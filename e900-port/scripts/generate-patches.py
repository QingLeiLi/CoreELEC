#!/usr/bin/env python3
"""Regenerate candidate patches from locally verified upstream source blobs."""
import difflib
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIT = ROOT.parent / "coreelec-audit"
SOURCES = AUDIT / "sources"
MANIFEST = {row["path"]: row for row in json.loads(
    (AUDIT / "source-manifest.json").read_text())}


def original(path):
    data = (SOURCES / path.replace("/", "__")).read_bytes()
    assert hashlib.sha256(data).hexdigest() == MANIFEST[path]["sha256"], path
    return data.decode()


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def patch(name, title, changes):
    parts = [f"Subject: [EXPERIMENTAL] {title}\n\n",
             "Base revisions are fixed in pins.json. Not hardware validated.\n\n"]
    for path, new in changes.items():
        old = original(path)
        assert old != new
        parts.append(f"diff --git a/{path} b/{path}\n")
        parts.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile="a/" + path, tofile="b/" + path))
    dest = ROOT / "patches" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(parts))
    print(dest.relative_to(ROOT))


p = "include/linux/amlogic/cpu_version.h"
s = replace_once(original(p),
                 "#define MESON_CPU_MAJOR_ID_G12B\t\t0x29\n",
                 "#define MESON_CPU_MAJOR_ID_G12B\t\t0x29\n"
                 "#define MESON_CPU_MAJOR_ID_GXLX2\t\t0x2A\n")
s = replace_once(s, "static inline bool is_meson_gxm_cpu(void)\n",
                 "/* GXLX2 is a distinct SoC; do not alias GXL/G12A globally. */\n"
                 "static inline bool is_meson_gxlx2_cpu(void)\n"
                 "{\n\treturn get_cpu_type() == MESON_CPU_MAJOR_ID_GXLX2;\n}\n\n"
                 "static inline bool is_meson_gxm_cpu(void)\n")
patch("linux/0001-gxlx2-identity.patch", "add the real GXLX2 CPU identity", {p: s})

changes = {}
p = "drivers/common/chips/decoder_cpu_ver_info.c"
changes[p] = replace_once(original(p),
    "static const struct of_device_id cpu_ver_of_match[] = {\n",
    "static const struct of_device_id cpu_ver_of_match[] = {\n"
    "\t{\n\t\t.compatible = \"amlogic, cpu-major-id-gxlx2\",\n"
    "\t\t.data = &cpu_ver_info[AM_MESON_CPU_MAJOR_ID_GXLX2 - MAJOR_ID_START],\n\t},\n")
p = "drivers/common/chips/chips.c"
changes[p] = replace_once(original(p),
    '\t{AM_MESON_CPU_MAJOR_ID_GXLX, "gxlx"},\n',
    '\t{AM_MESON_CPU_MAJOR_ID_GXLX, "gxlx"},\n'
    '\t{AM_MESON_CPU_MAJOR_ID_GXLX2, "gxlx2"},\n')
p = "drivers/common/firmware/firmware_drv.c"
s = replace_once(original(p), "int get_firmware_data(unsigned int format, char *buf)\n",
    "/* Trace actual selections, without changing microcode compatibility policy. */\n"
    "static void trace_gxlx2_firmware(const struct fw_info_s *info)\n"
    "{\n\tif (get_cpu_major_id() == AM_MESON_CPU_MAJOR_ID_GXLX2)\n"
    '\t\tpr_info("e900-gxlx2: firmware format=%u name=%s cpu=%s source=%s\\n",\n'
    "\t\t\tinfo->format, info->name, info->data->head.cpu,\n"
    "\t\t\tinfo->src_from);\n}\n\n"
    "int get_firmware_data(unsigned int format, char *buf)\n")
needle = "\t\tdata_len = info->data->head.data_size;\n"
assert s.count(needle) == 2
s = s.replace(needle, "\t\ttrace_gxlx2_firmware(info);\n" + needle)
changes[p] = s
patch("media/0001-gxlx2-identity-and-firmware-trace.patch",
      "match GXLX2 explicitly and trace selected decode firmware", changes)

