#!/usr/bin/env python3
"""Prepare a regular-file USB test image; never open a block device or mount it."""
import gzip
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("board_validator", PORT / "scripts/validate-board.py")
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fat_offset(path):
    with path.open("rb") as stream:
        sector = stream.read(512)
    if len(sector) != 512 or sector[510:] != b"\x55\xaa":
        raise ValueError("Missing DOS partition table")
    kind = sector[450]
    start, count = struct.unpack_from("<II", sector, 454)
    if kind not in {0x06, 0x0b, 0x0c, 0x0e} or start < 1 or count < 1:
        raise ValueError("First partition must be FAT")
    if (start + count) * 512 > path.stat().st_size:
        raise ValueError("FAT partition extends beyond the image")
    return start * 512


def check_script(path, source):
    data = path.read_bytes()
    if len(data) < 72:
        raise ValueError("Truncated U-Boot script")
    fields = struct.unpack(">7I4B32s", data[:64])
    header = bytearray(data[:64])
    header[4:8] = b"\0" * 4
    if fields[0] != 0x27051956 or zlib.crc32(header) != fields[1]:
        raise ValueError("Invalid U-Boot script header")
    payload = data[64:]
    if fields[3] != len(payload) or zlib.crc32(payload) != fields[6]:
        raise ValueError("Invalid U-Boot script payload")
    # ARM / Linux / script / uncompressed. Legacy multi-image size table.
    if fields[7:11] != (5, 2, 6, 0):
        raise ValueError("Unexpected U-Boot script format")
    size, end = struct.unpack_from(">II", payload)
    if end != 0 or size != len(source) or payload[8:8 + size] != source:
        raise ValueError("U-Boot script does not contain the reviewed source")


def prepare(repo):
    state = json.loads((repo / ".e900-profile.json").read_text())
    if state["profile"] != "decoder" or state.get("board_dtb") != board.BOARD:
        raise ValueError("USB image requires the decoder board profile")
    marker = repo / ".e900-usb-image.json"
    marker.unlink(missing_ok=True)
    dtb = board.find_board(repo)
    validated = board.validate(dtb)
    candidates = list((repo / "target").glob("*-Generic.img.gz"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one Generic image, found {len(candidates)}")
    source_image = candidates[0]
    tools = {}
    for name in ["mcopy", "mkimage"]:
        matches = list(repo.glob(f"build.*/toolchain/bin/{name}"))
        if len(matches) != 1:
            raise ValueError(f"Expected one built host tool: {name}")
        tools[name] = str(matches[0])
    script_source = PORT / "boards/e900-usb-autoscript.src"
    source_bytes = script_source.read_bytes()
    forbidden = {"saveenv", "defenv", "store", "mmc", "nand", "reset"}
    for line in source_bytes.decode().splitlines():
        command = line.strip().split()
        if command and (command[0] in forbidden or command[:2] == ["env", "save"]):
            raise ValueError("Persistent bootloader operation in USB test script")
    output = source_image.with_name(source_image.name.replace("-Generic.img.gz", "-E900V21C-USB-TEST.img.gz"))
    with tempfile.TemporaryDirectory(prefix=".e900-usb-", dir=repo / "target") as directory:
        temporary = pathlib.Path(directory)
        raw = temporary / "test.img"
        with gzip.open(source_image, "rb") as src, raw.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        offset = fat_offset(raw)
        script = temporary / "autoscript"
        subprocess.run([tools["mkimage"], "-A", "arm", "-O", "linux", "-T", "script",
                        "-C", "none", "-n", "E900 USB test", "-d", str(script_source), str(script)], check=True)
        check_script(script, source_bytes)
        image_argument = str(raw) + "@@" + str(offset)
        entries = {"dtb.img": dtb, "aml_autoscript": script, "s905_autoscript": script, "cfgload": script}
        readback = {}
        for name, source in entries.items():
            subprocess.run([tools["mcopy"], "-i", image_argument, "-o", str(source), "::/" + name], check=True)
            copied = temporary / (name + ".readback")
            subprocess.run([tools["mcopy"], "-i", image_argument, "::/" + name, str(copied)], check=True)
            if copied.read_bytes() != source.read_bytes():
                raise ValueError(f"FAT readback mismatch: {name}")
            readback[name] = sha256(copied)
        # Also verify this is a complete CE image, with the kernel just built.
        kernel = temporary / "kernel.img"
        subprocess.run([tools["mcopy"], "-i", image_argument, "::/kernel.img", str(kernel)], check=True)
        expected_kernels = list(repo.glob("build.*/build/linux-*/arch/arm64/boot/Image.lzo"))
        if len(expected_kernels) != 1 or sha256(kernel) != sha256(expected_kernels[0]):
            raise ValueError("USB image kernel does not match this build")
        with kernel.open("rb") as stream:
            if stream.read(8) != b"ANDROID!":
                raise ValueError("Expected CE's existing Android boot image container")
        system = temporary / "SYSTEM"
        subprocess.run([tools["mcopy"], "-i", image_argument, "::/SYSTEM", str(system)], check=True)
        with system.open("rb") as stream:
            if stream.read(4) != b"hsqs":
                raise ValueError("SYSTEM is not a SquashFS filesystem")
        expected_system = source_image.with_name(source_image.name[:-len("-Generic.img.gz")] + ".system")
        if not expected_system.is_file() or sha256(system) != sha256(expected_system):
            raise ValueError("USB SYSTEM does not match this build")
        readback["kernel.img"] = sha256(kernel)
        readback["SYSTEM"] = sha256(system)
        compressed = temporary / output.name
        with raw.open("rb") as src, compressed.open("wb") as dst:
            with gzip.GzipFile(filename="", mode="wb", fileobj=dst, mtime=0, compresslevel=6) as archive:
                shutil.copyfileobj(src, archive)
        compressed.replace(output)
    digest = sha256(output)
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n")
    metadata = dict(schema=1, run_id=os.environ.get("GITHUB_RUN_ID", "local"),
                    run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
                    image=str(output.relative_to(repo)), sha256=digest, board=validated,
                    profile_state_sha256=sha256(repo / ".e900-profile.json"),
                    boot_script_sha256=sha256(script_source), fat_readback=readback,
                    hardware_tested=False, intended_use="external USB test only")
    marker.write_text(json.dumps(metadata, indent=2) + "\n")
    output.with_name(output.name + ".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared and read back USB test image: {output}")
    return metadata


if __name__ == "__main__":
    prepare(pathlib.Path(sys.argv[1]).resolve())
