#!/usr/bin/env python3
"""Exercise final-image hook, failure cleanup and real Linux hwdb generation."""
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from unittest import mock

PORT = Path(__file__).resolve().parents[1]
REF = Path(os.environ.get('E900_CE_REFERENCE', PORT / 'reference/CoreELEC'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('hwdb_image_builder', PORT / 'scripts/prebuild-hwdb.py')
installer = load('hwdb_image_installer', PORT / 'scripts/install-patches.py')
with tempfile.TemporaryDirectory(prefix='e900-hwdb-test-') as temporary:
    root = Path(temporary)
    repo = root / 'repo'
    (repo / 'scripts').mkdir(parents=True)
    shutil.copy2(REF / 'scripts/image', repo / 'scripts/image')
    original = (repo / 'scripts/image').read_text()
    fix = installer.image_build_fix(repo, True, None)
    assert original.count('# Create squashfs file,') == 1
    assert fix[1].index(installer.HWDB_IMAGE_HOOK) > fix[1].index('# Copy DEVICE related files')
    assert fix[1].index(installer.HWDB_IMAGE_HOOK) < fix[1].index('# Create squashfs file,')
    (repo / fix[0]).write_text(fix[1])
    assert installer.image_build_fix(repo, True, fix[2]) == fix
    assert installer.image_build_fix(repo, False, fix[2])[1] == original
    (repo / fix[0]).write_text(fix[1] + '\n# local edit\n')
    try:
        installer.image_build_fix(repo, True, fix[2])
    except RuntimeError as exc:
        assert 'Locally edited' in str(exc)
    else:
        raise AssertionError('Accepted local image hook edit')

    image = root / 'image'
    vendor = image / 'usr/lib/udev/hwdb.d'
    vendor.mkdir(parents=True)
    (vendor / '20-e900.hwdb').write_text('e900:test:*\n ID_E900_TEST=vendor\n ID_E900_ORDER=early\n\n')
    (vendor / '90-e900.hwdb').write_text('e900:test:*\n ID_E900_ORDER=late\n\n')
    # User rules deliberately resolve outside the staging tree, as on CE.
    user = root / 'user-rules'
    user.mkdir()
    (user / 'README').write_text('CE ships documentation here, not a hardware rule.\n')
    (user / '99-user.hwdb').write_text('e900:test:*\n ID_E900_TEST=user\n\n')
    (image / 'etc/udev').mkdir(parents=True)
    (image / 'etc/udev/hwdb.d').symlink_to(user)
    output = image / 'usr/lib/udev/hwdb.bin'
    record = image / 'usr/lib/e900-boot/hwdb-build.json'
    record.parent.mkdir(parents=True)
    # Failure must discard stale image outputs rather than ship an old database.
    output.write_text('stale')
    record.write_text('stale')
    with mock.patch.object(builder.subprocess, 'check_output', return_value='systemd 249\n'), \
            mock.patch.object(builder.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'hwdb')):
        try:
            builder.prepare(image, '/test/hwdb')
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('Accepted failed hwdb generator')
    assert not output.exists() and not record.exists()
    (vendor / '99-linked.hwdb').symlink_to(user / '99-user.hwdb')
    try:
        builder.prepare(image)
    except ValueError:
        pass
    else:
        raise AssertionError('Followed external vendor rules')
    (vendor / '99-linked.hwdb').unlink()
    # Fixed LE header/layout for supported systemd versions; rejects truncation.
    valid = b'KSLPHHRH' + struct.pack('<9Q', 249, 105, 80, 24, 16, 32, 80, 24, 1) + bytes(25)
    assert builder.validate_database(valid) == 249
    for bad in (valid[:-1], b'broken', valid[:8] + struct.pack('<Q', 256) + valid[16:]):
        try:
            builder.validate_database(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted malformed/unsupported hwdb')
    def jammy_path_generator(command, **kwargs):
        stage = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--root=')))
        assert (stage / 'lib').is_symlink()
        assert {p.name for p in (stage / 'lib/udev/hwdb.d').iterdir()} == {'20-e900.hwdb', '90-e900.hwdb'}
        assert not (stage / 'etc/udev/hwdb.d').exists()
        (stage / 'lib/udev/hwdb.bin').write_bytes(valid)
    with mock.patch.object(builder.subprocess, 'check_output', return_value='systemd 249\n'), \
            mock.patch.object(builder.subprocess, 'run', side_effect=jammy_path_generator):
        builder.prepare(image, '/test/hwdb')
    assert output.read_bytes() == valid
    print('PASS: final-image hook ordering/idempotence, local-edit protection and failed-retry cleanup')

    if sys.platform != 'linux':
        print('PENDING on this host: real systemd generation, database queries and unit conditions (mandatory on Linux CI)')
        sys.exit(0)
    tool = shutil.which('systemd-hwdb')
    assert tool, 'Linux CI must install systemd-hwdb'
    # Execute the actual injected image hook, with the final synthetic SYSTEM.
    shutil.copy2(PORT / 'scripts/prebuild-hwdb.py', repo / 'scripts/e900-prebuild-hwdb.py')
    subprocess.run(['bash', '-eu', '-c', installer.HWDB_IMAGE_HOOK], check=True,
                   env=dict(os.environ, ROOT=str(repo), INSTALL=str(image)))
    metadata = json.loads(record.read_text())
    assert metadata['sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert {r['path'] for r in metadata['rules']} == {'20-e900.hwdb', '90-e900.hwdb'}
    # Real native libsystemd reader, no Python reimplementation of trie lookup.
    library = ctypes.CDLL(ctypes.util.find_library('systemd'))
    library.sd_hwdb_new_from_path.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    library.sd_hwdb_get.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)]
    library.sd_hwdb_unref.argtypes = [ctypes.c_void_p]
    hwdb = ctypes.c_void_p()
    assert library.sd_hwdb_new_from_path(os.fsencode(output), ctypes.byref(hwdb)) == 0
    try:
        for key, expected in [('ID_E900_TEST', b'vendor'), ('ID_E900_ORDER', b'late')]:
            value = ctypes.c_char_p()
            assert library.sd_hwdb_get(hwdb, b'e900:test:remote', key.encode(), ctypes.byref(value)) == 0
            assert value.value == expected
    finally:
        library.sd_hwdb_unref(hwdb)
    drop = (PORT / 'config/20-e900-hwdb-prebuilt.conf').read_text()
    assert 'ConditionDirectoryNotEmpty=\n' in drop
    assert 'ConditionPathExistsGlob=|/etc/udev/hwdb.d/*.hwdb' in drop
    # Use systemd's own evaluator with the refined OR group: a README is not a rule.
    def should_rebuild():
        return subprocess.run(['systemd-analyze', 'condition',
            'ConditionPathExists=|!' + str(output),
            'ConditionPathExists=|' + str(image / 'run/hwdb.bin'),
            'ConditionPathExistsGlob=|' + str(image / 'etc/udev/hwdb.d/*.hwdb')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    assert should_rebuild(), 'User overrides must still rebuild'
    (user / '99-user.hwdb').unlink()
    assert not should_rebuild(), 'Stock prebuilt image must skip rebuild'
    output.unlink()
    assert should_rebuild(), 'Missing database must still rebuild'
    print('PASS: actual image hook generates/queryable vendor hwdb, excludes user rules and retains runtime rebuild conditions')
print('PENDING: ARM target reader/physical boot timing and input-device regression')
