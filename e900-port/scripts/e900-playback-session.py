#!/usr/bin/env python3
"""Explicit first/reference/Stop-replay experiments; fail closed on missing coverage."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import runpy
import socket
import subprocess
import time

AUDIT = runpy.run_path(str(Path(__file__).with_name('e900-playback-audit.py')))
# Pinned vframe_receiver.h: PROVIDER_UNREG=1, PROVIDER_REG=8.
UNREG, REG = 1, 8


def create(path, value):
    AUDIT['new_json'](path, value)


def calls(rows, code):
    return [r for r in rows if r['source'] == 1 and r['kind'] == 2 and r['reg'] == code]


def display_coverage(rows):
    registrations = [r for r in calls(rows, 1) if r['value'] == REG]
    if not registrations:
        return {'complete': False, 'missing': ['provider_registration']}
    provider = registrations[-1]
    rows = [r for r in rows if r['index'] >= provider['index'] and r['session'] == provider['session']]
    required = {3: 'first_frame', 11: 'dcu_entry', 13: 'pps_entry', 18: 'csc_return'}
    missing = [name for code, name in required.items() if not calls(rows, code)]
    # An observed no-op return is coverage, not proof of configuration success.
    # vd_scaler_setting's unsupported return (15) replaces its normal exit (14).
    for entry, exits in ((11, (12,)), (13, (14, 15))):
        pending = 0
        invalid = False
        for r in rows:
            if r['source'] != 1 or r['kind'] != 2:
                continue
            if r['reg'] == entry:
                pending += 1
            elif r['reg'] in exits:
                pending -= 1
                invalid |= pending < 0
        if pending or invalid:
            missing.append('unbalanced_'+required[entry])
    hdr_pending = []
    for r in rows:
        if r['source'] != 1 or r['kind'] != 2 or r['handle'] != 1:
            continue
        if r['reg'] == 8:
            hdr_pending.append(r['value'])
        elif r['reg'] == 9:
            if not hdr_pending or hdr_pending.pop(0) != r['value']:
                missing.append('unmatched_hdr_submission')
    if hdr_pending:
        missing.append('unreturned_hdr_request')
    for code, known in ((16, (1,)), (17, (1,2)), (18, tuple(range(1,8)))):
        if any(r['value'] not in known for r in calls(rows, code)):
            missing.append('unknown_return_reason_'+str(code))
    reads = {r['reg'] for r in rows if r['source'] == 5 and r['kind'] == 7}
    missing += ['read_'+hex(reg) for reg in (0x1a50, 0x1d26, 0x1d28, 0x3800) if reg not in reads]
    return {'complete': not missing, 'missing': missing,
            'disposition': {'dcu_skipped': [r['value'] for r in calls(rows,16)],
                            'pps_unsupported': bool(calls(rows,15)),
                            'pps_skipped': [r['value'] for r in calls(rows,17)],
                            'csc_returns': sorted({r['value'] for r in calls(rows,18)}),
                            'hdr_requested': bool([r for r in calls(rows,8) if r['handle']==1]),
                            'hdr_flush_disabled': bool([r for r in calls(rows,10) if r['handle']==1])},
            'scope': 'Selected software boundaries and guarded reads, not pixel proof'}


def stopped(rows, context):
    return (context.get('decoder') == 'No vdec.' and context.get('disable') == '1'
            and any(r['value'] == UNREG for r in calls(rows, 1))
            and any(r['value'] == 1 for r in calls(rows, 2)))


def reference_ready(rows, context):
    reads = [r for r in rows if r['source'] == 5 and r['kind'] == 7]
    return (context.get('disable') == '0' and context.get('global') == '1'
            and sum(r['reg']==0x1d28 and r['value']!=0 for r in reads)>=2
            and all(any(r['reg']==reg for r in reads) for reg in (0x1a50,0x1d26,0x3800)))


class LiveRows:
    """Read immutable append-only prefixes; never re-arm to make space."""
    def __init__(self, generation, reader=None, writer=None):
        self.generation = generation
        self.read = reader or AUDIT['read']
        self.write = writer or AUDIT['write']
        self.rows = []

    def poll(self):
        before = AUDIT['state'](self.read('scan'))
        if before['generation'] != self.generation or before['overflow'] or before['status'] != 1:
            raise RuntimeError('Foreign/frozen/overflowed recorder; keep evidence and stop')
        count = before['count']
        if count < len(self.rows):
            raise RuntimeError('Live prefix shrank')
        for page in range(len(self.rows)//8, (count+7)//8):
            self.write('page', page)
            for line in self.read('data').splitlines():
                words = line.split()
                if len(words) != len(AUDIT['FIELDS']):
                    raise RuntimeError('Malformed live row')
                r = {key: int(value, 10 if i < 2 else 16)
                     for i, (key, value) in enumerate(zip(AUDIT['FIELDS'], words))}
                if r['generation'] != self.generation:
                    raise RuntimeError('Live row generation replaced')
                if r['index'] < len(self.rows) or r['index'] >= count:
                    continue
                if r['index'] != len(self.rows):
                    raise RuntimeError('Gap in live prefix')
                self.rows.append(r)
        after = AUDIT['state'](self.read('scan'))
        if after['generation'] != self.generation or after['overflow'] or after['status'] != 1:
            raise RuntimeError('Recorder changed during live read')
        if len(self.rows) != count:
            raise RuntimeError('Incomplete live prefix')
        return self.rows


def rpc(method, params, log):
    item = {'method': method, 'params': params, 'send_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
    log.append(item)
    try:
        with socket.create_connection(('127.0.0.1', 9090), 3) as conn:
            conn.settimeout(5)
            conn.sendall(json.dumps({'jsonrpc': '2.0', 'id': 71, 'method': method, 'params': params}).encode())
            buf = ''
            while len(buf) < 65536:
                chunk = conn.recv(8192)
                if not chunk:
                    raise RuntimeError('Incomplete RPC response')
                buf += chunk.decode()
                while buf.strip():
                    try:
                        value, end = json.JSONDecoder().raw_decode(buf.lstrip())
                    except ValueError:
                        break
                    buf = buf.lstrip()[end:]
                    if value.get('id') != 71:
                        continue
                    item['response'] = value
                    if 'error' in value:
                        raise RuntimeError(str(value['error']))
                    return value['result']
        raise RuntimeError('RPC response too large')
    except Exception as error:
        item['error'] = str(error)
        raise
    finally:
        item['return_boottime_ns'] = time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def wait_for(trace, predicate, timeout, stable=0):
    deadline, since = time.monotonic()+timeout, None
    while time.monotonic() < deadline:
        rows = trace.poll()
        if predicate(rows, AUDIT['snapshot']()):
            since = since if since is not None else time.monotonic()
            if time.monotonic()-since >= stable:
                return
        else:
            since = None
        time.sleep(.02)
    raise RuntimeError('Coverage/state timeout; no further media action permitted')


def checked_policy(reader=None):
    reader = reader or (lambda module, name: Path('/sys/module',module,'parameters',name).read_text().strip())
    values = {}
    for module, name in (('amvideo','gxlx2_g12_mif'), ('amvideo','gxlx2_gen3_clear_high'),
                         ('fb','gxlx2_osd_blender_only')):
        value = reader(module,name)
        values[module+'.'+name] = value
        if value not in ('N','0'):
            raise RuntimeError('Display experiment still enabled: '+module+'.'+name)
    for name in ('gxlx2_pixel_scan','gxlx2_edge_scan'):
        value = dict(word.split('=',1) for word in reader('amvideo',name).split() if '=' in word)
        if value.get('status') not in ('0','3','4') or value.get('owned','0') != '0':
            raise RuntimeError('Pixel/edge probe active or not safely retired: '+name)
        values['amvideo.'+name] = {key:value.get(key) for key in ('status','owned')}
    for module in ('amvideo','am_vecm','rdma','rdma_mgr','fb','register_ops','di','vpu'):
        for name in ('gxlx2_debug_events','gxlx2_gen3_rmw_events'):
            try:
                value = reader(module,name)
            except FileNotFoundError:
                continue  # This optional logging knob is not compiled in.
            values[module+'.'+name] = value
            if value != '0':
                raise RuntimeError('Verbose event channel active: '+module+'.'+name)
    return values


def preflight():
    api = Path('/sys/module/rdma_mgr/parameters/gxlx2_playback_live_api')
    if not api.is_file() or api.read_text().strip() != '1':
        raise RuntimeError('Requires 0043 live API; no media action performed')
    status = AUDIT['state'](AUDIT['read']('scan'))
    if status['status'] == 1 or status['capacity'] < 65536:
        raise RuntimeError('Busy recorder or insufficient supported capacity')
    c = AUDIT['snapshot']()
    if c.get('hdr_experiment') not in ('N', '0') or c.get('hold') != '0' or c.get('global') != '1':
        raise RuntimeError('Nondefault display policy; refusing experiment')
    if Path('/sys/module/amvideo/parameters/gxlx2_hw_init_status').read_text().strip() != '2':
        raise RuntimeError('Video init incomplete')
    if Path('/sys/module/amvideo/parameters/gxlx2_stage_samples').read_text().strip() != '0':
        raise RuntimeError('Verbose legacy stage probes active')
    if Path('/sys/module/rdma/parameters/enable').read_text().strip() != '1,0':
        raise RuntimeError('RDMA policy differs from reference')
    c['checked_policy'] = checked_policy()
    return c


def execute(args):
    context = preflight()
    args.run.mkdir(parents=True, exist_ok=True)
    folder = args.run/args.action
    folder.mkdir(exist_ok=False)
    phase = 'stop' if args.action == 'transition' else 'first'
    report = {'status': 'INCOMPLETE', 'action': args.action, 'boot_id': context['boot_id'],
              'rpc': [], 'file': args.file, 'before': context,
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'kernel_version': platform.uname().version, 'timeout_seconds': args.timeout}
    armed = False
    try:
        if args.action == 'first':
            if context['decoder'] != 'No vdec.':
                raise RuntimeError('First playback requires no existing decoder')
        else:
            previous = json.loads((args.run/('reference' if args.action == 'transition' else 'first')/'result.json').read_text())
            if previous['status'] != 'COVERED_REQUIRES_VISUAL' or previous['boot_id'] != context['boot_id'] or previous['file'] != args.file:
                raise RuntimeError('Missing covered same-boot/file prerequisite')
            if args.action == 'reference' and not args.confirmed_normal:
                raise RuntimeError('Explicit normal visual confirmation required')
            if args.action == 'transition' and not previous.get('confirmed_normal'):
                raise RuntimeError('No independent confirmed normal reference')
            active = rpc('Player.GetItem', {'playerid': 1, 'properties': ['file']}, report['rpc'])
            if active.get('item', {}).get('file') != args.file or context['disable'] != '0':
                raise RuntimeError('Baseline player/file/layer changed')
        rpc('Application.SetVolume', {'volume': 0}, report['rpc'])
        with (folder/'before.dmesg').open('w') as stream:
            subprocess.run(['dmesg'], stdout=stream, check=True)
        AUDIT['arm'](folder, phase)
        owner = json.loads((folder/(phase+'.owner.json')).read_text())
        armed = True
        trace = LiveRows(owner['generation'])
        if args.action == 'first':
            rpc('Player.Open', {'item': {'file': args.file}}, report['rpc'])
            wait_for(trace, lambda rows, c: display_coverage(rows)['complete'] and c['disable']=='0', args.timeout, stable=.3)
        elif args.action == 'reference':
            # The user already confirmed the physical picture; collect a separate
            # guarded reference before issuing any Stop. No playback action here.
            wait_for(trace, reference_ready, args.timeout)
            report['confirmed_normal'] = True
        else:
            rpc('Player.Stop', {'playerid': 1}, report['rpc'])
            wait_for(trace, stopped, args.timeout, stable=.3)
            report['stop_boundary'] = {'rows': len(trace.rows), 'context': AUDIT['snapshot'](),
                'scope': 'Provider/disable observed, No vdec and disable=1 stable 300ms; not proof every delayed work item completed'}
            # Same generation, no freeze/re-arm/export gap across Stop→replay.
            AUDIT['write']('phase', 3)
            rpc('Player.Open', {'item': {'file': args.file}}, report['rpc'])
            wait_for(trace, lambda rows, c: display_coverage([r for r in rows if r['phase']==3])['complete'] and c['disable']=='0', args.timeout, stable=.3)
        report['status'] = 'COVERED_REQUIRES_VISUAL'
    except Exception as error:
        report['error'] = str(error)
    finally:
        if not armed and (folder/(phase+'.owner.json')).exists():
            # arm() can fail after claiming a generation (e.g. snapshot I/O).
            # Let freeze() verify ownership; never touch an unowned recorder.
            try:
                owner = json.loads((folder/(phase+'.owner.json')).read_text())
                armed = owner['boot_id'] == context['boot_id']
            except (OSError, ValueError, KeyError):
                pass
        if armed:
            try:
                AUDIT['freeze'](folder, phase, hdmi=(args.action!='transition'))
                doc = json.loads((folder/(phase+'.json')).read_text())
                report['state'] = doc['state']
                report['coverage'] = {str(p): display_coverage([r for r in doc['records'] if r['phase']==p]) for p in (1,3)}
                if doc['state']['overflow']:
                    report.update(status='INCOMPLETE', error='Recorder overflow')
                elif args.action in ('first', 'transition'):
                    required_phase = '3' if args.action == 'transition' else '1'
                    if not report['coverage'][required_phase]['complete']:
                        report.update(status='INCOMPLETE', error='Final frozen window lacks display coverage')
                elif not reference_ready(doc['records'], doc['after']):
                    report.update(status='INCOMPLETE', error='Final frozen normal reference invalid')
            except Exception as error:
                report.update(status='INCOMPLETE', export_error=str(error))
        report['after'] = AUDIT['snapshot']()
        try:
            with (folder/'after.dmesg').open('w') as stream:
                subprocess.run(['dmesg'], stdout=stream, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            report['dmesg_error'] = str(error)
        create(folder/'result.json', report)
    print(json.dumps(report, indent=2))
    if report['status'] == 'INCOMPLETE':
        raise RuntimeError('Experiment incomplete; inspect saved result, do not continue')


def compare_session(run):
    results, docs = {}, {}
    boot = None
    for name, phase in (('first', 'first'), ('reference', 'first'), ('transition', 'stop')):
        folder = run/name
        result = json.loads((folder/'result.json').read_text())
        doc = json.loads((folder/(phase+'.json')).read_text())
        owner = json.loads((folder/(phase+'.owner.json')).read_text())
        manifest = json.loads((folder/'manifest.json').read_text())
        boot = boot or result['boot_id']
        if any(x['boot_id'] != boot for x in (result, doc, owner, manifest)):
            raise ValueError('Foreign boot in session')
        if result['status'] != 'COVERED_REQUIRES_VISUAL' or doc['state']['overflow'] or doc['state']['status'] != 2:
            raise ValueError('Incomplete session phase: '+name)
        if owner['generation'] != doc['state']['generation']:
            raise ValueError('Replaced generation')
        if result.get('state') != doc['state']:
            raise ValueError('Result belongs to another frozen window')
        expected_phase = 3 if name == 'transition' else 1
        if doc['state']['phase'] != expected_phase:
            raise ValueError('Wrong final phase')
        rows = AUDIT['decode'](doc['pages'], doc['state'])
        if rows != doc['records']:
            raise ValueError('Altered raw records')
        if not rows or rows[0]['kind'] != 1 or rows[0]['phase'] != (2 if name=='transition' else 1):
            raise ValueError('Missing initial marker')
        if name != 'transition' and any(r['phase'] != 1 for r in rows):
            raise ValueError('Mixed baseline phases')
        results[name], docs[name] = result, doc
    hashes = {r.get('runner_sha256', '') for r in results.values()}
    if len(hashes) != 1 or len(next(iter(hashes))) != 64:
        raise ValueError('Missing/mixed executor versions')
    policies = [r['before'].get('checked_policy') for r in results.values()]
    if not policies[0] or any(policy != policies[0] for policy in policies):
        raise ValueError('Missing/mixed experiment policy snapshots')
    collectors = {json.loads((run/n/'manifest.json').read_text()).get('collector_sha256', '') for n in results}
    if len(collectors) != 1 or len(next(iter(collectors))) != 64:
        raise ValueError('Missing/mixed collector versions')
    for left, right in (('first','reference'), ('reference','transition')):
        if (docs[right]['state']['generation']-docs[left]['state']['generation']) & 0xffffffff != 1:
            raise ValueError('Nonconsecutive experiment generations')
        if docs[right]['records'][0]['stamp'] < docs[left]['records'][-1]['stamp']:
            raise ValueError('Reordered/overlapping experiment windows')
    rows = docs['transition']['records']
    split = next((i for i,r in enumerate(rows) if r['source']==1 and r['kind']==1 and r['phase']==3), None)
    if split is None or any(r['phase']!=2 for r in rows[:split]) or any(r['phase']!=3 for r in rows[split:]):
        raise ValueError('Missing/reversed continuous phase boundary')
    if not stopped(rows[:split], results['transition']['stop_boundary']['context']):
        raise ValueError('Missing asynchronous Stop boundary')
    for name, selected in [('first', docs['first']['records']), ('replay', rows[split:])]:
        if not display_coverage(selected)['complete']:
            raise ValueError('Missing display coverage: '+name)
    if not results['reference'].get('confirmed_normal'):
        raise ValueError('No normal reference confirmation')
    reference = docs['reference']
    if not reference_ready(reference['records'], reference['after']):
        raise ValueError('Missing independent guarded reference samples')
    baseline_session = [r for r in calls(docs['first']['records'],1) if r['value']==REG][-1]['session']
    if any(r['session']!=baseline_session for r in reference['records'] if r['source']==5 and r['kind']==7):
        raise ValueError('Normal reference belongs to another playback session')
    replay_session = [r for r in calls(rows[split:],1) if r['value']==REG][-1]['session']
    if replay_session == baseline_session:
        raise ValueError('Replay did not enter a new provider session')
    if len({r['file'] for r in results.values()}) != 1:
        raise ValueError('File changed')
    # Continuous transition proves the recorder had no freeze/re-arm gap;
    # it cannot prove an unhooked hardware writer or pixel stage is healthy.
    return {'classification': 'REVIEW_REQUIRED', 'boot_id': boot,
            'localization': AUDIT['localization'](docs['first']['records'], rows[split:]),
            'reference_records': docs['reference']['records'],
            'normal_reference_readback_comparison': AUDIT['localization'](
                [r for r in reference['records'] if r['source']==5],
                [r for r in rows[split:] if r['source']==5]),
            'continuous_transition': rows,
            'limitations': ['Visual replay outcome must be supplied separately.',
                            'Coverage gates do not prove physical pixel output or complete delayed-work teardown.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('first','reference','transition','compare'))
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--file', default='/storage/videos/Test-H264-720p-20min.mp4')
    p.add_argument('--timeout', type=float, default=6)
    p.add_argument('--confirmed-normal', action='store_true')
    a = p.parse_args()
    if a.action == 'compare':
        print(json.dumps(compare_session(a.run), indent=2))
        return
    if not 0 < a.timeout <= 15:
        p.error('timeout must be >0 and <=15 seconds; never implies ring capacity is sufficient')
    with open('/run/e900-playback.lock','w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(a)


if __name__ == '__main__':
    main()
