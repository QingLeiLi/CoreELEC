#!/usr/bin/env python3
"""Prepare one automatic MMU + initramfs test; deploy scripts separately."""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, PORT / "scripts" / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def cpio_read(data):
    result, offset = [], 0
    while True:
        assert data[offset:offset + 6] == b"070701"
        fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        name = data[offset + 110:offset + 110 + namesize - 1].decode()
        start = (offset + 110 + namesize + 3) & ~3
        body = data[start:start + size]
        assert len(body) == size
        offset = (start + size + 3) & ~3
        if name == "TRAILER!!!":
            return result
        result.append((name, fields, body))


def cpio_write(entries):
    data = bytearray()
    trailer = ("TRAILER!!!", [0] * 13, b"")
    for name, old_fields, body in [*entries, trailer]:
        fields = list(old_fields)
        fields[6], fields[11] = len(body), len(name.encode()) + 1
        data += b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
        data += name.encode() + b"\0"
        data += b"\0" * (-len(data) % 4)
        data += body
        data += b"\0" * (-len(data) % 4)
    return bytes(data) + b"\0" * (-len(data) % 512)


def prepare(kit, verified_slot, destination, serial, mkimage, clang):
    trace = module("dual_trace", "make-entry-trace.py")
    reset = module("dual_reset", "make-reset-entry-image.py")
    disk = module("dual_disk", "prepare-usb-write-probe.py")
    usb = module("dual_usb", "prepare-usb-image.py")
    legacy = module("dual_legacy", "make-booti-test-kit.py")
    slot = json.loads(verified_slot.read_text())
    assert slot["hardware_write_tested"] is True and not destination.exists()
    nonce = slot["nonce"]
    assert len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce)
    destination.mkdir(parents=True)

    def sector(text):
        value = text.encode()
        assert len(value) < 512
        return value + b" " * (511 - len(value)) + b"\n"

    mmu_initial = sector(f"E900 dual10 MMU not yet observed nonce={nonce}\n")
    mmu_pass = sector(f"E900 dual10 MMU enabled and reset marker observed nonce={nonce}\n")
    user_initial = sector(f"E900 dual10 /init not yet observed nonce={nonce}\n")
    user_pass = sector(f"E900 dual10 /init reached nonce={nonce}\n")
    for name, value in [("E9MMU.TXT", mmu_initial), ("E9USER.TXT", user_initial),
                        ("E9MPASS.BIN", mmu_pass), ("E9UPASS.BIN", user_pass)]:
        (destination / name).write_bytes(value)

    original = (kit / "e900-Image").read_bytes()
    assert hashlib.sha256(original).hexdigest() == trace.PINNED_IMAGE
    hook, scratch = 0xcf1240, 0xcf1350
    expected_tail = [0xd5182001, 0xd5182022, 0xd5033fdf, 0xd5181000, 0xd5033fdf,
                     0xd508751f, 0xd503379f, 0xd5033fdf, 0xd65f03c0]
    assert list(struct.unpack_from("<9I", original, hook - 32)) == expected_tail
    assert hashlib.sha256(original[scratch:scratch + 112]).hexdigest() == "6b2722fd64581106ad1e30215605fdd46f491528dd323c8a88ac290e7d070aad"
    with tempfile.TemporaryDirectory(prefix="e900-mmu-hook-") as temporary:
        obj = pathlib.Path(temporary) / "mmu.o"
        subprocess.run([clang, "-target", "aarch64-none-elf", "-c", str(PORT / "boards/e900-mmu-reset.S"), "-o", str(obj)], check=True)
        stub = reset.text_section(obj.read_bytes())
    assert len(stub) == 104 and hook // 4096 == scratch // 4096 == (scratch + len(stub) - 1) // 4096
    assert scratch + len(stub) < 0xcf1430  # Do not overwrite __cpu_setup.
    assert stub[-16:] == struct.pack("<QII", 0x074ff000, 0xe9100001, 0)
    image = bytearray(original)
    struct.pack_into("<I", image, hook, trace.branch(hook, scratch))
    image[scratch:scratch + len(stub)] = stub
    assert image[:64] == original[:64]
    assert image[:hook] == original[:hook] and image[hook + 4:scratch] == original[hook + 4:scratch]
    assert image[scratch + len(stub):] == original[scratch + len(stub):]
    (destination / "e900-Image-mmu").write_bytes(image)
    (destination / "E9MSEED.BIN").write_bytes(struct.pack("<II", 0xe9100000, 0))
    (destination / "E9USEED.BIN").write_bytes(struct.pack("<II", 0xe9100010, 0))

    initrd = (kit / "e900-uInitrd").read_bytes()
    archive = gzip.decompress(initrd[64:])
    assert hashlib.sha256(archive).hexdigest() == trace.PINNED_INITRD
    entries = cpio_read(archive)
    originals = {name: (fields, body) for name, fields, body in entries}
    assert "init" in originals and "usr/bin/busybox" in originals
    assert "e9" not in originals and "init.ce-original" not in originals
    new_entries = [("init.ce-original" if name == "init" else name, fields, body) for name, fields, body in entries]
    inode = max(fields[0] for _, fields, _ in entries) + 1

    def add(name, mode, body):
        nonlocal inode
        fields = [inode, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, 0, 0]
        new_entries.append((name, fields, body))
        inode += 1

    init_source = (PORT / "boards/e900-userspace-init.src.in").read_text().replace("@NONCE@", nonce).encode()
    add("init", 0o100755, init_source)
    add("e9", 0o40755, b"")
    add("e9/user-marker.bin", 0o100644, struct.pack("<I", 0xe9100002))
    add("e9/userspace-proof.txt", 0o100644, user_pass)
    rebuilt = cpio_write(new_entries)
    decoded = {name: (fields, body) for name, fields, body in cpio_read(rebuilt)}
    for name, value in originals.items():
        actual = decoded["init.ce-original" if name == "init" else name]
        fields, body = value
        fields = list(fields)
        if name == "init":
            fields[11] = len("init.ce-original") + 1
        assert actual == (fields, body)
    (destination / "diagnostic-init.sh").write_bytes(init_source)
    packed = gzip.compress(rebuilt, mtime=0)
    cpio_gz = destination / "diagnostic.cpio.gz"
    cpio_gz.write_bytes(packed)
    user_initrd = destination / "e900-uInitrd-user"
    subprocess.run([str(mkimage), "-A", "arm64", "-O", "linux", "-T", "ramdisk", "-C", "gzip",
                    "-n", "E900 diagnostic PID1", "-d", str(cpio_gz), str(user_initrd)], check=True)
    legacy.legacy_image(user_initrd, 3, 1, packed)

    adb = ["adb", "-s", serial]
    # Only normal filesystem writes here. Scripts are deployed later, after tests.
    subprocess.run(adb + ["push"] + [str(destination / n) for n in ["E9MMU.TXT", "E9USER.TXT", "E9MPASS.BIN", "E9UPASS.BIN"]]
                   + ["/storage/external_storage/sda1/"], check=True)
    subprocess.run(adb + ["shell", "sync"], check=True)

    def read(lba, count):
        result = subprocess.run(adb + ["shell", f"busybox dd if=/dev/block/sda bs=512 skip={lba} count={count} 2>/dev/null | busybox base64"],
                                check=True, capture_output=True, timeout=25)
        value = base64.b64decode(b"".join(result.stdout.split()), validate=True)
        assert len(value) == count * 512
        return value

    current = subprocess.run(adb + ["shell", "cat /storage/external_storage/sda1/E9LOG.TXT | busybox base64"],
                             check=True, capture_output=True, timeout=25)
    current = base64.b64decode(b"".join(current.stdout.split()), validate=True)
    (destination / "previous-evidence.txt").write_bytes(current)
    volume = disk.FatDisk(read)
    log_slot = volume.evidence_slot(current)
    assert all(log_slot[k] == slot[k] for k in ["lba", "cluster", "volume_id"])
    mmu_slot = volume.evidence_slot(mmu_initial, b"E9MMU   TXT")
    assert mmu_slot["lba"] != log_slot["lba"]
    guard_template = (PORT / "boards/e900-usb-write-probe.src.in").read_text()
    stages = []

    def prefix(phase):
        return f"E900 dual10 {phase} nonce={nonce}\n".encode().ljust(64, b" ")

    for phase in ["P1", "P2"]:
        (destination / f"E9{phase}FLAG.BIN").write_bytes(prefix(phase) + b" " * 447 + b"\n")

    def guard(filename, target, lba, indent):
        text = guard_template.replace("@LBA@", hex(lba)).replace("E9NEXT.BIN", filename).replace("E9LOG.TXT", target)
        lines = [line for line in text.splitlines() if not line.startswith("echo ") and not line.startswith("setenv bootargs ")]
        lines += ['if test "${e9_write}" != "passed"; then', '  setenv e9_log failed', 'fi']
        return [indent + 'if test "${e9_log}" = "passed"; then'] + [indent + "  " + line for line in lines] + [indent + "fi"]

    output = []
    for line in (PORT / "boards/e900-dual-boot.src.in").read_text().splitlines():
        stripped, indent = line.strip(), line[:len(line) - len(line.lstrip())]
        if stripped.startswith("@CHECKPOINT "):
            _, phase, label = stripped.strip("@").split()
            filename = f"E9D{len(stages):03d}.BIN"
            text = f"checkpoint={label}\nnonce={nonce}\n".encode()
            payload = prefix(phase) + text
            payload += b" " * (511 - len(payload)) + b"\n"
            (destination / filename).write_bytes(payload)
            stages.append(dict(file=filename, phase=phase, label=label, sha256=hashlib.sha256(payload).hexdigest()))
            output += guard(filename, "E9LOG.TXT", log_slot["lba"], indent)
        elif stripped == "@MMU_PROOF@":
            output += guard("E9MPASS.BIN", "E9MMU.TXT", mmu_slot["lba"], indent)
        else:
            output.append(line)
    script_text = "\n".join(output) + "\n"
    assert "@" not in script_text and len(script_text) < 65536
    assert all(term not in script_text for term in ["saveenv", "defenv", "mmc write", "store write"])
    (destination / "dual-boot.src").write_text(script_text)
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 MMU and PID1 checkpoints", "-d", str(destination / "dual-boot.src"), str(script)], check=True)
    usb.check_script(script, script_text.encode())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    report = dict(log_slot=log_slot, mmu_slot=mmu_slot, nonce=nonce, stages=stages,
                  mmu_hook=hook, mmu_stub=scratch, mmu_stub_bytes=len(stub),
                  mmu_image_sha256=hashlib.sha256(image).hexdigest(),
                  original_image_sha256=trace.PINNED_IMAGE, user_initrd_sha256=usb.sha256(user_initrd),
                  original_cpio_sha256=trace.PINNED_INITRD,
                  original_cpio_entries_preserved=True, script_sha256=usb.sha256(script),
                  hardware_tested=False)
    (destination / "dual-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared MMU + userspace test; scripts NOT deployed:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kit", type=pathlib.Path)
    parser.add_argument("verified_slot", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--adb-serial", required=True)
    parser.add_argument("--mkimage", required=True, type=pathlib.Path)
    parser.add_argument("--clang", default="clang")
    args = parser.parse_args()
    prepare(args.kit, args.verified_slot, args.destination, args.adb_serial, args.mkimage, args.clang)
