#!/usr/bin/env python3
"""Register-only transition capture. Does not play video or touch pixel selectors."""
import argparse
import fcntl
import json
from pathlib import Path
import runpy
import time

HERE = Path(__file__).resolve().parent
EDGE = runpy.run_path(str(HERE / 'e900-transition.py'))
REG_FIELDS = ('canvas gen2 luma_x luma_y chroma_x chroma_y fmt_width fmt_height '
              'sc_misc line_in pic_in h_phase v_phase h_ctrl v_ctrl out_size').split()
META = ['index', 'generation', 'stamp', 'tick', 'phase', 'flags']


def decode_extensions(pages, rows):
    result = []
    for page in pages:
        for line in page.splitlines():
            words = line.split()
            if not words:
                continue
            if len(words) != len(META) + len(REG_FIELDS):
                raise ValueError('Unexpected register-extension width')
            values = [int(v, 10 if i < 2 else 16) for i, v in enumerate(words)]
            if any(v < 0 or v > (0xffffffffffffffff if i == 2 else 0xffffffff)
                   for i, v in enumerate(values)):
                raise ValueError('Out-of-range extension value')
            if len(result) >= len(rows):
                raise ValueError('Extra extension row')
            row = rows[len(result)]
            if values[:6] != [row[k] for k in META] or row['flags'] not in (0, 1):
                raise ValueError('Replaced/misaligned register extension')
            result.append(dict(zip(REG_FIELDS, values[6:])))
    if len(result) != len(rows):
        raise ValueError('Missing register extension')
    return [dict(row, registers=ext) for row, ext in zip(rows, result)]


