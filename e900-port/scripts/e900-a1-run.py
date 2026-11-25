#!/usr/bin/env python3
"""Build291 A1 only. Invoke each stage explicitly after the preceding review/consent.

This never reboots, releases video init, starts VDIN, restarts playback, or retries a pulse.
"""
import argparse
import codecs
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback

VIDEO = Path('/sys/class/video')
PARAM = Path('/sys/module/amvideo/parameters')
DECODER = Path('/sys/class/vdec/vdec_status')
BOOT = Path('/proc/sys/kernel/random/boot_id')
SAMPLE = '/storage/videos/Test-H264-720p-20min.mp4'
TOOL_NAMES = ('e900-register-transition.py', 'e900-transition.py', 'e900-submit-trace.py',
              'e900-loopback.py', 'inspect-vdin-snapshot.py', 'e900-capture-ready.sh',
              'e900-debug.py', 'e900-start-capture.sh')


def read(path):
    return Path(path).read_text().strip()


def atomic_new(path, obj):
    with Path(path).open('x') as stream:
        json.dump(obj, stream, indent=2)
        stream.write('\n')


def interrupted(_signum, _frame):
    raise RuntimeError('Signal interrupted A1; collector cleanup required')


def snapshot():
    fields = {'boot_id': BOOT, 'video_init': PARAM/'gxlx2_hw_init_status',
              'global_output': VIDEO/'video_global_output', 'disable_video': VIDEO/'disable_video',
              'hold': PARAM/'gxlx2_blend_hold', 'gen3': PARAM/'gxlx2_gen3_clear_high',
              'decoder': DECODER, 'display_mode': Path('/sys/class/display/mode'),
              'rdma': Path('/sys/module/rdma/parameters/enable'),
              'edge_scan': PARAM/'gxlx2_edge_scan',
              'submit_scan': Path('/sys/module/rdma_mgr/parameters/gxlx2_submit_scan'),
              'os_release': Path('/etc/os-release')}
    result = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    for name, path in fields.items():
        try: result[name] = read(path)
        except Exception as exc: result[name] = {'error': str(exc)}
    for name, cmd in (('uname', ['uname', '-a']), ('df_storage', ['df', '-k', '/storage']),
                      ('df_flash', ['df', '-k', '/flash'])):
        try: result[name] = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception as exc: result[name] = {'error': str(exc)}
    session = Path('/storage/e900-capture/session.txt')
    try: result['vdin_session'] = session.read_text() if session.exists() else None
    except OSError as exc: result['vdin_session'] = {'error': str(exc)}
    return result


def save_dmesg(run, name):
    try:
        result = subprocess.run(['dmesg'], capture_output=True, timeout=10)
        (run/name).write_bytes(result.stdout)
        if result.stderr: (run/(name+'.stderr')).write_bytes(result.stderr)
    except Exception as exc:
        (run/(name+'.error')).write_text(str(exc)+'\n')


def rpc(run, method, params):
    request = {'jsonrpc': '2.0', 'id': int(time.time_ns() % 1000000000),
               'method': method, 'params': params}
    record = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'request': request}
    chunks = []
    try:
        with socket.create_connection(('127.0.0.1', 9090), 3) as conn:
            conn.settimeout(5)
            conn.sendall(json.dumps(request).encode())
            buffer = ''
            total = 0
            deadline = time.monotonic() + 5
            decoder = codecs.getincrementaldecoder('utf-8')()
            while total < 65536 and time.monotonic() < deadline:
                conn.settimeout(max(.001, deadline - time.monotonic()))
                chunk = conn.recv(8192)
                if not chunk: break
                chunks.append(chunk)
                total += len(chunk)
                if total > 65536: raise RuntimeError('Oversized JSON-RPC reply')
                buffer += decoder.decode(chunk)
                while buffer.strip():
                    try: reply, end = json.JSONDecoder().raw_decode(buffer.lstrip())
                    except json.JSONDecodeError: break
                    buffer = buffer.lstrip()[end:]
                    if reply.get('id') != request['id']: continue
                    record['raw_reply'] = b''.join(chunks).decode(errors='replace')
                    record['reply'] = reply
                    if 'error' in reply: raise RuntimeError('JSON-RPC error: '+str(reply['error']))
                    return reply.get('result')
            raise RuntimeError('Missing or oversized JSON-RPC reply')
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        record['raw_reply'] = b''.join(chunks).decode(errors='replace')
        with (run/'rpc.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')


def frame_count(status):
    match = re.search(r'^\s*frame count\s*:\s*(\d+)\s*$', status, re.MULTILINE)
    if not match: raise RuntimeError('Cannot parse decoder frame count')
    return int(match.group(1))


