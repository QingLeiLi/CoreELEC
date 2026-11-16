#!/usr/bin/env python3
"""Repackage a verified CE build into an external-USB booti diagnostic kit."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import zipfile
import zlib

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usb_image", PORT / "scripts/prepare-usb-image.py")
usb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usb)


def legacy_image(path, kind, compression, payload):
    data = path.read_bytes()
    header = bytearray(data[:64])
    fields = struct.unpack(">7I4B32s", header)
    header[4:8] = b"\0" * 4
    assert fields[0] == 0x27051956 and zlib.crc32(header) == fields[1]
    assert fields[3] == len(data) - 64 and zlib.crc32(data[64:]) == fields[6]
    assert fields[7:11] == (5, 22, kind, compression)
    assert data[64:] == payload


def make(export, destination, mkimage):
    metadata = json.loads((export / "build-metadata.json").read_text())
    assert metadata["last_action_exit_code"] == 0 and metadata["usb_image_prepared"] is True
    assert metadata["board_dtb"] == usb.board.BOARD
    entries = metadata["artifacts"]

    def artifact(suffix):
        matches = [entry for entry in entries if entry["path"].endswith(suffix)]
        assert len(matches) == 1, suffix
        path = export / matches[0]["path"]
        assert path.resolve().is_relative_to(export.resolve())
        assert usb.sha256(path) == matches[0]["sha256"]
        return path

    kernel = artifact("/arch/arm64/boot/Image")
    container = artifact("/arch/arm64/boot/Image.lzo")
    dtb = artifact("/coreelec-gxl/" + usb.board.BOARD + ".dtb")
    usb.board.validate(dtb)
    data = container.read_bytes()
    assert data[:8] == b"ANDROID!"
    kernel_size, _, ramdisk_size, _, second_size, _, _, page = struct.unpack_from("<8I", data, 8)
    assert page in {2048, 4096, 8192} and second_size == 0 and ramdisk_size > 0
    offset = ((page + kernel_size + page - 1) // page) * page
    ramdisk = data[offset:offset + ramdisk_size]
    assert len(ramdisk) == ramdisk_size and ramdisk.startswith(b"070701")
    with kernel.open("rb") as stream:
        image_header = stream.read(64)
    assert image_header[56:60] == b"ARMd"
    assert destination.resolve() != export.resolve() and not destination.exists()
    destination.mkdir(parents=True)
    shutil.copy2(kernel, destination / "e900-Image")
    shutil.copy2(dtb, destination / "dtb.img")
    packed_ramdisk = gzip.compress(ramdisk, mtime=0)
    temporary = destination / ".initramfs.cpio.gz"
    temporary.write_bytes(packed_ramdisk)
    initrd = destination / "e900-uInitrd"
    subprocess.run([str(mkimage), "-A", "arm64", "-O", "linux", "-T", "ramdisk", "-C", "gzip",
                    "-n", "E900 CE initramfs", "-d", str(temporary), str(initrd)], check=True)
    legacy_image(initrd, 3, 1, packed_ramdisk)
    assert gzip.decompress(initrd.read_bytes()[64:]) == ramdisk
    temporary.unlink()
    source = PORT / "boards/e900-usb-booti.src"
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 booti diagnostic", "-d", str(source), str(script)], check=True)
    usb.check_script(script, source.read_bytes())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    rollback = destination / "rollback"
    rollback.mkdir()
    # Rollback files are rebuilt from the exact script used by the verified image.
    original = PORT / "boards/e900-usb-autoscript.src"
    assert usb.sha256(original) == metadata["usb_image"]["boot_script_sha256"]
    old_script = rollback / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 USB test", "-d", str(original), str(old_script)], check=True)
    usb.check_script(old_script, original.read_bytes())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(old_script, rollback / name)
    report = dict(source_run=metadata["usb_image"]["run_id"], source_container_sha256=usb.sha256(container),
                  kernel_sha256=usb.sha256(kernel), dtb_sha256=usb.sha256(dtb),
                  initramfs_cpio_sha256=hashlib.sha256(ramdisk).hexdigest(),
                  image_text_offset=struct.unpack_from("<Q", image_header, 8)[0],
                  method="booti with legacy ARM64 gzip ramdisk; panic=0", hardware_tested=False,
                  changed="USB loader path and panic/log settings; same kernel, DTB, initramfs and SYSTEM")
    (destination / "kit-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    (destination / "README.txt").write_text(
        "E900V21C diagnostic USB kit; hardware validation pending.\n"
        "Power off the box. Copy these SIX files to the existing COREELEC FAT root:\n"
        "e900-Image, e900-uInitrd, dtb.img, aml_autoscript, s905_autoscript, cfgload.\n"
        "Overwrite existing files. Keep SYSTEM and kernel.img unchanged. Do not reflash eMMC.\n"
        "Uses booti with the same CE kernel and initramfs, following the working Armbian load layout.\n"
        "panic=0 disables timed software panic reboot; a hardware watchdog may still reset.\n"
        "To roll back, copy the three scripts inside rollback/ to the FAT root.\n")
    paths = sorted(path for path in destination.rglob("*") if path.is_file())
    (destination / "SHA256SUMS").write_text("".join(f"{usb.sha256(path)}  {path.relative_to(destination)}\n" for path in paths))
    archive = destination.with_suffix(".zip")
    assert not archive.exists()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in destination.rglob("*"):
            if path.is_file():
                output.write(path, str(path.relative_to(destination)))
    print(f"Prepared diagnostic kit: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--mkimage", required=True, type=pathlib.Path)
    args = parser.parse_args()
    make(args.export.resolve(), args.destination.resolve(), args.mkimage.resolve())
