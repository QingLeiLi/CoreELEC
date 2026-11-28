#!/usr/bin/env python3
"""Build294-only boot compensation for the verified missing OSD CH3 trigger.

Run before Kodi, after graphics/device setup. No arbitrary register interface,
shared reset, CTRL write, video playback or persistent bootloader modification.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

BUILD = '21.3-Omega_devel_20261128084424'
BOARD = 'gxlx2_p291_1g_e900v21c'
MASK = 0xff000088
WANT = 0x01000080


class Device:
    def text(self, path):
        return Path(path).read_text().strip()

    def irq(self):
        return int(self.text('/sys/module/fb/parameters/rdma_irq_count'))

    def sleep(self, seconds):
        time.sleep(seconds)

    def read_reg(self, reg):
        if reg not in ('1106', '1107', '1110'):
            raise ValueError('Unapproved register')
        pattern = r'\[\s*([\d.]+)[^\]]*\].*fb: reg\[0x' + reg + r'\]: 0x([0-9a-fA-F]+)'
        before = re.findall(pattern, subprocess.check_output(['dmesg'], text=True))
        Path('/sys/class/graphics/fb0/debug').write_text('r ' + reg)
        after = re.findall(pattern, subprocess.check_output(['dmesg'], text=True))
        if not after or (before and after[-1] == before[-1]):
            raise RuntimeError('Missing fresh readback for ' + reg)
        return int(after[-1][1], 16)

    def write_auto(self, value):
        Path('/sys/class/graphics/fb0/debug').write_text('w 1110 ' + format(value, 'x'))


def recover(device, record, check=False):
    # A new image must opt in explicitly after a fresh register-map audit.
    version = device.text('/etc/os-release')
    if ('VERSION="' + BUILD + '"') not in version.splitlines():
        record['result'] = 'skipped-other-build'
        return
    if device.text('/proc/device-tree/coreelec-dt-id').rstrip('\0') != BOARD:
        raise RuntimeError('Wrong board')
    if '4.9.269' not in device.text('/proc/version'):
        raise RuntimeError('Wrong kernel')
    if 'amvideo.gxlx2_hw_init_wait=0' not in device.text('/proc/cmdline').split():
        record['result'] = 'skipped-diagnostic-wait'
        return
    if device.text('/sys/module/amvideo/parameters/gxlx2_hw_init_status') != '2':
        raise RuntimeError('Media buses/fixed initialization not ready')
    if device.text('/sys/class/vdec/vdec_status') != 'No vdec.':
        raise RuntimeError('Active decoder; refusing startup recovery')
    first = device.irq()
    device.sleep(0.12)
    second = device.irq()
    record['irq_before'] = [first, second]
    if second > first:
        record['result'] = 'already-completing'
        return
    if first or second:
        raise RuntimeError('Unexpected nonzero stalled OSD counter')

    old = device.read_reg('1110')
    start = device.read_reg('1106')
    end = device.read_reg('1107')
    record['before'] = dict(auto=hex(old), start=hex(start), end=hex(end))
    # Accept only the exact defect, with the same table page verified on this exact build.
    if old != 0x120:
        raise RuntimeError('Unexpected AUTO configuration')
    if not (start == 0x34e10000
            and start <= end < start + 4096 and (end - start + 1) % 8 == 0):
        raise RuntimeError('Invalid OSD DMA table range')
    if check:
        record['result'] = 'would-recover'
        return
    # Recheck live state immediately before the single controlled write.
    if device.read_reg('1110') != old or device.irq() != 0:
        raise RuntimeError('State changed before write')
    written = False
    success = False
    try:
        written = True
        device.write_auto((old & ~MASK) | WANT)
        samples = []
        for _ in range(2):
            device.sleep(0.2)
            samples.append(dict(irq=device.irq(), auto=hex(device.read_reg('1110'))))
        record['samples'] = samples
        success = (samples[0]['irq'] > 0 and samples[1]['irq'] > samples[0]['irq']
                   and all(int(s['auto'], 16) & MASK == WANT for s in samples))
        if not success:
            raise RuntimeError('OSD did not resume continuous completion')
        record['result'] = 'recovered'
    finally:
        if written and not success:
            # Restore only our CH3 fields; callbacks may legitimately update CH2.
            current = device.read_reg('1110')
            restore = (current & ~MASK) | (old & MASK)
            device.write_auto(restore)
            record['rollback'] = hex(device.read_reg('1110'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read only; do not recover')
    args = parser.parse_args()
    record = dict(boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  monotonic=time.monotonic(), check=args.check)
    folder = Path('/storage/e900-boot-speed/boot-rdma')
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / (record['boot'] + ('-check' if args.check else '') + '.json')
    output.write_text(json.dumps(dict(record, result='pending'), indent=2) + '\n')
    code = 0
    try:
        recover(Device(), record, args.check)
    except Exception as exc:
        record.update(result='refused-or-failed', error=str(exc))
        code = 1
    output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
