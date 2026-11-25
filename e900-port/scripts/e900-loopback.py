#!/usr/bin/env python3
"""Existing VDIN session only: fresh image pairs, no playback/start/clock recovery."""
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
INSPECT = runpy.run_path(str(HERE / 'inspect-vdin-snapshot.py'))
PALETTE = [(255,255,255),(255,255,0),(0,255,255),(0,255,0),
           (255,0,255),(255,0,0),(0,0,255),(0,0,0)]


def colorbar_reference(rgb, width, height):
    # Known benchmark only. This row avoids its moving white marker.
    y = height // 4
    points = [tuple(rgb[(y*width + width*(2*i+1)//16)*3:][:3]) for i in range(8)]
    return all(max(abs(a-b) for a,b in zip(actual, expected)) <= 32
               for actual,expected in zip(points, PALETTE))


class Loopback:
    def __init__(self, output, runner=subprocess.run, sleep=time.sleep, decoder=None, gui=None):
        self.output = Path(output); self.output.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.output).free < 64*1024*1024:
            raise RuntimeError('Need 64MiB free for image evidence')
        self.runner = runner; self.sleep = sleep
        self.decoder = decoder or (lambda: Path('/sys/class/vdec/vdec_status').read_text())
        self.gui = gui or runpy.run_path(str(HERE / 'e900-debug.py'))['kodi_state']
        self.nonce = str(time.time_ns())
        self.previous_completion = self.previous_timestamp = None

    def __call__(self, label):
        report = dict(phase=label, point='legacy_ENCP_loopback', frames=[],
                      clock_recovery=False, physical_hdmi_observed=False,
                      decoding='BT601_limited_YUV444_reverse64; requires current-session route calibration')
        try:
            for i in range(2):
                if 'ammvdec_h264' not in self.decoder():
                    raise RuntimeError('Known decoder inactive; no current video image evidence')
                gui_before = self.gui()
                name = 'REG_' + self.nonce + '_' + label + '_' + str(i)
                env = dict(os.environ, E900_CAPTURE_NO_GATE='1', E900_CAPTURE_SKIP_SYNC='1')
                r = self.runner(['sh', str(HERE/'e900-capture-ready.sh'), name],
                                env=env, capture_output=True, text=True, timeout=15, check=True)
                source = Path(r.stdout.strip().splitlines()[-1])
                data = source.read_bytes(); meta,pixels = INSPECT['inspect'](data)
                if meta['format_convert'] != 2:
                    raise ValueError('Uncalibrated loopback format')
                for key,previous in [('completion_count',self.previous_completion),
                                     ('frame_timestamp',self.previous_timestamp)]:
                    if previous is not None and meta[key] <= previous:
                        raise ValueError('Stale/backwards loopback frame: '+key)
                self.previous_completion = meta['completion_count']
                self.previous_timestamp = meta['frame_timestamp']
                rgb = INSPECT['decode_yuv444_bt601'](pixels,meta['width'],True)
                target = self.output/(label+'_'+str(i))
                target.with_suffix('.e9cap').write_bytes(data)
                target.with_suffix('.png').write_bytes(INSPECT['png'](meta['width'],meta['height'],rgb,'RGB'))
                meta.update(packet=str(target.with_suffix('.e9cap')), png=str(target.with_suffix('.png')),
                            rgb_sha256=hashlib.sha256(rgb).hexdigest(),
                            rgb_min=min(rgb), rgb_max=max(rgb),
                            colorbar_reference=colorbar_reference(rgb,meta['width'],meta['height']),
                            gui_before=gui_before,gui_after=self.gui())
                report['frames'].append(meta)
                if 'ammvdec_h264' not in self.decoder():
                    raise RuntimeError('Decoder ended during capture')
                if i == 0:
                    self.sleep(1)
            if label == 'before':
                if not all(f['colorbar_reference'] for f in report['frames']):
                    raise ValueError('No known colorbar positive reference; do not mutate output')
                if report['frames'][0]['rgb_sha256'] == report['frames'][1]['rgb_sha256']:
                    raise ValueError('Positive images unchanged; moving benchmark freshness unproven')
            report['status'] = 'fresh_completed_pair'
        except Exception as error:
            report['status'] = 'failed'; report['error'] = str(error)
        return report