def playback_remaining(run):
    active = rpc(run, 'Player.GetActivePlayers', {})
    if len(active) != 1 or active[0].get('type') != 'video': raise RuntimeError('Exactly one video player required')
    playerid = active[0]['playerid']
    item = rpc(run, 'Player.GetItem', {'playerid': playerid, 'properties': ['file']})
    if item.get('item', {}).get('file') != SAMPLE: raise RuntimeError('Current player item differs from benchmark')
    props = rpc(run, 'Player.GetProperties', {'playerid': playerid,
              'properties': ['time', 'totaltime', 'speed']})
    def seconds(value):
        return value['hours']*3600+value['minutes']*60+value['seconds']+value.get('milliseconds', 0)/1000
    if props.get('speed') != 1 or seconds(props['totaltime'])-seconds(props['time']) < 180:
        raise RuntimeError('Playback paused or less than 180 seconds remain')
    return {'playerid': playerid, 'item': item, 'properties': props}


def prepare(run, tools, tools_commit):
    if run.exists(): raise FileExistsError(f'Run exists: {run}')
    if not run.is_absolute() or not tools.is_absolute(): raise ValueError('Use absolute paths')
    snap = snapshot()
    if shutil.disk_usage(run.parent).free < 128*1024*1024: raise RuntimeError('Need 128 MiB free')
    if snap['video_init'] != '2' or snap['hold'] != '0' or snap['gen3'] != 'N':
        raise RuntimeError('Unexpected video init/hold/GEN3; do not alter existing settings')
    if snap['global_output'] != '1' or snap['disable_video'] != '0':
        raise RuntimeError('Unexpected global output/layer disable')
    if snap['display_mode'] != '1080p60hz' or not isinstance(snap['rdma'], str) or not snap['rdma']:
        raise RuntimeError('Output/RDMA baseline missing or differs; stop for review')
    for name, active in (('edge_scan', (1, 2, 6)), ('submit_scan', (1,))):
        status = re.search(r'\bstatus=(\d+)\b', str(snap[name]))
        if status is None or int(status.group(1)) in active:
            raise RuntimeError('Unknown/active recorder or deferred cleanup: '+name)
    missing = [name for name in TOOL_NAMES if not (tools/name).is_file()]
    if missing: raise FileNotFoundError(f'Missing tools: {missing}')
    run.mkdir(mode=0o700)
    (run/'scripts').mkdir()
    hashes = {}
    for name in TOOL_NAMES:
        src = tools/name
        hashes[name] = hashlib.sha256(src.read_bytes()).hexdigest()
        shutil.copy2(src, run/'scripts'/name)
    shutil.copy2(Path(__file__), run/'scripts'/'e900-a1-run.py')
    manifest = {'experiment': 'A1', 'boot_id': snap['boot_id'], 'os_commit': 'unknown; identify from deployed build provenance',
                'tools_commit': tools_commit,
                'tool_sha256': hashes, 'sample': SAMPLE, 'output_mode': 'unknown',
                'rdma': snap['rdma'], 'audio_volume': 'unknown', 'authorization': 'record user reply separately',
                'unique_variable': 'gxlx2_blend_hold=3; global_output pulse 0.2s',
                'fixed': 'same Build291 boot, 1080p60, one VDIN session, GEN3=N, RDMA unchanged'}
    manifest['output_mode'] = snap['display_mode']
    atomic_new(run/'manifest.json', manifest)
    atomic_new(run/'preparation.json', snap)
    print(json.dumps({'run': str(run), 'boot_id': snap['boot_id'], 'tool_sha256': hashes}, indent=2))


def require_run(run, stage):
    if not run.is_absolute() or not run.is_dir(): raise ValueError('Existing absolute run directory required')
    if (run/(stage + '.started')).exists() or (run/(stage + '.json')).exists():
        raise RuntimeError(f'{stage} already attempted in this run; no automatic repeat')
    manifest = json.loads((run/'manifest.json').read_text())
    if manifest['boot_id'] != read(BOOT): raise RuntimeError('Boot changed; stop this run')
    with (run/(stage + '.started')).open('x') as marker:
        marker.write(snapshot()['utc']+'\n')
    return manifest


