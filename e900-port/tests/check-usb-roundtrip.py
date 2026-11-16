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
    kernel.write_bytes(b"ANDROID!" + bytes(4096))
    board = kernel.parent / "dts/amlogic/coreelec-gxl" / (usb.board.BOARD + ".dtb")
    board.parent.mkdir(parents=True)
    shutil.copy2(dtb, board)
    (repo / ".e900-profile.json").write_text(json.dumps(dict(profile="decoder", board_dtb=usb.board.BOARD)))
    system = target / "CoreELEC-test.system"
    system.write_bytes(b"hsqs" + bytes(4096))
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
    metadata = usb.prepare(repo)
    assert set(metadata["fat_readback"]) == {"dtb.img", "aml_autoscript", "s905_autoscript", "cfgload", "kernel.img", "SYSTEM"}
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

print("Synthetic OS files only; the actual CoreELEC SYSTEM and hardware still need testing.")
