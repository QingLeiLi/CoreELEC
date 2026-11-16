#!/usr/bin/env python3
"""Negative checks for image bounds, script integrity and stale image exports."""
import importlib.util
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import zlib

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usb_image_test", PORT / "scripts/prepare-usb-image.py")
usb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usb)


def rejects(function, *args):
    try:
        function(*args)
    except ValueError:
        return
    raise AssertionError("Invalid image/script accepted")


with tempfile.TemporaryDirectory(prefix="e900-usb-check-") as directory:
    root = pathlib.Path(directory)
    image = root / "disk.img"
    sector = bytearray(512)
    sector[510:] = b"\x55\xaa"
    sector[450] = 0x0c
    struct.pack_into("<II", sector, 454, 1, 1)
    image.write_bytes(sector + bytes(512))
    assert usb.fat_offset(image) == 512
    struct.pack_into("<I", sector, 458, 2)
    image.write_bytes(sector + bytes(512))
    rejects(usb.fat_offset, image)
    sector[450] = 0x83
    image.write_bytes(sector + bytes(512))
    rejects(usb.fat_offset, image)
    print("PASS: partition bounds reject truncated images and non-FAT boot partitions")

    source = b"echo test\n"
    payload = struct.pack(">II", len(source), 0) + source
    header = bytearray(struct.pack(">7I4B32s", 0x27051956, 0, 0, len(payload), 0, 0,
                                   zlib.crc32(payload), 5, 2, 6, 0, b"test"))
    struct.pack_into(">I", header, 4, zlib.crc32(header))
    script = root / "script"
    script.write_bytes(header + payload)
    usb.check_script(script, source)
    rejects(usb.check_script, script, b"different source")
    broken = bytearray(script.read_bytes())
    broken[-1] ^= 1
    script.write_bytes(broken)
    rejects(usb.check_script, script, source)
    broken[0] ^= 1
    script.write_bytes(broken)
    rejects(usb.check_script, script, source)
    print("PASS: U-Boot script validates source content, header CRC and data CRC")

    repo = root / "repo"
    repo.mkdir()
    state = dict(profile="decoder", board_dtb=usb.board.BOARD)
    (repo / ".e900-profile.json").write_text(json.dumps(state))
    # Even an apparently prepared image from another run must not be exported.
    (repo / ".e900-usb-image.json").write_text(json.dumps(dict(
        image="target/old-E900V21C-USB-TEST.img.gz", run_id="previous-run", run_attempt="1")))
    work = root / "work"
    export = work / "export/decoder"
    stale = export / "target/old-E900V21C-USB-TEST.img.gz"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale image")
    (export / "build-metadata.json").write_text(json.dumps(dict(artifacts=[dict(path=str(stale.relative_to(export)))])))
    environment = dict(os.environ, E900_WORK_ROOT=str(work), GITHUB_RUN_ID="new-run", GITHUB_RUN_ATTEMPT="1")
    for action, result in [("image", "0"), ("image", "1"), ("media", "0")]:
        subprocess.run([sys.executable, str(PORT / "scripts/export-artifacts.py"), str(repo),
                        "decoder", action, result], env=environment, check=True)
        metadata = json.loads((export / "build-metadata.json").read_text())
        assert metadata["usb_image_prepared"] is False and not metadata["artifacts"]
        assert not stale.exists()
    print("PASS: old-run images, failed builds and media-only runs never export a ready USB image")

print("USB IMAGE GUARDS PASSED. FAT readback runs when preparing the actual image.")