changes = {}
p = "include/linux/amlogic/media/vout/hdmi_tx/hdmi_tx_module.h"
changes[p] = replace_once(original(p), "\tint chip_type;\n",
    "\tint chip_type;\n"
    "\t/* Experimental direct HDMI access with the existing GXL PHY profile. */\n"
    "\tbool gxlx2_direct_hdmi;\n")
p = "drivers/amlogic/media/vout/hdmitx/hdmi_tx_20/hdmi_tx_main.c"
s = replace_once(original(p),
    '\t\tret = of_property_read_u32(pdev->dev.of_node, "ic_type",\n'
    '\t\t\t&(hdmitx_device.chip_type));\n',
    '\t\tret = of_property_read_u32(pdev->dev.of_node, "ic_type",\n'
    '\t\t\t&(hdmitx_device.chip_type));\n'
    '\t\thdmitx_device.gxlx2_direct_hdmi = of_property_read_bool(\n'
    '\t\t\tpdev->dev.of_node, "amlogic,gxlx2-direct-hdmi");\n')
s = replace_once(s, "\tret = amhdmitx_get_dt_info(pdev);\n",
    "\tret = amhdmitx_get_dt_info(pdev);\n"
    "\tif (hdmitx_device.gxlx2_direct_hdmi) {\n"
    "\t\tif (!is_meson_gxlx2_cpu() ||\n"
    "\t\t    hdmitx_device.chip_type != MESON_CPU_ID_GXL) {\n"
    '\t\t\tdev_err(&pdev->dev, "GXLX2 direct HDMI requires SoC 0x2a and ic_type 3\\n");\n'
    "\t\t\treturn -EINVAL;\n\t\t}\n"
    '\t\tdev_warn(&pdev->dev, "experimental GXLX2 HDMI register transport; GXL PHY retained\\n");\n'
    "\t}\n")
changes[p] = s
p = "drivers/amlogic/media/vout/hdmitx/hdmi_tx_20/hw/reg_ops.c"
s = replace_once(original(p), "#include <linux/io.h>\n",
                 "#include <linux/io.h>\n#include <linux/string.h>\n")
s = replace_once(s, "struct reg_map *map;\n",
    "/* GXL buses/PHY, but separate direct DWC and TOP register windows. */\n"
    "static struct reg_map reg_maps_gxlx2[ARRAY_SIZE(reg_maps_def)];\n\n"
    "struct reg_map *map;\n")
s = replace_once(s, "\tfor (i = 0; map[i].phy_addr != REG_ADDR_END; i++) {\n",
    "\tif (get_hdmitx_device()->gxlx2_direct_hdmi) {\n"
    "\t\tmemcpy(reg_maps_gxlx2, reg_maps_def, sizeof(reg_maps_def));\n"
    "\t\treg_maps_gxlx2[HDMITX_SEC_REG_IDX].phy_addr = 0xda800000;\n"
    "\t\treg_maps_gxlx2[HDMITX_SEC_REG_IDX].size = 0x8000;\n"
    "\t\treg_maps_gxlx2[HDMITX_REG_IDX].phy_addr = 0xda808000;\n"
    "\t\treg_maps_gxlx2[HDMITX_REG_IDX].size = 0x4000;\n"
    "\t\tmap = reg_maps_gxlx2;\n\t}\n"
    "\tfor (i = 0; map[i].phy_addr != REG_ADDR_END; i++) {\n")
needle = "\tif (hdev->chip_type >= MESON_CPU_ID_G12A)\n"
assert s.count(needle) == 2
s = s.replace(needle,
    "\tif (hdev->gxlx2_direct_hdmi || hdev->chip_type >= MESON_CPU_ID_G12A)\n")
changes[p] = s
patch("linux/0002-gxlx2-opt-in-hdmi-transport.patch",
      "add opt-in GXLX2 direct register transport, preserve GXL PHY", changes)

p = "drivers/common/media_clock/clk/clkg12.c"
s = replace_once(original(p), "\tAM_MESON_CPU_MAJOR_ID_GXLX,\\\n",
    "\tAM_MESON_CPU_MAJOR_ID_GXLX,\\\n\tAM_MESON_CPU_MAJOR_ID_GXLX2,\\\n")
patch("media/0002-gxlx2-experimental-clock-registration.patch",
      "register shared decode clocks for GXLX2 (capability audit pending)", {p: s})
