#!/usr/bin/env python3
"""Explicit bounded first/Stop/replay recording. Never plays or stops media."""
import argparse
import collections
import fcntl
import hashlib
import json
import subprocess
from pathlib import Path
import time

ROOT = Path('/sys/module/rdma_mgr/parameters')
BOOT = Path('/proc/sys/kernel/random/boot_id')
FIELDS = 'index generation stamp source kind session phase batch handle reg value aux'.split()
PHASES = {'first': 1, 'stop': 2, 'replay': 3}
SOURCES = {1: 'lifecycle', 2: 'normal_rdma', 3: 'osd_rdma', 4: 'direct_write', 5: 'safe_read'}
EVENTS = {1: 'provider', 2: 'disable', 3: 'first_frame', 4: 'layer_switch',
          5: 'blend_state', 6: 'pps', 7: 'csc_post', 8: 'hdr_request',
          9: 'hdr_submitted', 10: 'hdr_disabled', 11: 'dcu_entry', 12: 'dcu_exit',
          13: 'pps_entry', 14: 'pps_exit', 15: 'pps_unsupported', 16: 'dcu_skipped', 17: 'pps_skipped', 18: 'csc_return'}
KINDS = {1: 'marker', 2: 'state', 3: 'prepare', 4: 'word', 5: 'irq', 6: 'cancel', 7: 'read'}


def read(name):
    return (ROOT / ('gxlx2_playback_' + name)).read_text()


def write(name, value):
    (ROOT / ('gxlx2_playback_' + name)).write_text(str(value) + '\n')


def state(text):
    result = {k: int(v) for k, v in (word.split('=') for word in text.split())}
    if set(result) != {'generation', 'status', 'count', 'capacity', 'overflow', 'phase'}:
        raise ValueError('Unknown playback schema')
    if result['status'] not in (0, 1, 2) or not 0 <= result['count'] <= result['capacity'] <= 65536:
        raise ValueError('Invalid playback state')
    return result


def decode(pages, expected):
    rows = []
    batches = {}
    for page in pages:
        for line in page.splitlines():
            words = line.split()
            if not words:
                continue
            if len(words) != len(FIELDS):
                raise ValueError('Unknown row schema')
            row = {key: int(value, 10 if i < 2 else 16)
                   for i, (key, value) in enumerate(zip(FIELDS, words))}
            if any(value < 0 or value > (2**64-1 if key == 'stamp' else 2**32-1)
                   for key, value in row.items()):
                raise ValueError('Out of range row')
            if row['index'] != len(rows) or row['generation'] != expected['generation']:
                raise ValueError('Missing/replaced playback rows')
            if row['source'] not in SOURCES or row['kind'] not in KINDS or row['phase'] not in (0, 1, 2, 3):
                raise ValueError('Invalid source/kind/phase')
            if rows and row['stamp'] < rows[-1]['stamp']:
                raise ValueError('Reversed kernel timestamps')
            if row['source'] in (2, 3) and row['kind'] in (3, 4, 5, 6):
                key = (row['source'], row['handle'], row['batch'])
                if not row['batch']:
                    raise ValueError('Writer table missing batch identity')
                if row['kind'] == 3:
                    if key in batches or row['aux'] == 0:
                        raise ValueError('Duplicate/empty prepared table')
                    batches[key] = {'total': row['aux'], 'last_item': -1, 'terminal': False,
                                    'mutable': row['source'] == 3 and row['value'] == 0}
                else:
                    batch = batches.get(key)
                    if batch is None or batch['terminal']:
                        raise ValueError('Table record without pending preparation')
                    if row['kind'] == 4:
                        if not (0 <= row['aux'] < batch['total']) or (not batch['mutable'] and row['aux'] <= batch['last_item']):
                            raise ValueError('Out-of-order/invalid table word')
                        batch['last_item'] = row['aux']
                    else:
                        batch['terminal'] = True
            rows.append(row)
    if len(rows) != expected['count']:
        raise ValueError('Incomplete export')
    return rows


