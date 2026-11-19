#!/usr/bin/env python3
"""Exercise image preparation with real host tools and tiny synthetic OS files.

Usage: check-usb-roundtrip.py <compiled-board.dtb> <mtools-directory> <mkimage>
This tests packaging, not Linux/SYSTEM bootability or physical USB hardware.
"""
import gzip
import importlib.util
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usb_roundtrip", PORT / "scripts/prepare-usb-image.py")
usb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usb)
dtb, mtools, mkimage = [pathlib.Path(value).resolve() for value in sys.argv[1:]]
usb.board.validate(dtb)

with tempfile.TemporaryDirectory(prefix="e900-usb-roundtrip-") as directory:
    repo = pathlib.Path(directory) / "repo"
    target = repo / "target"
    target.mkdir(parents=True)
    toolchain = repo / "build.test/toolchain/bin"
    toolchain.mkdir(parents=True)
    (toolchain / "mkimage").symlink_to(mkimage)
    (toolchain / "mcopy").symlink_to(mtools / "mcopy")
    kernel = repo / "build.test/build/linux-test/arch/arm64/boot/Image.lzo"
    kernel.parent.mkdir(parents=True)
    identity = repo / "build.test/BUILD_FILENAME"
    identity.write_text("CoreELEC-test\n")
    def newc(name,body,mode):
        fields=[1,mode,0,0,1,0,len(body),0,0,0,0,len(name)+1,0]
        head=b"070701"+b"".join(f"{v:08x}".encode() for v in fields)+name.encode()+b"\0"
        head+=bytes(-len(head)%4)
        return head+body+bytes(-len(body)%4)
    ramdisk=newc('init',b'#!/bin/sh\necho synthetic test\n',0o100755)+newc('TRAILER!!!',b'',0)
    container=bytearray(4096+len(ramdisk))
    container[:8]=b'ANDROID!'
    struct.pack_into('<8I',container,8,16,0x1080000,len(ramdisk),0x1000000,0,0xf00000,0x100,2048)
    container[2048:2064]=b'synthetic kernel'
    container[4096:]=ramdisk
    kernel.write_bytes(container)
    image=kernel.with_name('Image');raw_image=bytearray(4096)
    struct.pack_into('<2Q',raw_image,8,0x1080000,4096)
    raw_image[56:60]=b'ARMd';image.write_bytes(raw_image)
    module_tree=repo/'build.test/build/media_modules-aml-test/drivers'
    module_tree.mkdir(parents=True)
    names=['decoder_common.ko','amvdec_mh264.ko']
    squash=repo/'system-root'
    installed=squash/'usr/lib/kernel-overlays/base/lib/modules/4.9.269/media_modules-aml'
    installed.mkdir(parents=True)
    for name in names:
        (module_tree/name).write_bytes(b'synthetic module')
        shutil.copy2(module_tree/name,installed/name)
    board = kernel.parent / "dts/amlogic/coreelec-gxl" / (usb.board.BOARD + ".dtb")
    board.parent.mkdir(parents=True)
    shutil.copy2(dtb, board)
    (repo / ".e900-profile.json").write_text(json.dumps(dict(profile="decoder", board_dtb=usb.board.BOARD)))
    system = target / "CoreELEC-test.system"
    squash_tool=shutil.which('mksquashfs')
    assert squash_tool and shutil.which('unsquashfs'),'Install squashfs-tools'
    subprocess.run([squash_tool,str(squash),str(system),'-noappend','-processors','1','-all-root','-quiet'],check=True)
    raw = target / "fixture.img"
    start, sectors = 2048, 65536
    header = bytearray(512)
    header[450] = 0x0c
    struct.pack_into("<II", header, 454, start, sectors)
    header[510:] = b"\x55\xaa"
    with raw.open("wb") as stream:
        stream.write(header)
        stream.truncate((start + sectors) * 512)
    partition = str(raw) + "@@" + str(start * 512)
    subprocess.run([str(mtools / "mformat"), "-i", partition, "-T", str(sectors), "-v", "COREELEC", "::"], check=True)
    for source, name in [(kernel, "kernel.img"), (system, "SYSTEM")]:
        subprocess.run([str(mtools / "mcopy"), "-i", partition, str(source), "::/" + name], check=True)
    compressed = target / "CoreELEC-test-Generic.img.gz"
    with raw.open("rb") as source, gzip.open(compressed, "wb") as destination:
        shutil.copyfileobj(source, destination)
    # Incremental caches retain old timestamped releases. Even a newer stale
    # file must not be selected or deleted in place of this build's image.
    stale = target / "CoreELEC-stale-Generic.img.gz"
    stale.write_bytes(b"stale cached image; must never be opened")
    os.utime(compressed, (1, 1))
    assert stale.stat().st_mtime > compressed.stat().st_mtime
    metadata = usb.prepare(repo)
    assert metadata['source_image'] == 'target/' + compressed.name
    assert metadata['build_filename'] == 'CoreELEC-test'
    assert stale.read_bytes() == b"stale cached image; must never be opened"
    assert set(metadata["fat_readback"]) == {"dtb.img", "e900-Image", "e900-uInitrd", "aml_autoscript", "s905_autoscript", "cfgload", "kernel.img", "SYSTEM"}
    assert metadata['media_modules']==sorted(names)
    assert metadata['boot_method'].startswith('booti /')
    import hashlib
    assert metadata['initramfs_sha256']==hashlib.sha256(ramdisk).hexdigest()
    # A matching SYSTEM hash alone must never hide missing media modules again.
    (installed/'amvdec_mh264.ko').unlink()
    bad_system=target/'missing-modules.system'
    subprocess.run([squash_tool,str(squash),str(bad_system),'-noappend','-processors','1','-all-root','-quiet'],check=True)
    try:usb.check_media_modules(repo,bad_system)
    except ValueError as exc:assert 'SYSTEM media modules mismatch' in str(exc)
    else:raise AssertionError('Missing media driver was accepted')
    environment = dict(os.environ, E900_WORK_ROOT=str(repo.parent / "work"))
    subprocess.run([sys.executable, str(PORT / "scripts/export-artifacts.py"), str(repo), "decoder", "image", "0"], env=environment, check=True)
    exported = pathlib.Path(environment["E900_WORK_ROOT"]) / "export/decoder"
    result = json.loads((exported / "build-metadata.json").read_text())
    assert result["usb_image_prepared"] is True
    assert any(entry["path"].endswith("-E900V21C-USB-TEST.img.gz") for entry in result["artifacts"])
    # An interrupted or failed retry must remove the prior exported test image.
    subprocess.run([sys.executable, str(PORT / "scripts/export-artifacts.py"), str(repo), "decoder", "image", "1"], env=environment, check=True)
    result = json.loads((exported / "build-metadata.json").read_text())
    assert result["usb_image_prepared"] is False
    assert not list((exported / "target").glob("*.img.gz"))
    # Never fall back to an old cached image if the current build is absent.
    identity.write_text('CoreELEC-missing\n')
    try:
        usb.prepare(repo)
    except ValueError as exc:
        assert 'Current build Generic image missing' in str(exc)
    else:
        raise AssertionError('Old cached image substituted for missing current build')
    assert not (repo / '.e900-usb-image.json').exists()
    for bad in ['../CoreELEC-test', '/tmp/CoreELEC-test', '', 'CoreELEC-test\nother']:
        identity.write_text(bad)
        try: usb.current_image(repo)
        except ValueError as exc: assert 'Invalid BUILD_FILENAME' in str(exc)
        else: raise AssertionError('Invalid build identity accepted')
    identity.unlink()
    try: usb.current_image(repo)
    except ValueError as exc: assert 'Expected one BUILD_FILENAME, found 0' in str(exc)
    else: raise AssertionError('Missing build identity accepted')
    identity.write_text('CoreELEC-test\n')
    other = repo / 'build.other/BUILD_FILENAME'
    other.parent.mkdir(); other.write_text('CoreELEC-stale\n')
    try: usb.current_image(repo)
    except ValueError as exc: assert 'Expected one BUILD_FILENAME, found 2' in str(exc)
    else: raise AssertionError('Ambiguous build identity accepted')
    other.unlink(); other.parent.rmdir()
    # Recreate the ready marker to check failed SYSTEM validation removes it.
    (repo / '.e900-usb-image.json').write_text(json.dumps(metadata))
    system.write_bytes(b"hsqs changed build output")
    try:
        usb.prepare(repo)
    except ValueError as exc:
        assert "SYSTEM does not match" in str(exc)
    else:
        raise AssertionError("Image with a stale SYSTEM was accepted")
    assert not (repo / ".e900-usb-image.json").exists()
    print("PASS: real mtools/mkimage FAT roundtrip, provenance export and failed-retry cleanup")
    print("PASS: mismatched SYSTEM rejects preparation and clears the ready marker")
    print("PASS: current BUILD_FILENAME selects among cached releases; missing/unsafe/ambiguous identity fails closed")

print("Synthetic payloads inside real FAT/SquashFS filesystems; source-built OS and hardware tests remain pending.")