def baseline(run):
    require_run(run, 'baseline')
    report = {'boot_id': read(BOOT), 'stage': 'baseline', 'steps': [], 'status': 'started'}
    owned = None
    sub = runpy.run_path(str(run/'scripts'/'e900-submit-trace.py'))
    try:
        snap = snapshot()
        atomic_new(run/'baseline-before.json', snap)
        if snap['video_init'] != '2' or snap['decoder'] != 'No vdec.': raise RuntimeError('Not a fresh first playback')
        if snap['global_output'] != '1' or snap['hold'] != '0' or snap['gen3'] != 'N': raise RuntimeError('Wrong baseline params')
        rpc(run, 'JSONRPC.Ping', {})
        if rpc(run, 'Player.GetActivePlayers', {}): raise RuntimeError('Kodi already playing')
        rpc(run, 'Application.SetVolume', {'volume': 0})
        volume = rpc(run, 'Application.GetProperties', {'properties': ['volume']})
        if volume.get('volume') != 0: raise RuntimeError('Mute readback failed')
        # Same global lock as the standalone recorder and transition collector.
        global_lock = open('/run/e900-submit.lock', 'w')
        fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = sub['state'](sub['read']('scan'))
        if state['status'] == 1: raise RuntimeError('Another submit recorder active')
        expected = (state['generation']+1) & 0xffffffff
        sub['write']('scan', 1)
        state = sub['state'](sub['read']('scan'))
        if state['generation'] != expected or state['status'] != 1: raise RuntimeError('Submit recorder replaced')
        owned = expected
        report['initial_submit_generation'] = owned
        (run/'baseline-open-attempted').write_text(snapshot()['utc']+'\n')
        rpc(run, 'Player.Open', {'item': {'file': SAMPLE}})
        for _ in range(60):
            if 'ammvdec_h264' in read(DECODER): break
            time.sleep(.2)
        else: raise RuntimeError('Decoder not confirmed; inspect player state before any further action')
        first = frame_count(read(DECODER))
        time.sleep(1)
        second = frame_count(read(DECODER))
        if second <= first: raise RuntimeError('Decoder frame count did not advance')
        report['frame_count_first'] = first
        report['frame_count_second'] = second
        report['playback'] = playback_remaining(run)
        report['decoder'] = read(DECODER)
        report['status'] = 'first_playback_confirmed'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = str(exc)
        raise
    finally:
        if owned is not None:
            try:
                state = sub['state'](sub['read']('scan'))
                if state['generation'] == owned:
                    if state['status'] == 1: sub['write']('scan', 0)
                    atomic_new(run/'initial-submit.json', sub['export']())
                    report['initial_submit_state'] = sub['state'](sub['read']('scan'))
                else: report['submit_cleanup_error'] = 'Generation replaced; foreign recorder untouched'
            except Exception as exc: report['submit_cleanup_error'] = str(exc)
        report['final_snapshot'] = snapshot()
        atomic_new(run/'baseline.json', report)
        if 'global_lock' in locals(): global_lock.close()


def run_collector(run, tools):
    collector = runpy.run_path(str(tools/'e900-register-transition.py'))
    submit = runpy.run_path(str(tools/'e900-submit-trace.py'))
    loopback = runpy.run_path(str(tools/'e900-loopback.py'))
    image_capture = loopback['Loopback'](run/'transition-images')
    result = collector['collect'](collector['EDGE']['Kernel'](), True, False, submit,
                                  off_seconds=.2, image_capture=image_capture)
    result['boot_id'] = read(BOOT)
    result['loopback_calibration_claimed'] = True
    result['policy_after'] = {name: read(PARAM/name)
                              for name in ('gxlx2_blend_hold', 'gxlx2_gen3_clear_high')}
    atomic_new(run/'transition.json', result)
    print(json.dumps({k: result.get(k) for k in ('status', 'error', 'submission_evidence_complete', 'image_evidence_complete')}))
    return 0 if result['status'].startswith('collected_') and result['submission_evidence_complete'] and result['image_evidence_complete'] else 2