def new_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def snapshot():
    result = {'host_time_ns': time.time_ns(), 'boot_id': BOOT.read_text().strip()}
    for name, path in {'decoder': '/sys/class/vdec/vdec_status', 'mode': '/sys/class/display/mode',
                       'global': '/sys/class/video/video_global_output',
                       'disable': '/sys/class/video/disable_video',
                       'hold': '/sys/module/amvideo/parameters/gxlx2_blend_hold',
                       'hdr_experiment': '/sys/module/am_vecm/parameters/gxlx2_hdr_recovery'}.items():
        try: result[name] = Path(path).read_text().strip()
        except OSError as error: result[name] = {'unavailable': str(error)}
    return result


def hdmi_snapshot(context, getter=None):
    """Only audited existing TX getters; no writes or arbitrary registers."""
    base = Path('/sys/class/amhdmitx/amhdmitx0')
    getter = getter or (lambda name: subprocess.run(
        ['cat', str(base/name)], check=True, capture_output=True,
        text=True, timeout=3).stdout.strip())
    result = {'host_time_ns': time.time_ns(), 'scope': 'TX configuration/AVMUTE status, not pixels on wire',
              'atomic_frame': False, 'values': {}}
    try:
        result['values']['hpd_state'] = getter('hpd_state')
        if (result['values']['hpd_state'] != '1' or context.get('global') != '1' or
            context.get('disable') != '0' or 'ammvdec_h264' not in context.get('decoder', '') or
            context.get('mode') in (None, '', 'null', 'invalid')):
            result['status'] = 'skipped_inactive'; return result
        # show_config reads TX AVI/input configuration and PLL registers;
        # show_avmute dispatches only MISC_READ_AVMUTE_OP -> read_avmute.
        for name in ('config', 'avmute'):
            result['values'][name] = getter(name)
        result['status'] = 'collected_status_only'
    except (OSError, subprocess.SubprocessError) as error:
        result.update(status='unavailable', error=str(error))
    return result


