#!/usr/bin/env python3
"""Bounded E900 evidence collection. Never changes display/decoder policy.

arm -> snapshot --label normal [--pixels] -> snapshot --label abnormal
-> disarm -> compare NORMAL_DIR ABNORMAL_DIR. Python standard library only.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import shutil
import struct
import subprocess
import time
import zlib

# Pinned public enum AMVIDEOCAP_STATE_FINISHED_CAPTURE (decimal).
CAPTURE_FINISHED = 300
ROOT = Path('/')
CHANNELS = ('amvideo', 'di', 'vpu', 'rdma', 'rdma_mgr', 'register_ops', 'fb', 'am_vecm')
PARAMS = {
    'am_vecm': ('gxlx2_debug_events',),
    'amvideo': ('gxlx2_debug_events', 'gxlx2_stage_samples', 'gxlx2_hw_init_status',
                'gxlx2_hw_init_step', 'gxlx2_hw_init_wait', 'gxlx2_g12_mif',
                'gxlx2_gen3_clear_high', 'gxlx2_gen3_clear_high_submits', 'gxlx2_pixel_scan'),
    'rdma': ('enable', 'irq_count', 'vsync_cfg_count', 'force_rdma_config',
             'gxlx2_debug_state', 'gxlx2_debug_events', 'gxlx2_gen3_rmw_events',
             'gxlx2_stall_frames', 'gxlx2_stall_rearms'),
    'di': ('bypass_all', 'bypass_post', 'bypass_post_state', 'gxlx2_debug_events'),
    'vpu': ('gxlx2_debug_events',),
    'rdma_mgr': ('gxlx2_debug_events', 'gxlx2_debug_state', 'gxlx2_gen3_rmw_events'),
    'fb': ('gxlx2_osd_blender_only', 'gxlx2_debug_events', 'osd_vpp_misc'),
    'register_ops': ('gxlx2_debug_events', 'gxlx2_gen3_rmw_events'),
}
# These getters have been inspected; do not enumerate arbitrary sysfs attributes.
READS = {
    'boot_id': '/proc/sys/kernel/random/boot_id', 'cmdline': '/proc/cmdline',
    'version': '/proc/version', 'uptime': '/proc/uptime',
    'interrupts': '/proc/interrupts', 'memory': '/proc/meminfo',
    'vfm': '/sys/class/vfm/map', 'decoder': '/sys/class/vdec/vdec_status',
    'video_state': '/sys/class/video/video_state',
    'display_mode': '/sys/class/display/mode',
}


def path(name):
    return ROOT / name.lstrip('/')


def read(name):
    try:
        return {'status': 'ok', 'text': path(name).read_text(errors='replace')}
    except OSError as e:
        return {'status': 'unavailable', 'error': str(e)}


def knob(module, name, value):
    p = path('/sys/module/%s/parameters/%s' % (module, name))
    try:
        p.write_text(str(value) + '\n')
        return {'status': 'ok'}
    except OSError as e:
        return {'status': 'unavailable', 'error': str(e)}


def arm(budget):
    if not 0 <= budget <= 512:
        raise ValueError('Event budget must be 0..512')
    marker('ARM budget=%d' % budget)
    result = {m: knob(m, 'gxlx2_debug_events', budget) for m in CHANNELS}
    result['gen3_rmw'] = {m: knob(m, 'gxlx2_gen3_rmw_events', budget)
                          for m in ('rdma', 'rdma_mgr', 'register_ops', 'fb')}
    return result


def marker(text):
    try:
        path('/dev/kmsg').write_text('<6>E900_DEBUG ' + text + '\n')
        return True
    except OSError:
        return False


def kodi_state():
    calls = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'Player.GetActivePlayers'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'Player.GetProperties',
         'params': {'playerid': 1, 'properties': ['speed', 'time', 'percentage']}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'GUI.GetProperties',
         'params': {'properties': ['currentwindow', 'currentcontrol', 'fullscreen']}},
    ]
    try:
        with socket.create_connection(('127.0.0.1', 9090), 2) as s:
            s.settimeout(2)
            s.sendall(json.dumps(calls).encode())
            buf = b''
            while len(buf) < 65536:
                chunk = s.recv(8192)
                if not chunk:
                    break
                buf += chunk
                try:
                    return {'status': 'ok', 'result': json.loads(buf)}
                except (ValueError, UnicodeError):
                    pass
            raise ValueError('Incomplete/oversize JSON-RPC reply')
    except (OSError, ValueError) as e:
        return {'status': 'unavailable', 'error': str(e)}


def png_bgr(data, width, height):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack(
            '>I', zlib.crc32(kind + payload) & 0xffffffff)
    rows = []
    for y in range(height):
        row = bytearray(data[y * width * 3:(y + 1) * width * 3])
        row[0::3], row[2::3] = row[2::3], row[0::3]
        rows.append(b'\0' + row)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack(
        '>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(
        b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


def canvas_capture(folder):
    """Normal synchronous amvideocap API: no mmap or raw memory access.

    Captures the currently selected display Canvas via GE2D, before VD1/VPP.
    This MUST NOT be described as a VD1-output or HDMI screenshot.
    """
    report = {'point': 'display_canvas_via_ge2d', 'width': 320, 'height': 180,
              'pixel_order': 'BGR24', 'downstream_pixel_evidence': False}
    dec = read(READS['decoder'])
    if dec['status'] != 'ok' or 'ammvdec_h264' not in dec['text']:
        return dict(report, status='skipped', error='No active H264 decoder')
    fd = None
    try:
        fd = os.open(str(path('/dev/amvideocap0')), os.O_RDONLY | os.O_NONBLOCK)
        for nr, value, size in [(2, 320, 4), (3, 180, 4), (5, 1500, 8), (6, 0, 4)]:
            fcntl.ioctl(fd, 0x40000000 | (size << 16) | (ord('V') << 8) | nr, value)
        start = time.monotonic()
        data = os.read(fd, 320 * 180 * 4)
        def get(nr):
            b = bytearray(8)
            fcntl.ioctl(fd, 0x80000000 | (4 << 16) | (ord('V') << 8) | nr, b, True)
            return int.from_bytes(b[:4], 'little')
        report.update(actual_width=get(0x11), actual_height=get(0x12), state=get(0x31),
                      source_width=get(0x21), source_height=get(0x22),
                      timestamp_ms_low32=get(0x13), format=get(0x10),
                      bytes=len(data), seconds=time.monotonic() - start)
        if (report['actual_width'], report['actual_height'], len(data)) != (320, 180, 172800):
            raise ValueError('Incomplete or unexpected capture layout')
        if report['state'] != CAPTURE_FINISHED:
            raise ValueError('Synchronous completed-capture state is not decimal300')
        (folder / 'canvas.bgr').write_bytes(data)
        (folder / 'canvas.png').write_bytes(png_bgr(data, 320, 180))
        report.update(status='ok', sha256=hashlib.sha256(data).hexdigest(),
                      statistics={'minimum': min(data), 'maximum': max(data),
                                  'mean_byte': sum(data) / len(data),
                                  'unique_byte_values': len(set(data))})
    except (OSError, ValueError) as e:
        report.update(status='failed', error=str(e))
    finally:
        if fd is not None:
            time.sleep(0.5)
            os.close(fd)
    return report


def parse_logs(text):
    rows = []
    for line in text.splitlines():
        for prefix in ('e900-stage ', 'e900-snapshot ', 'e900-debug ', 'e900-gen3 ', 'e900-capture '):
            if prefix in line:
                payload = line.split(prefix, 1)[1]
                fields = dict(re.findall(r'([A-Za-z0-9_]+)=([^\s]+)', payload))
                rows.append({'source': prefix.strip(), 'fields': fields, 'line': line})
                break
    return rows


def state():
    result = {k: read(v) for k, v in READS.items()}
    result['parameters'] = {
        m: {n: read('/sys/module/%s/parameters/%s' % (m, n)) for n in names}
        for m, names in PARAMS.items()}
    return result


def snapshot(args):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', args.label):
        raise ValueError('Label must be 1..48 letters/digits/underscore/hyphen')
    boot = read(READS['boot_id']).get('text', 'unknown').strip()
    folder = Path(args.output) / (boot + '-' + str(time.time_ns()) + '-' + args.label)
    folder.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder.parent).free < 8 * 1024 * 1024:
        raise OSError('Snapshot requires at least 8 MiB available space')
    folder.mkdir(exist_ok=False)
    report = {'schema': 1, 'label': args.label, 'utc': datetime.datetime.now(
        datetime.timezone.utc).isoformat(), 'monotonic_start': time.monotonic(),
        'interpretation': 'interval observations, not an atomic hardware/pixel snapshot',
        'before': state(), 'pixel_capture': {'status': 'not_requested'}}
    token = folder.name
    report['marker_written'] = marker('BEGIN ' + token)
    try:
        report['probe_arm'] = knob('amvideo', 'gxlx2_stage_samples', 4)
        time.sleep(0.25)
        knob('amvideo', 'gxlx2_stage_samples', 0)
        time.sleep(0.75)
        if args.pixels:
            report['pixel_capture'] = canvas_capture(folder)
        if getattr(args, 'pipeline_pixels', False):
            import runpy
            probe = Path(__file__).resolve().with_name('e900-pixel-probe.py')
            if probe.is_file():
                client = runpy.run_path(str(probe))
                result = client['collect']()
                if result.get('status') == 'collected_uncalibrated':
                    (folder / 'pipeline-pixels.svg').write_text(client['render_svg'](result))
                report['pipeline_pixels'] = result
                (folder / 'pipeline-pixels.json').write_text(json.dumps(result, indent=2) + '\n')
            else:
                report['pipeline_pixels'] = {'status':'unavailable', 'error':'Missing e900-pixel-probe.py'}
        report['after'] = state()
        report['kodi'] = kodi_state()
        marker('END ' + token)
        d = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=5)
        text = d.stdout
        report['dmesg_status'] = d.returncode
        history = text.rsplit('E900_DEBUG ARM ', 1)
        report['lifecycle_since_arm'] = ([r for r in parse_logs(history[1])
            if r['source'] in ('e900-debug', 'e900-gen3')] if len(history) == 2 else [])
        (folder / 'dmesg.txt').write_text(text)
        begin, end = 'E900_DEBUG BEGIN ' + token, 'E900_DEBUG END ' + token
        if begin in text and end in text:
            interval = text.split(begin, 1)[1].split(end, 1)[0]
            report['interval_status'] = 'bounded_by_markers'
            report['observations'] = parse_logs(interval)
        else:
            report['interval_status'] = 'markers_missing_no_current_stage_claim'
            report['observations'] = []
    except Exception as e:
        report['collection_error'] = '%s: %s' % (type(e).__name__, e)
    finally:
        knob('amvideo', 'gxlx2_stage_samples', 0)
        report['monotonic_end'] = time.monotonic()
        pending = folder / 'snapshot.json.partial'
        pending.write_text(json.dumps(report, indent=2) + '\n')
        pending.rename(folder / 'snapshot.json')
    print(folder)


VOLATILE = {'idx', 'index', 'pts', 'seq', 'epoch', 'addr'}


def config_values(doc):
    result = {}
    for row in doc.get('observations', []):
        f = row['fields']
        # Lifecycle event a/b/c/d meanings differ, so group by event/channel.
        group = f.get('kind', f.get('event', 'stage'))
        group += ':' + f.get('channel', '')
        if 'plane' in f:
            group += ':plane' + f['plane']
        for key, value in f.items():
            if key not in VOLATILE:
                result.setdefault(group + '.' + key, set()).add(value)
    return {k: sorted(v) for k, v in result.items()}


def compare(left, right):
    a, b = [json.loads((Path(p) / 'snapshot.json').read_text()) for p in (left, right)]
    av, bv = config_values(a), config_values(b)
    keys = sorted(av.keys() | bv.keys())
    diffs = {k: {'left': av.get(k), 'right': bv.get(k)} for k in keys if av.get(k) != bv.get(k)}
    missing = [side for side, d in [('left', a), ('right', b)]
               if not d.get('observations')]
    pixels = {'left': a.get('pixel_capture', {'status': 'missing'}),
              'right': b.get('pixel_capture', {'status': 'missing'})}
    if all(pixels[x].get('status') == 'ok' for x in ('left', 'right')):
        pixels['same_hash'] = pixels['left']['sha256'] == pixels['right']['sha256']
        pixels['note'] = 'Moving content/timing can differ; equality/difference alone does not localize failure.'
    readback_diffs = {}
    aa, bb = a.get('after', {}), b.get('after', {})
    for key in ('video_state', 'display_mode', 'vfm'):
        if aa.get(key) != bb.get(key):
            readback_diffs[key] = {'left': aa.get(key), 'right': bb.get(key)}
    import runpy
    probe = Path(__file__).resolve().with_name('e900-pixel-probe.py')
    pipeline = {'status':'unavailable', 'error':'Missing probe collector'}
    if probe.is_file():
        pipeline = runpy.run_path(str(probe))['compare_scans'](a.get('pipeline_pixels', {}), b.get('pipeline_pixels', {}))
    return {'schema': 1, 'labels': [a['label'], b['label']],
            'same_boot': a['before']['boot_id'] == b['before']['boot_id'],
            'missing_interval_evidence': missing, 'configuration_differences': diffs,
            'pixel_comparison': pixels, 'pipeline_pixel_comparison': pipeline, 'software_readback_differences': readback_diffs,
            'parameters': {'left': a.get('after', {}).get('parameters', {}), 'right': b.get('after', {}).get('parameters', {})},
            'conclusion': 'Differences are candidates; no automatic root-cause verdict. Intermediate sparse taps require per-port hardware/scene calibration.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('arm'); a.add_argument('--budget', type=int, default=128)
    sub.add_parser('disarm')
    s = sub.add_parser('snapshot'); s.add_argument('--label', required=True)
    s.add_argument('--output', default='/storage/e900-debug'); s.add_argument('--pixels', action='store_true')
    s.add_argument('--pipeline-pixels', action='store_true', help='Opt-in fixed legacy intermediate sparse pixel scan; calibration required')
    c = sub.add_parser('compare'); c.add_argument('normal'); c.add_argument('abnormal')
    args = p.parse_args()
    if args.command == 'compare':
        print(json.dumps(compare(args.normal, args.abnormal), indent=2))
    elif args.command == 'snapshot':
        snapshot(args)
    else:
        if args.command == 'disarm':
            knob('amvideo', 'gxlx2_stage_samples', 0)
        print(json.dumps(arm(args.budget if args.command == 'arm' else 0), indent=2))


if __name__ == '__main__':
    main()