def pulse(run):
    manifest = require_run(run, 'pulse')
    report = {'stage': 'pulse', 'boot_id': manifest['boot_id'], 'status': 'started'}
    tools = run/'scripts'
    hold = PARAM/'gxlx2_blend_hold'
    changed_hold = False
    locks = []
    old_signals = {}
    try:
        snap = snapshot(); atomic_new(run/'pulse-before.json', snap)
        save_dmesg(run, 'dmesg-before.txt')
        (run/'decoder-before.txt').write_text(str(snap['decoder'])+'\n')
        for name, expected in manifest['tool_sha256'].items():
            if hashlib.sha256((tools/name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Archived tool changed: '+name)
        if not (run/'baseline.json').exists() or json.loads((run/'baseline.json').read_text()).get('status') != 'first_playback_confirmed':
            raise RuntimeError('Fresh first playback not confirmed')
        if 'ammvdec_h264' not in snap['decoder'] or snap['global_output'] != '1' or snap['hold'] != '0' or snap['gen3'] != 'N' or snap['disable_video'] != '0':
            raise RuntimeError('A1 preconditions changed')
        if snap['display_mode'] != manifest['output_mode'] or snap['rdma'] != manifest['rdma']:
            raise RuntimeError('Mode/RDMA changed')
        report['playback'] = playback_remaining(run)
        before_count = frame_count(snap['decoder'])
        time.sleep(.5)
        if frame_count(read(DECODER)) <= before_count: raise RuntimeError('Decoder did not advance before pulse')
        session = snap['vdin_session'] or ''
        if f'boot_id={manifest["boot_id"]}' not in session: raise RuntimeError('No same-boot VDIN session')
        if not (run/'CURRENT-CALIBRATION-CONFIRMED.txt').exists(): raise RuntimeError('Record same-route calibration in CURRENT-CALIBRATION-CONFIRMED.txt')
        # The collector itself checks a fresh calibrated image pair before mutating global.
        # A separate screen report may be recorded but is not required for this same-route run.
        for name in ('e900-edge', 'e900-pixel-probe', 'e900-submit', 'e900-loopback'):
            lock = open('/run/'+name+'.lock', 'w')
            locks.append(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        edge = runpy.run_path(str(tools/'e900-transition.py'))
        submit = runpy.run_path(str(tools/'e900-submit-trace.py'))
        edge_state = edge['state'](edge['Kernel']().read('scan'))
        submit_state = submit['state'](submit['read']('scan'))
        if edge_state['status'] in (1, 2, 6) or submit_state['status'] == 1:
            raise RuntimeError('Another recorder active or deferred cleanup')
        recorders_before = {'edge': edge_state, 'submit': submit_state}
        report['recorders_before'] = recorders_before
        for sig in (signal.SIGHUP, signal.SIGTERM):
            old_signals[sig] = signal.signal(sig, interrupted)
        hold.write_text('3\n'); changed_hold = True
        if read(hold) != '3': raise RuntimeError('Hold readback mismatch')
        cmd = [str(tools/'e900-register-transition.py'), '--off-seconds', '0.2',
               '--with-submissions', '--with-loopback', '--loopback-calibrated',
               '--exercise-global-output', '--out', str(run/'transition.json')]
        report['command'] = cmd
        atomic_new(run/'collector-command.json', {'argv': cmd, 'utc': snapshot()['utc']})
        with (run/'collector.stdout').open('x') as out, (run/'collector.stderr').open('x') as err:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                report['exit_code'] = run_collector(run, tools)
        (run/'exit-code.txt').write_text(str(report['exit_code'])+'\n')
        report['status'] = 'collector_returned' if report['exit_code'] == 0 else 'collector_incomplete'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = str(exc)
        raise
    finally:
        if 'exit_code' not in report:
            report['exit_code'] = 125
            (run/'exit-code.txt').write_text('125\n')
        report['before_cleanup'] = snapshot()
        # The collector owns global. Do not stop a replaced or active recorder.
        if changed_hold:
            try:
                edge_state = edge['state'](edge['Kernel']().read('scan'))
                submit_state = submit['state'](submit['read']('scan'))
                report['cleanup_recorders'] = {'edge': edge_state, 'submit': submit_state}
                # Each collector may arm at most once. A replacement generation
                # cannot be ours, even when that replacement is already frozen.
                generations_owned = all(current['generation'] in
                    (recorders_before[name]['generation'],
                     (recorders_before[name]['generation'] + 1) & 0xffffffff)
                    for name, current in report['cleanup_recorders'].items())
                if (read(VIDEO/'video_global_output') == '1' and read(hold) == '3' and
                    generations_owned and edge_state['status'] not in (1, 2, 6) and submit_state['status'] != 1):
                    hold.write_text('0\n'); report['hold_restored_by_wrapper'] = read(hold) == '0'
                else:
                    report['hold_cleanup_blocked'] = 'Global/hold/recorder state changed; preserve for audit'
            except Exception as exc: report['hold_cleanup_error'] = str(exc)
        for sig, prior in old_signals.items(): signal.signal(sig, prior)
        for lock in reversed(locks): lock.close()
        report['final_snapshot'] = snapshot()
        save_dmesg(run, 'dmesg-after.txt')
        (run/'decoder-after.txt').write_text(str(report['final_snapshot']['decoder'])+'\n')
        atomic_new(run/'pulse.json', report)
    return report['exit_code']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prepare', 'baseline', 'pulse', 'final'))
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--tools', type=Path, help='Absolute matching deployed tools directory')
    p.add_argument('--tools-commit', help='Exact deployed tool source commit, required for prepare')
    a = p.parse_args()
    old_signals = {}
    try:
        if a.stage in ('baseline', 'pulse'):
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                old_signals[sig] = signal.signal(sig, interrupted)
        if a.stage == 'prepare':
            if not a.tools or not a.tools_commit: p.error('--tools and --tools-commit required')
            prepare(a.run, a.tools, a.tools_commit)
        elif a.stage == 'baseline': baseline(a.run)
        elif a.stage == 'pulse':
            raise SystemExit(pulse(a.run))
        else:
            require_run(a.run, 'final')
            atomic_new(a.run/'final.json', snapshot())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        for sig, prior in old_signals.items(): signal.signal(sig, prior)


if __name__ == '__main__': main()