def arm(run, phase):
    run.mkdir(parents=True, exist_ok=True)
    manifest = run/'manifest.json'
    boot = BOOT.read_text().strip()
    if manifest.exists():
        if json.loads(manifest.read_text())['boot_id'] != boot:
            raise RuntimeError('Boot changed; use a new run')
    else:
        new_json(manifest, {'schema': 1, 'boot_id': boot,
                           'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           'scope': 'Bounded selected lifecycle/writer/readback records; not complete hardware execution or pixel proof'})
    owner = run/(phase+'.owner.json')
    # Claim this phase once; never overwrite or auto-repeat a failed experiment.
    with owner.open('x') as stream:
        initial = state(read('scan'))
        if initial['status'] == 1:
            raise RuntimeError('Another playback generation is active')
        write('phase', PHASES[phase])
        write('scan', 1)
        armed = state(read('scan'))
        if armed['generation'] != (initial['generation']+1) & 0xffffffff or armed['status'] != 1:
            raise RuntimeError('Generation changed during arm; no foreign cleanup')
        json.dump({'boot_id': boot, 'generation': armed['generation'], 'phase': phase}, stream)
    new_json(run/(phase+'.before.json'), snapshot())
    print(json.dumps({'phase': phase, 'generation': armed['generation'], 'action': 'armed; perform only the separately authorized media action, then freeze promptly'}))


def freeze(run, phase, hdmi=False):
    owner = json.loads((run/(phase+'.owner.json')).read_text())
    if owner['boot_id'] != BOOT.read_text().strip():
        raise RuntimeError('Boot changed; do not touch this recorder')
    current = state(read('scan'))
    if current['generation'] != owner['generation']:
        raise RuntimeError('Foreign generation; refusing to freeze')
    if current['status'] == 1:
        write('scan', 0)
    before = state(read('scan'))
    if before['status'] != 2 or before['generation'] != owner['generation']:
        raise RuntimeError('Recorder not frozen or replaced')
    pages = []
    # Kernel page size is 8 rows, matching the existing selected-table exporter.
    for page in range((before['count']+7)//8):
        write('page', page)
        pages.append(read('data'))
    if state(read('scan')) != before:
        raise RuntimeError('State changed during export')
    rows = decode(pages, before)
    after = snapshot()
    report = {'schema': 1, 'boot_id': owner['boot_id'], 'phase': phase,
              'state': before, 'pages': pages, 'records': rows, 'after': after}
    if hdmi:
        report['hdmi'] = hdmi_snapshot(after) if phase != 'stop' else {'status': 'skipped_real_stop'}
    new_json(run/(phase+'.json'), report)
    print(json.dumps({'phase': phase, 'rows': len(rows), 'overflow': before['overflow']}))



# Fixed source map: a changed value is a lead, never a root-cause verdict.
REGISTER_MAP = {
    0x1a50: ('VD1_IF0_GEN_REG', 'vd_set_dcu -> vd1_set_dcu', 'VD1 MIF'),
    0x1a51: ('VD1_IF0_CANVAS0', 'set_layer_display_canvas', 'Canvas selection'),
    0x1a68: ('VIU_VD1_FMT_CTRL', 'vd_set_dcu -> vd1_set_dcu', 'formatter'),
    0x1d04: ('VPP_SCALE_COEF', 'vd_scaler_setting', 'PPS coefficient stream'),
    0x1d19: ('VPP_SC_MISC', 'vd_scaler_setting', 'PPS'),
    0x1d25: ('VPP_POSTBLEND_CURRENT_XY', 'vpp_blend_update', 'dynamic status; not a restart control'),
    0x1d26: ('VPP_MISC', 'vpp_blend_update', 'blend'),
    0x1d28: ('VPP_FIFO_STATUS', 'vpp_blend_update', 'dynamic FIFO status'),
    0x3802: ('VD1_HDR2_MATRIXI_COEF00_01', 'set_hdr_matrix', 'HDR input matrix'),
    0x3804: ('VD1_HDR2_MATRIXI_COEF11_12', 'set_hdr_matrix', 'HDR input matrix'),
    0x3806: ('VD1_HDR2_MATRIXI_COEF22', 'set_hdr_matrix', 'HDR input matrix'),
    0x380e: ('VD1_HDR2_MATRIXO_COEF00_01', 'set_hdr_matrix', 'HDR output matrix'),
    0x3800: ('VD1_HDR2_CTRL', 'hdr_func', 'HDR configuration; no bypass bit assumption'),
}
FUNCTION_MAP = {1: 'video_receiver_event_fun', 2: '_video_set_disable',
                3: 'video_toggle_frame', 4: 'safe_switch_videolayer',
                5: 'vpp_blend_update', 6: 'vpp_set_super_scaler_regs',
                7: 'vpp_matrix_update -> video_post_process',
                8: 'hdr_func entry', 9: 'hdr_func submission end',
                10: 'hdr_func disable_flush return', 11: 'vd_set_dcu entry',
                12: 'vd_set_dcu exit', 13: 'vd_scaler_setting entry',
                14: 'vd_scaler_setting exit', 15: 'vd_scaler_setting unsupported return', 16: 'vd1_set_dcu null frame',
                17: 'vd1_scaler_setting missing input', 18: 'vpp_matrix_update return'}



RETURN_REASONS = {
    16: {1: 'vd1_set_dcu: null vf; no DCU configuration'},
    17: {1: 'vd1_scaler_setting: null setting', 2: 'vd1_scaler_setting: null frame_par'},
    18: {1: 'invalid/null vinfo', 2: 'HDR bypass state and layer not ready',
         3: 'Dolby Vision owns processing', 4: 'output mode change deferred',
         5: 'HDMI CSC CHECK_OUTPUT deferral', 6: 'no signal change and no toggle',
         7: 'normal function end; does not alone prove HDR submitted'},
}


def event_detail(row):
    result = dict(row, event=EVENTS.get(row['reg'], 'unknown'))
    if row['reg'] in RETURN_REASONS:
        result['return_reason'] = RETURN_REASONS[row['reg']].get(row['value'], 'unknown')
    return result


def localization(first, replay):
    """Align event classes/ordinals; expose unresolved asynchronous writes."""
    def indexed(rows):
        groups = collections.defaultdict(list)
        for row in rows:
            if row['source'] == 1 and row['kind'] == 2:
                groups[('call', row['reg'], row['handle'])].append(row)
            elif row['kind'] == 7:
                groups[('live', row['reg'], 0)].append(row)
        return groups
    left, right = indexed(first), indexed(replay)
    findings = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key, []), right.get(key, [])
        mode, reg, handle = key
        item = {'category': mode, 'code_or_register': hex(reg), 'handle': handle,
                'first_count': len(a), 'replay_count': len(b)}
        if mode == 'call':
            item['function'] = FUNCTION_MAP.get(reg, 'unmapped')
        else:
            name, function, meaning = REGISTER_MAP.get(reg, ('unmapped', 'unmapped', 'raw configuration'))
            item.update(register=name, function=function, meaning=meaning)
        if not a or not b:
            item.update(classification='MISSING_COVERAGE_OR_CALL',
                        evidence={'first': a[:1], 'replay': b[:1]},
                        limitation='An absent event can be outside the capture window; not proof a call was omitted.')
            findings.append(item); continue
        # Provider event IDs, frame indices/PTS and new-frame counts legitimately
        # differ. Counts/ordering are retained; do not turn those into failures.
        if mode == 'call':
            signatures = lambda rows: [(r['value'], r['aux']) for r in rows]
            if reg in (1, 2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18) and signatures(a) != signatures(b):
                i = next((i for i in range(min(len(a), len(b)))
                          if signatures(a)[i] != signatures(b)[i]), min(len(a), len(b)))
                item.update(classification='CALL_ARGUMENT_OR_COUNT_DIFFERENCE',
                            evidence={'first': a[i:i+1], 'replay': b[i:i+1]})
                findings.append(item)
        else:
            i = next((i for i in range(min(len(a),len(b))) if a[i]['value'] != b[i]['value']), None)
            if i is not None:
                item.update(classification='LIVE_VALUE_DIFFERENCE',
                            evidence={'first': a[i], 'replay': b[i]},
                            limitation='Ordinal samples are not synchronized scanlines; dynamic status and frame addresses may differ normally.')
                findings.append(item)
    def provenance(rows):
        writes = collections.defaultdict(list)
        result = []
        for row in rows:
            if row['kind'] == 4:
                writes[row['reg']].append(row)
            elif row['kind'] == 7:
                candidates = writes[row['reg']][-4:]
                result.append({'read': row, 'prior_selected_writes': candidates,
                               'matches_last_selected_write': None if not candidates else candidates[-1]['value'] == row['value'],
                               'limitation': 'Preparation/dispatch precedes hardware latch; mismatch is not a lost-write assertion.'})
        return result
    return {'status': 'CANDIDATES_REQUIRE_AUDIT', 'findings': findings,
            'readback_provenance': {'first': provenance(first), 'replay': provenance(replay)},
            'alignment': 'Same source event/register occurrence; raw index and kernel stamps retained. No claim of earliest physical pixel failure.',
            'coverage': {name: {'provider': any(r['source']==1 and r['reg']==1 for r in rows),
                               'hdr_request': any(r['source']==1 and r['reg']==8 for r in rows),
                               'hdr_submitted': any(r['source']==1 and r['reg']==9 for r in rows),
                               'safe_read': any(r['kind']==7 for r in rows),
                               'osd_window': any(r['source']==3 and r['kind']==3 for r in rows)}
                         for name, rows in [('first',first),('replay',replay)]}}


def compare(run):
    docs = {name: json.loads((run/(name+'.json')).read_text()) for name in PHASES}
    boot = json.loads((run/'manifest.json').read_text())['boot_id']
    parsed = {}
    for name, doc in docs.items():
        if doc['boot_id'] != boot or doc['state']['status'] != 2 or doc['state']['overflow']:
            raise ValueError('Foreign boot/active/overflowed phase: '+name)
        rows = decode(doc['pages'], doc['state'])
        if rows != doc['records'] or not any(r['kind'] == 1 and r['phase'] == PHASES[name] for r in rows):
            raise ValueError('Missing phase marker or altered derived records: '+name)
        if any(r['phase'] != PHASES[name] for r in rows):
            raise ValueError('Unassigned/mixed phase: '+name)
        parsed[name] = rows
    def streams(rows):
        result = collections.defaultdict(list)
        for r in rows:
            if r['kind'] in (4, 7):
                result[f"{SOURCES[r['source']]}:{r['reg']:04x}"].append(r['value'])
        return dict(result)
    a, b = streams(parsed['first']), streams(parsed['replay'])
    # Storage integrity alone is not display/teardown coverage. Historical
    # separate windows remain useful raw data, never a complete transition.
    missing = {}
    for name in ('first', 'replay'):
        codes = {r['reg'] for r in parsed[name] if r['source'] == 1 and r['kind'] == 2}
        missing[name] = [EVENTS[code] for code in (3, 11, 12, 13, 14, 8, 9) if code not in codes]
        if not any(r['source'] == 5 and r['kind'] == 7 for r in parsed[name]):
            missing[name].append('safe_read')
    changes = {key: {'first': a[key], 'replay': b[key]} for key in a.keys() & b.keys() if a[key] != b[key]}
    return {'schema': 1, 'boot_id': boot, 'classification': 'INCOMPLETE_TRANSITION',
            'coverage_gate': {'missing': missing,
                              'reason': 'Separate generations do not cover the Stop-to-replay gap; use continuous session collector'},
            'first_only': {k: a[k] for k in a.keys()-b.keys()},
            'replay_only': {k: b[k] for k in b.keys()-a.keys()}, 'changed_ordered_values': changes,
            'counts': {name: dict(collections.Counter(f"{SOURCES[r['source']]}:{KINDS[r['kind']]}" for r in rows)) for name, rows in parsed.items()},
            'lifecycle': {name: [event_detail(r) for r in rows if r['source'] == 1 and r['kind'] == 2] for name, rows in parsed.items()},
            'endpoint_status': {name: docs[name].get('hdmi', {'status': 'not_requested'}) for name in PHASES},
            'localization': localization(parsed['first'], parsed['replay']),
            'timeline': {name: rows for name, rows in parsed.items()},
            'limitations': ['Missing baseline is unknown, never zero/uninitialized.',
                           'Values retain repetition/order per address; full cross-address order is in timeline.',
                           'Software intent/preparation/IRQ, safe live readback and pixels are separate evidence.',
                           'Manual action/RPC, window coverage, source/session alignment and physical picture require audit.',
                           'Outside fixed register allowlist or unhooked paths are not covered.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('arm', 'freeze', 'compare'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--phase', choices=PHASES)
    parser.add_argument('--hdmi-status', action='store_true', help='Freeze only: audited TX getters on active H264; never read on Stop')
    args = parser.parse_args()
    if args.command == 'compare':
        print(json.dumps(compare(args.run), indent=2)); return
    if not args.phase: parser.error('--phase required')
    with open('/run/e900-playback.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'arm': arm(args.run, args.phase)
        else: freeze(args.run, args.phase, args.hdmi_status)


if __name__ == '__main__':
    main()
