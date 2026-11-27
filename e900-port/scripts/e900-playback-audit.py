#!/usr/bin/env python3
"""Explicit bounded first/Stop/replay recording. Never plays or stops media."""
import argparse
import collections
import fcntl
import hashlib
import json
from pathlib import Path
import time

ROOT = Path('/sys/module/rdma_mgr/parameters')
BOOT = Path('/proc/sys/kernel/random/boot_id')
FIELDS = 'index generation stamp source kind session phase batch handle reg value aux'.split()
PHASES = {'first': 1, 'stop': 2, 'replay': 3}
SOURCES = {1: 'lifecycle', 2: 'normal_rdma', 3: 'osd_rdma', 4: 'direct_write', 5: 'safe_read'}
EVENTS = {1: 'provider', 2: 'disable', 3: 'first_frame', 4: 'layer_switch',
          5: 'blend_state', 6: 'pps', 7: 'csc_post', 8: 'hdr_request',
          9: 'hdr_submitted', 10: 'hdr_disabled'}
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


def freeze(run, phase):
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
    new_json(run/(phase+'.json'), {'schema': 1, 'boot_id': owner['boot_id'],
             'phase': phase, 'state': before, 'pages': pages, 'records': rows, 'after': snapshot()})
    print(json.dumps({'phase': phase, 'rows': len(rows), 'overflow': before['overflow']}))


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
    changes = {key: {'first': a[key], 'replay': b[key]} for key in a.keys() & b.keys() if a[key] != b[key]}
    return {'schema': 1, 'boot_id': boot, 'classification': 'REVIEW_REQUIRED',
            'first_only': {k: a[k] for k in a.keys()-b.keys()},
            'replay_only': {k: b[k] for k in b.keys()-a.keys()}, 'changed_ordered_values': changes,
            'counts': {name: dict(collections.Counter(f"{SOURCES[r['source']]}:{KINDS[r['kind']]}" for r in rows)) for name, rows in parsed.items()},
            'lifecycle': {name: [dict(r, event=EVENTS.get(r['reg'], 'unknown')) for r in rows if r['source'] == 1 and r['kind'] == 2] for name, rows in parsed.items()},
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
    args = parser.parse_args()
    if args.command == 'compare':
        print(json.dumps(compare(args.run), indent=2)); return
    if not args.phase: parser.error('--phase required')
    with open('/run/e900-playback.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (arm if args.command == 'arm' else freeze)(args.run, args.phase)


if __name__ == '__main__':
    main()
