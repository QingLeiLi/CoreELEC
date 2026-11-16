#!/usr/bin/env python3
"""Validate the compiled experimental board DTB without executing device code."""
import hashlib
import json
import pathlib
import struct
import sys

BOARD = "gxlx2_p291_1g_e900v21c"


def read_fdt(data):
    header = struct.unpack_from(">10I", data)
    magic, total, structure, strings_offset = header[:4]
    assert magic == 0xd00dfeed and total <= len(data)
    strings = data[strings_offset:strings_offset + header[8]]
    end = structure + header[9]
    assert end <= total
    pos, stack, nodes = structure, [], {}
    while pos < end:
        token = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if token == 1:
            zero = data.index(0, pos, end)
            stack.append(data[pos:zero].decode())
            pos = (zero + 4) & ~3
            nodes["/" + "/".join(stack[1:])] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, offset = struct.unpack_from(">II", data, pos)
            pos += 8
            assert pos + size <= end
            name = strings[offset:strings.index(0, offset)].decode()
            nodes["/" + "/".join(stack[1:])][name] = data[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 9:
            assert not stack
            return nodes
        else:
            assert token == 4
    raise ValueError("Missing FDT_END")


def cells(value):
    assert len(value) % 4 == 0
    return list(struct.unpack(">" + "I" * (len(value) // 4), value))


def find_board(repo):
    patterns = [f"build.*/build/linux-*/arch/arm64/boot/dts/amlogic/coreelec-gxl/{BOARD}.dtb",
                f"build.*/install_pkg/linux-*/usr/share/bootloader/device_trees/{BOARD}.dtb"]
    candidates = [path for pattern in patterns for path in repo.glob(pattern)]
    if not candidates:
        raise RuntimeError("The E900 board DTB was not built or installed")
    if len({hashlib.sha256(path.read_bytes()).hexdigest() for path in candidates}) != 1:
        raise RuntimeError("Built and installed E900 DTBs differ")
    return candidates[0]


def validate(path):
    data = path.read_bytes()
    nodes = read_fdt(data)
    assert nodes["/"]["coreelec-dt-id"] == (BOARD + "\0").encode()
    assert nodes["/"]["amlogic-dt-id"] == b"gxlx2_p291_1g\0"
    assert b"amlogic,gxlx2\0" in nodes["/"]["compatible"]
    assert b"amlogic, Gxl\0" in nodes["/"]["compatible"]
    assert nodes["/cpu_ver_name"]["compatible"] == b"amlogic, cpu-major-id-gxlx2\0"
    assert cells(nodes["/memory@00000000"]["linux,usable-memory"]) == [0, 0x100000, 0, 0x3ff00000]
    secure = nodes["/reserved-memory/firmware_secmon@10000000"]
    assert cells(secure["reg"]) == [0, 0x10000000, 0, 0x200000]
    assert "no-map" in secure and "reusable" not in secure
    cma = nodes["/reserved-memory/linux,secmon"]
    assert cells(cma["size"]) == [0, 0x400000] and "reusable" in cma
    assert cells(cma["alloc-ranges"]) == [0, 0x5000000, 0, 0x400000]
    assert "no-memory" not in nodes["/secmon"]
    framebuffer = nodes["/reserved-memory/linux,meson-fb"]
    assert cells(framebuffer["alloc-ranges"]) == [0, 0x3dc00000, 0, 0x2400000]
    assert nodes["/meson-fb"]["logo_addr"] == b"0x3dc00000\0"
    assert cells(nodes["/usb2phy@d0078000"]["portnum"]) == [2]
    assert cells(nodes["/usb3phy@d0078080"]["portnum"]) == [0]
    for name in ["emmc@d0074000", "sd@d0072000", "sdio@d0070000", "wifi", "bt-dev",
                 "gpioleds", "gpio_keypad", "openvfd"]:
        assert nodes["/" + name]["status"] == b"disabled\0", name
    hdmi = nodes["/amhdmitx"]
    assert cells(hdmi["ic_type"]) == [3] and "amlogic,gxlx2-direct-hdmi" in hdmi
    ethernet = nodes["/ethernet@0xc9410000"]
    assert cells(ethernet["internal_phy"]) == [1] and ethernet["phy-mode"] == b"rmii\0"
    assert ethernet["pinctrl-names"] == b"internal_eth_pins\0"
    assert ethernet["pinctrl-0"] == b"" and "rst_pin-gpios" not in ethernet
    # Fixed secure memory, CMA allocation range and framebuffer must not overlap.
    regions = [(0x10000000, 0x10200000), (0x5000000, 0x5400000), (0x3dc00000, 0x40000000)]
    for index, (start, end) in enumerate(regions):
        for other_start, other_end in regions[index + 1:]:
            assert end <= other_start or other_end <= start
    return dict(board=BOARD, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                checks="passed", hardware_tested=False)


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1]).resolve()
    path = find_board(source) if source.is_dir() else source
    print(json.dumps(dict(path=str(path), **validate(path)), indent=2))
