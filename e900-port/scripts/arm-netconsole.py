#!/usr/bin/env python3
"""On the box, arm netconsole in wait mode. Never release video init here."""
import argparse
import ipaddress
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receiver-ip', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--receiver-mac', required=True)
    parser.add_argument('--interface', default='eth0')
    parser.add_argument('--port', type=int, default=6666)
    args = parser.parse_args()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', args.receiver_mac):
        parser.error('Expected receiver Ethernet/Wi-Fi MAC address')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', args.interface) or not 1 <= args.port <= 65535:
        parser.error('Invalid interface or port')
    params = Path('/sys/module/amvideo/parameters')
    if (params / 'gxlx2_hw_init_wait').read_text().strip() != 'Y':
        raise SystemExit('Reboot with amvideo.gxlx2_hw_init_wait=1 first')
    if (params / 'gxlx2_hw_init_status').read_text().strip() != '1':
        raise SystemExit('Video register init is not pending')
    if Path('/sys/module/netconsole').exists():
        raise SystemExit('netconsole already loaded; inspect existing target before changing it')
    if (Path('/sys/class/net') / args.interface / 'carrier').read_text().strip() != '1':
        raise SystemExit('Wired interface has no carrier')
    route = subprocess.check_output(['ip', '-4', 'route', 'get', str(args.receiver_ip)], text=True)
    dev, src = re.search(r'\bdev\s+(\S+)', route), re.search(r'\bsrc\s+(\S+)', route)
    if not dev or not src or dev[1] != args.interface:
        raise SystemExit('Receiver route does not use the selected wired interface')
    local = str(ipaddress.IPv4Address(src[1]))
    target = f'6665@{local}/{args.interface},{args.port}@{args.receiver_ip}/{args.receiver_mac}'
    subprocess.run(['modprobe', 'netconsole', 'netconsole=' + target], check=True)
    # INFO traces require console_loglevel >= 7. This is runtime-only.
    levels = Path('/proc/sys/kernel/printk')
    values = levels.read_text().split()
    values[0] = str(max(7, int(values[0])))
    levels.write_text(' '.join(values) + '\n')
    with Path('/dev/kmsg').open('w') as kmsg:
        kmsg.write('<6>E900_NETCONSOLE_READY video_init_pending=1\n')
    print('Armed. Confirm E900_NETCONSOLE_READY on the receiver before releasing init.')


if __name__ == '__main__':
    main()
