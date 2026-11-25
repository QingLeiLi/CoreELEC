#!/usr/bin/env python3
"""Offline A1 evidence gate. UNKNOWN is never a valid A1 result."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
REGISTER = runpy.run_path(str(HERE / 'e900-register-transition.py'))
SUBMIT = runpy.run_path(str(HERE / 'e900-submit-trace.py'))


def check(data, manifest=None, image_dir=None):
    checks = {}
    details = {}
    def put(name, ok, detail):
        checks[name] = 'PASS' if ok is True else 'FAIL' if ok is False else 'UNKNOWN'
        details[name] = detail

    rows = data.get('records') or []
    state = data.get('state') or {}
    boot = data.get('boot_id')
    put('boot', None if manifest is None else bool(boot) and boot == manifest.get('boot_id'),
        {'transition': boot, 'manifest': None if manifest is None else manifest.get('boot_id')})
    try:
        parsed = REGISTER['decode_extensions'](data['extension_pages'],
                    REGISTER['EDGE']['decode'](data['pages'], state))
        put('raw_register_pages', parsed == rows, 'Parsed raw pages must equal exported records')
    except (KeyError, TypeError, ValueError) as error:
        put('raw_register_pages', False, str(error))
    put('mode_status', state.get('mode') == 2 and state.get('status') == 3 and
        state.get('reason') == 0 and state.get('guard') == 0 and
        state.get('off') == 1 and state.get('restored') == 1 and
        data.get('status') == 'collected_register_transition' and data.get('pixels') == 'not_collected',
        state)
    put('generation', bool(rows) and all(r.get('generation') == state.get('generation') for r in rows),
        {'state': state.get('generation'), 'rows': len(rows)})
    put('row_sequence', bool(rows) and len(rows) == state.get('count') and
        all(r.get('index') == i and r.get('phase') == i % 2 and r.get('tick') == i // 2 + 1
            for i, r in enumerate(rows)) and
        all(rows[i].get('stamp', -1) <= rows[i + 1].get('stamp', -1) for i in range(len(rows) - 1)),
        'Complete paired VSync rows with monotonic kernel timestamps')
    first_off = next((i for i, r in enumerate(rows) if r.get('global') == 0), None)
    restore = next((i for i, r in enumerate(rows) if first_off is not None and i > first_off and r.get('global') == 1), None)
    windows = [rows[:first_off], rows[first_off:restore], rows[restore:]] if first_off is not None and restore is not None else [[], [], []]
    put('global_windows', all(windows) and all(r.get('global') == v for w, v in zip(windows, (1, 0, 1)) for r in w),
        {'off': first_off, 'restore': restore, 'counts': [len(w) for w in windows]})
    put('guards_flags', bool(rows) and all(r.get('flags') == 1 and r.get('guard') == 0 for r in rows),
        {'bad_indices': [r.get('index') for r in rows if r.get('flags') != 1 or r.get('guard') != 0][:20]})
    sampled = [[r for r in w if r.get('phase') in (0, 1)] for w in windows]
    baseline = next((r.get('live') for r in sampled[0]), None)
    bad = [r.get('index') for w in sampled for r in w if r.get('live') != baseline or r.get('live', 0) & 0x4400 != 0x4400]
    put('actual_hold_bits_and_full_live', bool(baseline is not None and all(sampled)) and not bad,
        {'baseline': None if baseline is None else hex(baseline), 'bad_indices': bad[:30], 'phase_counts': [len(w) for w in sampled]})
    # enabled is restored inside blend processing, AFTER the first phase0
    # with global=1. A 0->1 prefix is expected, not a failed restoration.
    after_enabled = [r.get('enabled') for r in windows[2]]
    put('software_disabled', bool(windows[1]) and any(r.get('enabled') == 0 for r in windows[1]) and
        all(r.get('enabled') == 1 for r in windows[0]) and bool(after_enabled) and
        all(v in (0, 1) for v in after_enabled) and after_enabled[-1] == 1 and
        after_enabled == sorted(after_enabled),
        {'enabled_by_window': [sorted({r.get('enabled') for r in w}) for w in windows]})
    def delta(key):
        return (windows[1][-1].get(key, 0) - windows[0][0].get(key, 0)) if windows[0] and windows[1] else 0
    put('pps_csc_effect', delta('pps_calls') > 0 and (delta('csc_post') > 0 or delta('csc_fake') > 0),
        {k: delta(k) for k in ('pps_calls', 'csc_post', 'csc_fake')})
    sub = data.get('submissions') or {}
    ss = sub.get('state') or {}
    batches = sub.get('batches') or {}
    submit_rows = sub.get('records') or []
    try:
        sr, sb = SUBMIT['decode'](sub['pages'], ss)
        sb = {str(k): v for k, v in sb.items()}
        put('raw_submission_pages', sr == submit_rows and sb == batches,
            'Prepared tables and terminals must match raw pages')
    except (KeyError, TypeError, ValueError) as error:
        put('raw_submission_pages', False, str(error))
    terms = {str(b.get('terminal')) for b in batches.values()}
    put('submissions', ss.get('status') == 2 and ss.get('overflow') == 0 and
        ss.get('count', 0) > 0 and len(submit_rows) == ss.get('count') and bool(batches),
        {'state': ss, 'batch_count': len(batches), 'terminals': sorted(terms)})
    off_stamp = windows[1][0].get('stamp') if windows[1] else None
    put('submission_time_coverage', bool(submit_rows and rows and off_stamp is not None) and
        submit_rows[0].get('stamp', 2**64) <= off_stamp and
        submit_rows[-1].get('stamp', -1) >= rows[-1].get('stamp', 2**64) and
        all(submit_rows[i].get('stamp', -1) <= submit_rows[i + 1].get('stamp', -1)
            for i in range(len(submit_rows) - 1)), 'Submissions span before off through final register sample')
    changed = [r for r in submit_rows if r.get('kind') == 1 and windows[1] and windows[2] and
               windows[1][0]['stamp'] <= r.get('stamp', -1) <= windows[2][0]['stamp']]
    put('pps_hdr_submitted_during_off', any(r.get('reg') == 0x1d04 for r in changed) and
        any(0x3800 <= r.get('reg', 0) <= 0x38ff for r in changed),
        'Counter increments alone do not establish PPS/HDR table submission')
    pending = [k for k, b in batches.items() if b.get('terminal') == 'pending']
    last_batch = str(submit_rows[-1].get('batch')) if submit_rows else None
    put('submission_terminals', None if 'canceled' in terms else
        all(t in ('irq_observed', 'pending') for t in terms) and
        (not pending or pending == [last_batch]),
        {'terminals': sorted(terms), 'pending_batches': pending, 'note': 'Canceled batches require manual causal review'})
    after_phase0 = [r for r in windows[2] if r.get('phase') == 0]
    put('restored_16_vsync', len(after_phase0) >= 16, {'phase0_count': len(after_phase0)})
    def frames(label):
        obj = data.get('image_' + label) or {}
        return obj.get('frames') or [], obj.get('status')
    before, bs = frames('before')
    after, ats = frames('after')
    def fresh(a):
        return bool(a) and all(isinstance(f.get(k), int) and f[k] > 0
                              for f in a for k in ('completion_count', 'frame_timestamp')) and all(
                   a[i]['completion_count'] < a[i + 1]['completion_count'] and
                   a[i]['frame_timestamp'] < a[i + 1]['frame_timestamp'] for i in range(len(a) - 1))
    put('before_images', bs == 'fresh_completed_pair' and len(before) == 2 and fresh(before) and
        all(f.get('colorbar_reference') for f in before) and before[0].get('rgb_sha256') != before[1].get('rgb_sha256'),
        {'status': bs, 'frames': len(before)})
    put('after_images', ats == 'fresh_completed_pair' and len(after) == 2 and fresh(after) and
        (not before or (after[0].get('completion_count', 0) > before[-1].get('completion_count', 0) and
         after[0].get('frame_timestamp', 0) > before[-1].get('frame_timestamp', 0))),
        {'status': ats, 'frames': len(after)})
    moving_bars = len(after) == 2 and all(f.get('colorbar_reference') for f in after) and after[0].get('rgb_sha256') != after[1].get('rgb_sha256')
    black_pair = len(after) == 2 and all(f.get('rgb_min') == 0 and f.get('rgb_max') == 0 for f in after)
    put('after_pixel_classification', True if moving_bars or black_pair else None,
        'moving_colorbars' if moving_bars else 'black_pair' if black_pair else
        'Unclassified/stationary output; packet freshness alone does not establish moving video')
    if image_dir is None:
        put('image_files', None, 'Supply --image-dir to verify original packet contents and PNGs')
    else:
        inspector = runpy.run_path(str(HERE / 'inspect-vdin-snapshot.py'))
        palette = runpy.run_path(str(HERE / 'e900-loopback.py'))['colorbar_reference']
        try:
            if not before or not after:
                raise ValueError('Missing before/after frames')
            for f in before + after:
                packet = (Path(image_dir) / Path(f['packet']).name).read_bytes()
                meta, pixels = inspector['inspect'](packet)
                for k in ('completion_count', 'frame_timestamp', 'packet_sha256', 'format_convert', 'width', 'height'):
                    if meta[k] != f[k]:
                        raise ValueError('Packet metadata mismatch: ' + k)
                if meta['format_convert'] != 2:
                    raise ValueError('Uncalibrated format')
                rgb = inspector['decode_yuv444_bt601'](pixels, meta['width'], True)
                if (hashlib.sha256(rgb).hexdigest() != f['rgb_sha256'] or
                    min(rgb) != f['rgb_min'] or max(rgb) != f['rgb_max'] or
                    palette(rgb, meta['width'], meta['height']) != f['colorbar_reference']):
                    raise ValueError('Image interpretation/hash mismatch')
                png = inspector['png'](meta['width'], meta['height'], rgb, 'RGB')
                if (Path(image_dir) / Path(f['png']).name).read_bytes() != png:
                    raise ValueError('PNG differs from original packet rendering')
            put('image_files', True, 'Available raw packets, interpreted pixels and PNGs match; pair completeness checked separately')
        except (OSError, KeyError, TypeError, ValueError) as error:
            put('image_files', False, str(error))
    put('environment_and_cleanup', None, 'Verify run manifest, no Stop/replay/mode change/VDIN restart/clock gate, and collector inactive')
    # Mechanical checks are a gate, never a substitute for the assigned audit.
    return {'verdict': 'REJECTED' if 'FAIL' in checks.values() else 'REVIEW_REQUIRED',
            'scope': 'Gate for COMPLETE A1 evidence only. Preserve partial evidence for the assigned human/agent audit; never discard a run on this verdict.',
            'checks': checks, 'details': details,
            'limitation': 'VSync samples cannot rule out changes between samples; software IRQ does not prove each hardware write.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('transition', type=Path)
    p.add_argument('--manifest', type=Path)
    p.add_argument('--image-dir', type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    result = check(json.loads(a.transition.read_text()), json.loads(a.manifest.read_text()) if a.manifest else None,
                   a.image_dir)
    output = json.dumps(result, indent=2) + '\n'
    if a.out:
        a.out.write_text(output)
    print(output, end='')
    raise SystemExit(1 if result['verdict'] == 'REJECTED' else 2)


if __name__ == '__main__':
    main()
