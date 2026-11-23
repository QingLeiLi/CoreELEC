#!/usr/bin/env python3
"""Receive kernel UDP console packets; flush them to a host log immediately."""
import argparse
import datetime
import os
from pathlib import Path
import socket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=6666)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((args.bind, args.port))
        with args.output.open('ab', buffering=0) as log:
            print(f'Listening on UDP {args.bind}:{args.port}; log: {args.output}', flush=True)
            try:
                while True:
                    packet, peer = udp.recvfrom(65535)
                    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    record = f'[{stamp} {peer[0]}:{peer[1]}] '.encode() + packet.rstrip(b'\n') + b'\n'
                    log.write(record)
                    os.fsync(log.fileno())
                    print(record.decode(errors='replace'), end='', flush=True)
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
