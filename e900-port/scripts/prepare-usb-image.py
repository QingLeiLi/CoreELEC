#!/usr/bin/env python3
"""Prepare a regular-file USB test image; never open a block device or mount it."""
import gzip
import hashlib
import importlib.util
import json
import os
import pathlib
import re
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


def current_image(repo):
    """Use CE's current build identity, never cache order or file timestamps."""
    identities = list(repo.glob("build.*/BUILD_FILENAME"))
    if len(identities) != 1:
        raise ValueError(f"Expected one BUILD_FILENAME, found {len(identities)}")
    name = identities[0].read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name):
        raise ValueError("Invalid BUILD_FILENAME basename")
    image = repo / "target" / (name + "-Generic.img.gz")
    system = repo / "target" / (name + ".system")
    if not image.is_file() or image.is_symlink():
        available = sorted(p.name for p in (repo / "target").glob("*-Generic.img.gz"))
        raise ValueError(f"Current build Generic image missing: {image.name}; available={available}")
    return image, system, name


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


def boot_payloads(container, image):
    """Extract unchanged CE newc initramfs; the vendor bootm container is not booted."""
    data=container.read_bytes()
    if len(data)<608 or data[:8]!=b"ANDROID!":
        raise ValueError("Expected CE Android boot image container")
    kernel_size,_,ramdisk_size,_,second_size,_,_,page=struct.unpack_from("<8I",data,8)
    if page<2048 or page>65536 or page&(page-1) or not kernel_size or not ramdisk_size or second_size:
        raise ValueError("Unsupported Android boot image layout")
    start=page+((kernel_size+page-1)//page)*page
    if start+ramdisk_size>len(data):
        raise ValueError("Truncated Android ramdisk")
    ramdisk=data[start:start+ramdisk_size]
    # Validate every newc entry and a real executable /init without rewriting it.
    pos=0;init=False
    while True:
        if ramdisk[pos:pos+6]!=b"070701" or pos+110>len(ramdisk):
            raise ValueError("Invalid CE newc ramdisk")
        try:
            fields=[int(ramdisk[pos+6+i*8:pos+14+i*8],16) for i in range(13)]
        except ValueError as exc:
            raise ValueError("Invalid CE cpio header") from exc
        size,namesize=fields[6],fields[11]
        if not namesize or pos+110+namesize>len(ramdisk):
            raise ValueError("Truncated CE cpio name")
        name=ramdisk[pos+110:pos+110+namesize]
        if name[-1:]!=b"\0":raise ValueError("Unterminated CE cpio name")
        body=(pos+110+namesize+3)&~3
        if body+size>len(ramdisk):raise ValueError("Truncated CE cpio body")
        if name[:-1] in {b"init",b"./init"}:
            init=(fields[1]&0o170000)==0o100000 and bool(fields[1]&0o111) and size>0
        pos=(body+size+3)&~3
        if name[:-1]==b"TRAILER!!!":break
    if not init:raise ValueError("CE ramdisk lacks executable /init")
    raw=image.read_bytes()
    if len(raw)<64 or raw[56:60]!=b"ARMd":raise ValueError("Invalid raw ARM64 Image")
    text_offset,image_size=struct.unpack_from("<2Q",raw,8)
    if text_offset!=0x1080000 or max(image_size,len(raw))>0x4000000:
        raise ValueError("ARM64 Image does not fit the tested USB boot layout")
    if ramdisk_size>0x3000000:raise ValueError("Initramfs overlaps the USB DTB load address")
    return ramdisk


def check_initrd(path, expected):
    data=path.read_bytes()
    if len(data)<64:raise ValueError("Truncated legacy initrd")
    fields=struct.unpack(">7I4B32s",data[:64]);header=bytearray(data[:64]);header[4:8]=bytes(4)
    if fields[0]!=0x27051956 or zlib.crc32(header)!=fields[1] or fields[7:11]!=(5,22,3,1):
        raise ValueError("Invalid ARM64 gzip legacy initrd header")
    if fields[3]!=len(data)-64 or zlib.crc32(data[64:])!=fields[6]:
        raise ValueError("Invalid legacy initrd payload CRC")
    if gzip.decompress(data[64:])!=expected:raise ValueError("CE initramfs changed during packaging")


def check_media_modules(repo, system):
    roots=list(repo.glob("build.*/build/media_modules-aml-*"))
    if len(roots)!=1:raise ValueError("Expected one built media module tree")
    modules=[p for p in roots[0].rglob("*.ko") if all(not part.startswith('.') for part in p.relative_to(roots[0]).parts)]
    expected={p.name for p in modules}
    if not expected or len(expected)!=len(modules):raise ValueError("Empty or ambiguous built media modules")
    tool=shutil.which("unsquashfs")
    if not tool:raise ValueError("unsquashfs is required to audit SYSTEM media modules")
    listing=subprocess.check_output([tool,"-l",str(system)],text=True)
    actual={pathlib.PurePosixPath(line.strip()).name for line in listing.splitlines()
            if '/media_modules-aml/' in line and line.rstrip().endswith('.ko')}
    if actual!=expected:
        raise ValueError(f"SYSTEM media modules mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    return sorted(actual)


def prepare(repo):
    state = json.loads((repo / ".e900-profile.json").read_text())
    if state["profile"] != "decoder" or state.get("board_dtb") != board.BOARD:
        raise ValueError("USB image requires the decoder board profile")
    marker = repo / ".e900-usb-image.json"
    marker.unlink(missing_ok=True)
    dtb = board.find_board(repo)
    validated = board.validate(dtb)
    source_image, expected_system, build_name = current_image(repo)
    tools = {}
    for name in ["mcopy", "mkimage"]:
        matches = list(repo.glob(f"build.*/toolchain/bin/{name}"))
        if len(matches) != 1:
            raise ValueError(f"Expected one built host tool: {name}")
        tools[name] = str(matches[0])
    script_source = PORT / "boards/e900-usb-image.src"
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
        if not expected_system.is_file() or sha256(system) != sha256(expected_system):
            raise ValueError("USB SYSTEM does not match this build")
        images=list(repo.glob("build.*/build/linux-*/arch/arm64/boot/Image"))
        if len(images)!=1:raise ValueError("Expected one raw ARM64 Image")
        ramdisk=boot_payloads(kernel,images[0])
        packed=temporary/"initrd.gz";packed.write_bytes(gzip.compress(ramdisk,mtime=0))
        initrd=temporary/"e900-uInitrd"
        subprocess.run([tools["mkimage"],"-A","arm64","-O","linux","-T","ramdisk",
                        "-C","gzip","-n","E900 original CE initramfs","-d",str(packed),str(initrd)],check=True)
        check_initrd(initrd,ramdisk)
        media_modules=check_media_modules(repo,system)
        entries={"dtb.img":dtb,"e900-Image":images[0],"e900-uInitrd":initrd,
                 "aml_autoscript":script,"s905_autoscript":script,"cfgload":script}
        readback={}
        for name,source in entries.items():
            subprocess.run([tools["mcopy"],"-i",image_argument,"-o",str(source),"::/"+name],check=True)
            copied=temporary/(name+".readback")
            subprocess.run([tools["mcopy"],"-i",image_argument,"::/"+name,str(copied)],check=True)
            if copied.read_bytes()!=source.read_bytes():raise ValueError(f"FAT readback mismatch: {name}")
            readback[name]=sha256(copied)
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
    metadata = dict(schema=2, run_id=os.environ.get("GITHUB_RUN_ID", "local"),
                    run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
                    build_filename=build_name, source_image=str(source_image.relative_to(repo)),
                    image=str(output.relative_to(repo)), sha256=digest, board=validated,
                    profile_state_sha256=sha256(repo / ".e900-profile.json"),
                    boot_script_sha256=sha256(script_source), fat_readback=readback,
                    boot_method="booti / raw ARM64 Image / original CE initramfs",
                    initramfs_sha256=hashlib.sha256(ramdisk).hexdigest(), media_modules=media_modules,
                    hardware_tested=False, intended_use="external USB test only")
    marker.write_text(json.dumps(metadata, indent=2) + "\n")
    output.with_name(output.name + ".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared and read back USB test image: {output}")
    return metadata


if __name__ == "__main__":
    prepare(pathlib.Path(sys.argv[1]).resolve())
