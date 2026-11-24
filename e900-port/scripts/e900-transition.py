#!/usr/bin/env python3
"""Capture one fixed-point blend transition; default observes, never plays video.

--exercise-global-output explicitly requests one1->0->1 transition during an
already active H264 test. A completed record is not proof of valid pixels.
"""
import argparse
import fcntl
import json
import time
from pathlib import Path

FIELDS = 'index generation stamp tick phase flags guard global enabled disable off epoch frame pts mem gen gen3 fmt fifo vpp_fifo live wanted shadow ctrl pos dummy clip0 clip1 route0 route1 gate0 gate1 sc_gate xvy_gate raw0 raw1 irq configured force done'.split()


def state(text):
    return {k: int(v, 16 if k == 'guard' else 10)
            for k, v in (word.split('=', 1) for word in text.split())}


def decode(pages, expected):
    rows = []
    for page in pages:
        for line in page.splitlines():
            values = line.split()
            if len(values) != len(FIELDS):
                raise ValueError('Unexpected transition record width')
            row = {k: int(v, 10 if i < 2 else 16)
                   for i, (k, v) in enumerate(zip(FIELDS, values))}
            if row['index'] != len(rows) or row['generation'] != expected['generation']:
                raise ValueError('Missing/duplicate/replaced transition record')
            if row['phase'] not in (0, 1) or row['flags'] & ~7:
                raise ValueError('Unknown phase/flags')
            row['registers_read'] = bool(row['flags'] & 1)
            row['pixel_read_coherent'] = row['flags'] == 7
            row['hardware_pixel_validity'] = 'unknown' if row['pixel_read_coherent'] else 'not_read'
            rows.append(row)
    if len(rows) != expected['count'] or not 0 < len(rows) <= 512:
        raise ValueError('Incomplete transition trace')
    return rows


class Kernel:
    root = Path('/sys/module/amvideo/parameters')

    def read(self, name):
        return (self.root / ('gxlx2_edge_' + name)).read_text()

    def write(self, name, value):
        (self.root / ('gxlx2_edge_' + name)).write_text(str(value) + '\n')

    def global_read(self):
        return Path('/sys/class/video/video_global_output').read_text().strip()

    def global_write(self, value):
        Path('/sys/class/video/video_global_output').write_text(str(value) + '\n')


def collect(io, exercise=False, timeout=15, clock=time.monotonic, sleep=time.sleep):
    result = {'schema': 1, 'status': 'failed', 'exercise': exercise,
              'physical_screen_observed': False, 'hardware_pixel_validity': 'unknown',
              'states': [], 'pages': [], 'mutations': []}
    owned = False
    generation = None
    changed_global = False
    original = None

    def get():
        s = state(io.read('scan'))
        result['states'].append(s)
        return s

    def wait_for(predicate, seconds):
        deadline = clock() + seconds
        while clock() < deadline:
            s = get()
            if s['generation'] != generation:
                raise RuntimeError('Trace replaced by another generation')
            if predicate(s):
                return s
            if s['status'] in (3, 4, 5, 6):
                raise RuntimeError('Trace ended before the requested boundary: ' + str(s))
            sleep(0.02)
        raise TimeoutError('Trace boundary timeout')

    try:
        before = get()
        if before['status'] in (1, 2, 6):
            raise RuntimeError('Another transition or deferred restore is pending')
        if exercise:
            original = io.global_read()
            if original != '1':
                raise RuntimeError('Expected global output1 before exercise')
        generation = (before['generation'] + 1) & 0xffffffff
        io.write('scan', 1)
        owned = True
        if exercise:
            s = wait_for(lambda s: s['count'] >= 12, timeout)
            # Read only the stable prefix while running; page0 is immutable once
            # filled. Require settled/coherent nonzero reference before toggling.
            io.write('page', 0)
            prefix = decode([io.read('data')], dict(s, count=8))
            reference = [r for r in prefix if r['pixel_read_coherent']]
            if not reference or not any((r['raw0'], r['raw1']) != (0, 0) for r in reference):
                raise RuntimeError('No nonzero settled reference; no toggle performed')
            io.global_write(0)
            changed_global = True
            result['mutations'].append({'global_output': 0, 'time': clock()})
            wait_for(lambda s: s['off'] == 1, 2)
            sleep(0.2)
            io.global_write(1)
            changed_global = False
            result['mutations'].append({'global_output': 1, 'time': clock()})
        final = wait_for(lambda s: s['status'] in (3, 4, 5, 6), timeout)
        result['final'] = final
        if final['status'] != 3 or final['reason'] != 0 or final['off'] != 1 or final['restored'] != 1:
            raise RuntimeError('No complete, restored blend transition: ' + str(final))
        for page in range((final['count'] + 7) // 8):
            io.write('page', page)
            result['pages'].append(io.read('data'))
        after = get()
        if any(after[k] != final[k] for k in ('generation', 'status', 'count', 'restored')):
            raise RuntimeError('Trace changed during export')
        result['records'] = decode(result['pages'], final)
        rows = result['records']
        first_off = next((r['index'] for r in rows if r['global'] == 0), None)
        restoring = next((r['index'] for r in rows if first_off is not None and
                          r['index'] > first_off and r['global'] == 1), None)
        result['boundaries'] = {
            'first_off': first_off, 'first_restore': restoring,
            'before': [r['index'] for r in rows if first_off is not None and r['index'] < first_off],
            'during': [r['index'] for r in rows if r['global'] == 0],
            'after': [r['index'] for r in rows if restoring is not None and r['index'] >= restoring]}
        result['status'] = 'collected_not_pixel_validated'
    except Exception as error:
        result['error'] = str(error)
    finally:
        if changed_global:
            try:
                io.global_write(original)
                result['global_restored'] = True
            except Exception as error:
                result['global_restore_error'] = str(error)
        if owned:
            try:
                s = get()
                if s['generation'] == generation and s['status'] in (1, 2):
                    io.write('scan', 0)
                    deadline = clock() + 2
                    while clock() < deadline:
                        s = get()
                        if s['generation'] != generation or s['status'] not in (1, 2):
                            break
                        sleep(0.02)
                result['cleanup_state'] = s
                if s['generation'] == generation and s['status'] == 6:
                    result['restore_pending'] = True
            except Exception as error:
                result['cleanup_error'] = str(error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--exercise-global-output', action='store_true')
    a = parser.parse_args()
    if a.exercise_global_output:
        if 'ammvdec_h264' not in Path('/sys/class/vdec/vdec_status').read_text():
            parser.error('Start the known H264 test first; no video will be opened here')
        for name, expected in [('gxlx2_blend_hold', '0'), ('gxlx2_gen3_clear_high', 'N')]:
            path = Kernel.root / name
            if path.exists() and path.read_text().strip() != expected:
                parser.error('Restore default ' + name + ' first')
        if Path('/sys/class/video/disable_video').read_text().strip() != '0':
            parser.error('Real layer disable is active')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open('/run/e900-edge.lock', 'w') as lock, open('/run/e900-pixel-probe.lock', 'w') as pixel_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(pixel_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = collect(Kernel(), a.exercise_global_output)
        a.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result.get(k) for k in ('status', 'error', 'final', 'restore_pending')}, indent=2))
    raise SystemExit(0 if result['status'] == 'collected_not_pixel_validated' else 1)


if __name__ == '__main__':
    main()