def export(io):
    before = EDGE['state'](io.read('scan'))
    if before.get('mode') != 2 or before['status'] not in (3, 4, 5):
        raise ValueError('Need a frozen register-only generation')
    pages, extensions = [], []
    for page in range((before['count'] + 7) // 8):
        io.write('page', page)
        pages.append(io.read('data'))
        extensions.append(io.read('regs'))
    after = EDGE['state'](io.read('scan'))
    if before != after:
        raise ValueError('Register trace changed during export')
    rows = decode_extensions(extensions, EDGE['decode'](pages, before))
    return dict(state=before, pages=pages, extension_pages=extensions, records=rows)


def summary(rows):
    off = next((r['index'] for r in rows if not r['global']), None)
    restored = next((r['index'] for r in rows if off is not None and r['index'] > off and r['global']), None)
    windows = dict(before=[], during=[], after=[])
    for r in rows:
        if r['flags'] != 1 or r['phase'] != 0:
            continue
        if off is not None and r['index'] < off:
            windows['before'].append(r)
        elif not r['global']:
            windows['during'].append(r)
        elif restored is not None and r['index'] >= restored:
            windows['after'].append(r)
    fields = ('gen gen3 fmt fifo vpp_fifo live wanted shadow route0 route1 gate0 gate1 '
              'sc_gate xvy_gate dummy clip0 clip1 pps_calls sr_support sr_refresh '
              'csc_status csc_flags csc_null csc_on csc_wait csc_branch csc_post csc_fake').split() + REG_FIELDS
    def get(row, key):
        return row['registers'][key] if key in REG_FIELDS else row[key]
    values = {name: {k: sorted({get(r, k) for r in subset[-4:]}) for k in fields}
              for name, subset in windows.items()}
    differences = {k: {'before': values['before'][k], 'after': values['after'][k]}
                   for k in fields if values['before'][k] != values['after'][k]}
    return dict(first_off=off, first_restore=restored,
                row_indices={name: [r['index'] for r in subset] for name, subset in windows.items()},
                last_four_values=values, restored_window_differences=differences,
                note='Differences include dynamic status/counters, not causal verdicts. '
                     'VD1 GEN bit17 is source-named BUSY; configuration equality is not pixel validation.')


def collect(io, exercise=False, baseline_confirmed=False, submit=None,
            timeout=15, off_seconds=1, clock=time.monotonic, sleep=time.sleep, image_capture=None):
    result = dict(schema=1, mode='register_only', status='failed', pixels='not_collected',
                  requested_off_seconds=off_seconds,
                  baseline_confirmation_provided=baseline_confirmed,
                  physical_screen_observed=False, mutations=[], error=None)
    generation = submit_generation = None
    owned = False
    original = None
    changed_global = False
    try:
        if exercise and not baseline_confirmed and image_capture is None:
            raise ValueError('Explicit operator baseline confirmation required before output mutation')
        if not 0 < off_seconds <= 2:
            raise ValueError('Off interval must be in (0, 2] seconds')
        initial = EDGE['state'](io.read('scan'))
        if initial['status'] in (1, 2, 6):
            raise RuntimeError('Another edge session or deferred restore is active')
        if exercise:
            original = io.global_read()
            if original != '1':
                raise RuntimeError('Expected global output1')
        if image_capture is not None:
            result['image_before'] = image_capture('before')
            if result['image_before']['status'] != 'fresh_completed_pair':
                raise RuntimeError('No calibrated fresh output image reference; no output toggle')
        if submit is not None:
            s = submit['state'](submit['read']('scan'))
            if s['status'] == 1:
                raise RuntimeError('Another submit trace is active')
            expected = (s['generation'] + 1) & 0xffffffff
            submit['write']('scan', 1)
            s = submit['state'](submit['read']('scan'))
            if s['generation'] != expected or s['status'] != 1:
                raise RuntimeError('Submit trace was replaced during arm')
            submit_generation = expected
        generation = (initial['generation'] + 1) & 0xffffffff
        io.write('scan', 2)
        owned = True

        def wait(predicate, seconds):
            deadline = clock() + seconds
            while clock() < deadline:
                s = EDGE['state'](io.read('scan'))
                if s['generation'] != generation or s.get('mode') != 2:
                    raise RuntimeError('Register generation/mode replaced')
                if predicate(s):
                    return s
                if s['status'] in (3, 4, 5, 6):
                    raise RuntimeError('Register trace ended before requested boundary: ' + str(s))
                sleep(.02)
            raise TimeoutError('Register trace timeout')

        if exercise:
            # Register guards establish safe sampling, NOT that pixels are valid.
            wait(lambda s: s['count'] >= 8, timeout)
            changed_global = True; io.global_write(0)
            result['mutations'].append(dict(global_output=0, time=clock()))
            wait(lambda s: s['off'] == 1, 2)
            sleep(off_seconds)
            io.global_write(1); changed_global = False
            result['mutations'].append(dict(global_output=1, time=clock()))
        final = wait(lambda s: s['status'] in (3, 4, 5, 6), timeout)
        if final['status'] != 3:
            raise RuntimeError('Unsafe/incomplete register capture: ' + str(final))
        result.update(export(io))
        result['summary'] = summary(result['records'])
        if exercise and (final['reason'] != 0 or not all(result['summary']['row_indices'].values())):
            raise RuntimeError('Incomplete before/during/after evidence')
        result['status'] = 'collected_register_transition' if final['off'] else 'collected_without_transition'
    except Exception as error:
        result['error'] = str(error)
    finally:
        if changed_global:
            try:
                io.global_write(original); result['global_restored'] = True
            except Exception as error:
                result['global_restore_error'] = str(error)
        if owned and generation is not None:
            try:
                s = EDGE['state'](io.read('scan'))
                if s['generation'] == generation and s['status'] in (1, 2):
                    io.write('scan', 0)
                    deadline = clock() + 2
                    while clock() < deadline:
                        s = EDGE['state'](io.read('scan'))
                        if s['generation'] != generation or s['status'] not in (1, 2):
                            break
                        sleep(.02)
                if s['generation'] == generation:
                    result['cleanup_state'] = s
                    if 'records' not in result and s['status'] in (3, 4, 5) and s['count']:
                        result['partial_trace'] = export(io)
            except Exception as error:
                result['cleanup_error'] = str(error)
        if submit_generation is not None:
            try:
                s = submit['state'](submit['read']('scan'))
                if s['generation'] != submit_generation:
                    raise RuntimeError('Submit generation replaced; not stopping foreign session')
                if s['status'] == 1:
                    submit['write']('scan', 0)
                result['submissions'] = submit['export']()
            except Exception as error:
                result['submission_error'] = str(error)
    if image_capture is not None and result['status'].startswith('collected_'):
        try:
            result['image_after'] = image_capture('after')
        except Exception as error:
            result['image_after'] = dict(status='failed', error=str(error))
    result['image_evidence_complete'] = all(result.get(k, {}).get('status') == 'fresh_completed_pair'
                                            for k in ('image_before', 'image_after'))
    result['baseline_source'] = ('fresh_calibrated_loopback' if result.get('image_before', {}).get('status') == 'fresh_completed_pair'
                                 else 'operator_confirmation' if baseline_confirmed else 'not_provided')
    result['submission_evidence_complete'] = ('submissions' in result and
        result['submissions']['status'] == 'collected_software_tables')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--exercise-global-output', action='store_true')
    parser.add_argument('--off-seconds', type=float, default=1,
                        help='Output-off hold in (0, 2] seconds; shorten to fit submission buffer')
    parser.add_argument('--baseline-confirmed', action='store_true', help='Only after an actual operator reply confirming the current picture')
    parser.add_argument('--with-submissions', action='store_true')
    parser.add_argument('--with-loopback', action='store_true', help='Use an already running calibrated VDIN session; never starts it or recovers clocks')
    parser.add_argument('--loopback-calibrated', action='store_true', help='Current route/byte order has been calibrated; each run still requires fresh moving colorbar images')
    a = parser.parse_args()
    if not 0 < a.off_seconds <= 2:
        parser.error('--off-seconds must be in (0, 2]')
    if a.with_loopback and a.exercise_global_output and not a.loopback_calibrated:
        parser.error('Calibrate the current running loopback session before using it as image evidence')
    if a.exercise_global_output:
        if not a.baseline_confirmed and not a.with_loopback:
            parser.error('Wait for the user to confirm the picture before this operation')
        if 'ammvdec_h264' not in Path('/sys/class/vdec/vdec_status').read_text():
            parser.error('Known H264 video is not active; no playback is started here')
        if Path('/sys/class/video/disable_video').read_text().strip() != '0':
            parser.error('Real layer disable is active')
        knob = EDGE['Kernel'].root / 'gxlx2_gen3_clear_high'
        if knob.exists() and knob.read_text().strip() != 'N':
            parser.error('Restore GEN3 experiment to default first')
    submit = runpy.run_path(str(HERE / 'e900-submit-trace.py')) if a.with_submissions else None
    image_capture = (runpy.run_path(str(HERE / 'e900-loopback.py'))['Loopback'](
        a.out.parent / (a.out.stem + '-images')) if a.with_loopback else None)
    locks = []
    try:
        for name in ('e900-edge', 'e900-pixel-probe', 'e900-submit', 'e900-loopback'):
            lock = open('/run/' + name + '.lock', 'w'); locks.append(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = collect(EDGE['Kernel'](), a.exercise_global_output, a.baseline_confirmed, submit,
                         off_seconds=a.off_seconds, image_capture=image_capture)
        result['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        result['loopback_calibration_claimed'] = a.loopback_calibrated
        result['policy_after'] = {name: (EDGE['Kernel'].root / name).read_text().strip()
                                  for name in ('gxlx2_blend_hold', 'gxlx2_gen3_clear_high')}
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: result.get(k) for k in ('status', 'error', 'submission_evidence_complete', 'image_evidence_complete')}, indent=2))
        if a.with_loopback and not result['image_evidence_complete']:
            raise SystemExit(2)
        if a.with_submissions and not result['submission_evidence_complete']:
            raise SystemExit(2)
        raise SystemExit(0 if result['status'].startswith('collected_') else 1)
    finally:
        for lock in reversed(locks):
            lock.close()


if __name__ == '__main__':
    main()
