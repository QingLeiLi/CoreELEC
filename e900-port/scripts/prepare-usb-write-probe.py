#!/usr/bin/env python3
"""Allocate one evidence file and bind a guarded write probe to its data sector.

Uses normal filesystem writes through ADB to create the file. Raw disk access
on the host is read-only. The generated bootloader script writes exactly one
sector, only after comparing its existing bytes with the FAT-loaded file.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import pathlib
import secrets
import shutil
import struct
import subprocess

PORT = pathlib.Path(__file__).resolve().parents[1]


class FatDisk:
    def __init__(self, read):
        self.read = read
        mbr = read(0, 1)
        assert mbr[510:512] == b"\x55\xaa"
        self.part, self.length = struct.unpack_from("<II", mbr, 454)
        assert self.part > 0 and self.length > 0
        bpb = read(self.part, 1)
        assert bpb[510:512] == b"\x55\xaa"
        assert struct.unpack_from("<H", bpb, 11)[0] == 512
        self.spc, self.fats = bpb[13], bpb[16]
        assert self.spc and self.spc & (self.spc - 1) == 0 and self.fats in {1, 2}
        self.reserved, self.root_entries = struct.unpack_from("<H", bpb, 14)[0], struct.unpack_from("<H", bpb, 17)[0]
        total = struct.unpack_from("<H", bpb, 19)[0] or struct.unpack_from("<I", bpb, 32)[0]
        assert 0 < total <= self.length
        self.fat_size = struct.unpack_from("<H", bpb, 22)[0] or struct.unpack_from("<I", bpb, 36)[0]
        root_sectors = (self.root_entries * 32 + 511) // 512
        self.root_lba = self.part + self.reserved + self.fats * self.fat_size
        self.data = self.root_lba + root_sectors
        self.clusters = (total - (self.data - self.part)) // self.spc
        assert self.clusters >= 4085, "FAT12 not supported"
        self.bits = 32 if self.clusters >= 65525 else 16
        assert self.fat_size * 512 * 8 // self.bits >= self.clusters + 2
        self.root_sectors = root_sectors
        self.root_cluster = struct.unpack_from("<I", bpb, 44)[0] if self.bits == 32 else None
        self.volume_id = struct.unpack_from("<I", bpb, 67 if self.bits == 32 else 39)[0]

    def cluster_lba(self, cluster):
        assert 2 <= cluster < self.clusters + 2
        return self.data + (cluster - 2) * self.spc

    def next_cluster(self, cluster):
        width = self.bits // 8
        offset = cluster * width
        sector = self.read(self.part + self.reserved + offset // 512, 1)
        return int.from_bytes(sector[offset % 512:offset % 512 + width], "little") & (0x0fffffff if width == 4 else 0xffff)

    def eof(self, cluster):
        return cluster >= (0x0ffffff8 if self.bits == 32 else 0xfff8)

    def directory(self):
        if self.bits == 16:
            yield self.read(self.root_lba, self.root_sectors)
            return
        cluster, seen = self.root_cluster, set()
        while not self.eof(cluster):
            assert cluster not in seen and len(seen) < 128
            seen.add(cluster)
            yield self.read(self.cluster_lba(cluster), self.spc)
            cluster = self.next_cluster(cluster)

    def evidence_slot(self, expected):
        assert len(expected) == 512
        entries = []
        finished = False
        for chunk in self.directory():
            for offset in range(0, len(chunk), 32):
                entry = chunk[offset:offset + 32]
                if entry[0] == 0:
                    finished = True
                    break
                if entry[0] == 0xe5 or entry[11] & 0x18 or entry[11] == 0x0f:
                    continue
                if entry[:11] == b"E9LOG   TXT":
                    entries.append(entry)
            if finished:
                break
        assert len(entries) == 1, "Evidence file is missing or ambiguous"
        entry = entries[0]
        assert struct.unpack_from("<I", entry, 28)[0] == 512
        cluster = struct.unpack_from("<H", entry, 26)[0]
        if self.bits == 32:
            cluster |= struct.unpack_from("<H", entry, 20)[0] << 16
        assert self.eof(self.next_cluster(cluster)), "Evidence must occupy exactly one cluster"
        lba = self.cluster_lba(cluster)
        assert self.data <= lba < self.part + self.length
        assert self.read(lba, 1) == expected, "Raw data does not match the allocated evidence file"
        return dict(lba=lba, cluster=cluster, partition_start=self.part,
                    partition_sectors=self.length, fat_bits=self.bits, volume_id=self.volume_id,
                    file="E9LOG.TXT", file_bytes=512, write_sectors=1)


def prepare(serial, destination, mkimage):
    assert not destination.exists()
    destination.mkdir(parents=True)
    nonce = secrets.token_hex(16)

    def sector(text):
        value = (text + " nonce=" + nonce + "\n").encode()
        assert len(value) < 512
        return value + b" " * (511 - len(value)) + b"\n"

    initial = sector("E900 evidence: USB bootloader write NOT OBSERVED")
    after = sector("E900 evidence: USB bootloader sector write VERIFIED; no CE kernel executed")
    (destination / "E9LOG.TXT").write_bytes(initial)
    (destination / "E9NEXT.BIN").write_bytes(after)
    adb = ["adb", "-s", serial]
    subprocess.run(adb + ["push", str(destination / "E9LOG.TXT"), str(destination / "E9NEXT.BIN"),
                          "/storage/external_storage/sda1/"], check=True)
    subprocess.run(adb + ["shell", "sync"], check=True)

    def read(lba, count):
        assert isinstance(lba, int) and lba >= 0 and 0 < count <= 256
        result = subprocess.run(adb + ["shell", f"busybox dd if=/dev/block/sda bs=512 skip={lba} count={count} 2>/dev/null | busybox base64"],
                                capture_output=True, check=True, timeout=25)
        data = base64.b64decode(b"".join(result.stdout.split()), validate=True)
        assert len(data) == count * 512
        return data

    slot = FatDisk(read).evidence_slot(initial)
    slot.update(nonce=nonce, initial_sha256=hashlib.sha256(initial).hexdigest(),
                after_sha256=hashlib.sha256(after).hexdigest(), hardware_write_tested=False)
    (destination / "slot.json").write_text(json.dumps(slot, indent=2) + "\n")
    source = (PORT / "boards/e900-usb-write-probe.src.in").read_text().replace("@LBA@", hex(slot["lba"]))
    assert "@" not in source
    (destination / "probe.src").write_text(source)
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 guarded USB file test", "-d", str(destination / "probe.src"), str(script)], check=True)
    spec = importlib.util.spec_from_file_location("usb_write_format", PORT / "scripts/prepare-usb-image.py")
    usb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usb)
    usb.check_script(script, source.encode())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    print("Prepared guarded evidence probe; scripts NOT deployed:", destination)
    print("File data sector:", slot["lba"], "FAT", slot["fat_bits"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb-serial", required=True)
    parser.add_argument("--mkimage", type=pathlib.Path, required=True)
    parser.add_argument("destination", type=pathlib.Path)
    args = parser.parse_args()
    prepare(args.adb_serial, args.destination.resolve(), args.mkimage.resolve())
