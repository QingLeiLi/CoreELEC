#!/usr/bin/env python3
"""Precompile the final image's built-in hwdb using the Linux host tool.

The on-disk trie is little-endian and consumed by the target's systemd 255.
Stage only vendor rules: never follow the image's /etc -> /storage links or
include the build machine's hardware rules. Runtime user overrides still use
the unmodified CE hwdb rebuild service and its higher-priority /run database.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def validate_database(data):
    if len(data) < 80 or data[:8] != b'KSLPHHRH':
        raise ValueError('Invalid hwdb signature/header')
    version, size, header, node, child, value, root, nodes, strings = struct.unpack_from('<9Q', data, 8)
    if not (249 <= version <= 255 and size == len(data) and header == 80
            and node == 24 and child == 16 and value in (16, 32)
            and nodes >= node and header <= root <= header + nodes - node
            and header + nodes + strings == size):
        raise ValueError('Unsupported or truncated hwdb layout')
    return version


def prepare(image, tool=None):
    image = Path(image).resolve()
    vendor = image / 'usr/lib/udev/hwdb.d'
    output = image / 'usr/lib/udev/hwdb.bin'
    metadata = image / 'usr/lib/e900-boot/hwdb-build.json'
    # No old database may survive a failed image assembly/retry.
    output.unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)
    if vendor.is_symlink() or not vendor.is_dir():
        raise ValueError('Missing real vendor hwdb.d directory')
    rules = sorted(vendor.glob('*.hwdb'))
    if not rules or any(p.is_symlink() or not p.is_file() for p in rules):
        raise ValueError('Missing or unexpected vendor hwdb rule')
    tool = tool or shutil.which('systemd-hwdb')
    if not tool:
        raise RuntimeError('Install the build host udev package (systemd-hwdb)')
    version = subprocess.check_output([str(tool), '--version'], text=True)
    match = re.match(r'systemd (\d+)\b', version)
    if not match or not 249 <= int(match[1]) <= 255:
        raise ValueError('Host hwdb generator must be systemd 249..255')
    with tempfile.TemporaryDirectory(prefix='e900-hwdb-') as temporary:
        stage = Path(temporary)
        dest = stage / 'usr/lib/udev/hwdb.d'
        dest.mkdir(parents=True)
        # Jammy's tool may use /lib/udev, CE's uses /usr/lib/udev. Model
        # merged-/usr inside the isolated root so both see exactly our rules.
        (stage / 'lib').symlink_to('usr/lib')
        manifest = []
        for rule in rules:
            data = rule.read_bytes()
            (dest / rule.name).write_bytes(data)
            manifest.append(dict(path=rule.name, sha256=hashlib.sha256(data).hexdigest()))
        env = dict(os.environ, LC_ALL='C')
        subprocess.run([str(tool), '--usr', '--root=' + str(stage), 'update'], check=True, env=env)
        database = (stage / 'usr/lib/udev/hwdb.bin').read_bytes()
        generated_version = validate_database(database)
        if generated_version != int(match[1]):
            raise ValueError('Generator version does not match database')
        output.write_bytes(database)
        output.chmod(0o444)
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(dict(schema=1, tool=version.splitlines()[0],
            sha256=hashlib.sha256(database).hexdigest(), rules=manifest), indent=2) + '\n')
    print(f'Precompiled E900 hwdb: {len(rules)} vendor files, {len(database)} bytes; runtime user overrides retained')


if __name__ == '__main__':
    prepare(sys.argv[1])
