#!/usr/bin/env python3
"""Host checks only: patch application, CPU identity, HDMI routing, installer guards."""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = pathlib.Path(os.environ.get("E900_AUDIT_ROOT", ROOT.parent / "coreelec-audit"))
REFERENCE = pathlib.Path(os.environ.get("E900_CE_REFERENCE", ROOT / "reference/CoreELEC"))


def run(args, cwd):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def function(source, name):
    match = re.search(r"^(?:unsigned int|void) " + name + r"\([^;]*?\)\n\{", source, re.M)
    assert match, name
    start = source.index("{", match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + "\n"


with tempfile.TemporaryDirectory(prefix="e900-port-check-") as directory:
    work = pathlib.Path(directory)
    fixtures = {}
    for row in json.loads((AUDIT / "source-manifest.json").read_text()):
        if row["path"] == "firmware/video_ucode.bin":
            continue
        package = "linux" if row["repo"].endswith("linux-amlogic") else "media"
        dest = work / package / row["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        source = AUDIT / "sources" / row["path"].replace("/", "__")
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row["sha256"]
        shutil.copy2(source, dest)
        fixtures[package] = work / package
    for package in ["linux", "media"]:
        # Isolate fixture roots even when CI's temp path is inside a checkout.
        run(["git", "init", "--quiet"], fixtures[package])
        for patch in sorted((ROOT / "patches" / package).glob("*.patch")):
            run(["git", "apply", "--check", patch], fixtures[package])
            run(["git", "apply", patch], fixtures[package])
    print("PASS: five patches apply sequentially to verified pinned source files")

    compiler = shutil.which("clang") or shutil.which("cc")
    assert compiler, "A host C compiler is needed"
    cpu_header = fixtures["linux"] / "include/linux/amlogic/cpu_version.h"
    cpu_test = work / "cpu-test.c"
    cpu_test.write_text('''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t u32;
#define CONFIG_AMLOGIC_CPU_VERSION 1
''' + '#include "' + str(cpu_header) + '"\n' + '''
static int cpu;
int get_meson_cpu_version(int level) { (void)level; return cpu; }
int main(void) {
    cpu = 0x2a;
    assert(is_meson_gxlx2_cpu());
    assert(!is_meson_gxl_cpu() && !is_meson_g12a_cpu());
    cpu = 0x21;
    assert(is_meson_gxl_cpu() && !is_meson_gxlx2_cpu());
    cpu = 0x28;
    assert(is_meson_g12a_cpu() && !is_meson_gxlx2_cpu());
    return 0;
}
''')
    run([compiler, "-std=c99", "-Wall", "-Werror", cpu_test, "-o", work / "cpu-test"], work)
    run([work / "cpu-test"], work)
    print("PASS: real patched CPU header distinguishes GXLX2, GXL and G12A")

    source = (fixtures["linux"] / "drivers/amlogic/media/vout/hdmitx/hdmi_tx_20/hw/reg_ops.c").read_text()
    maps = source[source.index("/* For gxb/gxl/gxm */"):source.index("unsigned int TO_PHY_ADDR")]
    indices = sorted(set(re.findall(r"\b[A-Z_]+_REG_IDX\b", maps))) + ["REG_IDX_END"]
    header = (fixtures["linux"] / "include/linux/amlogic/media/vout/hdmi_tx/hdmi_tx_module.h").read_text()
    cpu_defines = "\n".join(re.findall(r"^#define MESON_CPU_ID_.*$", header, re.M))
    test = '''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define REG_ADDR_END 0xffffffffU
#define pr_info(...) ((void)0)
struct reg_map { unsigned int phy_addr, size; void *p; };
struct hdmitx_dev { int chip_type; bool gxlx2_direct_hdmi; };
static struct hdmitx_dev device;
struct hdmitx_dev *get_hdmitx_device(void) { return &device; }
void *ioremap(unsigned int addr, unsigned int size) { (void)size; return (void *)(uintptr_t)addr; }
static unsigned int route;
unsigned int hdmitx_rd_reg_g12a(unsigned int a) { (void)a; return 12; }
unsigned int hdmitx_rd_reg_old(unsigned int a) { (void)a; return 3; }
unsigned int hdmitx_rd_reg_normal(unsigned int a) { (void)a; return 0; }
void hdmitx_wr_reg_g12a(unsigned int a, unsigned int d) { (void)a; (void)d; route = 12; }
void hdmitx_wr_reg_old(unsigned int a, unsigned int d) { (void)a; (void)d; route = 3; }
void hdmitx_wr_reg_normal(unsigned int a, unsigned int d) { (void)a; (void)d; route = 0; }
'''
    test += "enum { " + ", ".join(indices) + " };\n" + cpu_defines + "\n"
    test += maps + function(source, "hdmitx_rd_reg") + function(source, "hdmitx_wr_reg")
    test += '''int main(void) {
    device.chip_type = MESON_CPU_ID_GXL;
    init_reg_map(device.chip_type);
    assert(map == reg_maps_def);
    assert(map[HDMITX_REG_IDX].phy_addr == 0xc883a000);
    assert(hdmitx_rd_reg(0) == 3);
    hdmitx_wr_reg(0, 0); assert(route == 3);
    device.gxlx2_direct_hdmi = true;
    init_reg_map(device.chip_type);
    assert(map == reg_maps_gxlx2);
    assert(device.chip_type == MESON_CPU_ID_GXL);
    assert(map[HDMITX_SEC_REG_IDX].phy_addr == 0xda800000);
    assert(map[HDMITX_SEC_REG_IDX].size == 0x8000);
    assert(map[HDMITX_REG_IDX].phy_addr == 0xda808000);
    assert(map[HDMITX_REG_IDX].size == 0x4000);
    assert(map[HHI_REG_IDX].phy_addr == 0xc883c000);
    assert(map[VCBUS_REG_IDX].phy_addr == 0xd0100000);
    assert(hdmitx_rd_reg(0) == 12);
    hdmitx_wr_reg(0, 0); assert(route == 12);
    device.gxlx2_direct_hdmi = false;
    init_reg_map(device.chip_type);
    assert(map == reg_maps_def);
    assert(map[HDMITX_REG_IDX].phy_addr == 0xc883a000);
    assert(hdmitx_rd_reg(0) == 3);
    device.chip_type = MESON_CPU_ID_G12A;
    init_reg_map(device.chip_type);
    assert(map == reg_maps_g12a);
    assert(map[HDMITX_REG_IDX].phy_addr == 0xff608000);
    assert(hdmitx_rd_reg(0) == 12);
    hdmitx_wr_reg(0, 0); assert(route == 12);
    device.chip_type = MESON_CPU_ID_GXM;
    assert(hdmitx_rd_reg(0) == 0);
    hdmitx_wr_reg(0, 0); assert(route == 0);
    return 0;
}
'''
    (work / "hdmi-test.c").write_text(test)
    run([compiler, "-std=c99", "-Wall", "-Werror", work / "hdmi-test.c", "-o", work / "hdmi-test"], work)
    run([work / "hdmi-test"], work)
    print("PASS: extracted patched HDMI map/dispatch preserves GXL buses and existing routes")

    spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install-patches.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    checkout = work / "CoreELEC"
    for relative in ["projects/Amlogic-ce/packages/linux/package.mk",
                     "projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk",
                     "packages/sysutils/keyutils/package.mk",
                     "packages/sysutils/usbutils/package.mk",
                     "packages/network/connman/package.mk"]:
        dest = checkout / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REFERENCE / relative, dest)
    with mock.patch.object(installer.subprocess, "check_output", return_value=installer.PINS["coreelec"]):
        installer.install(checkout, "identify")
        installer.install(checkout, "identify")
        keyutils = (checkout / "packages/sysutils/keyutils/package.mk").read_text()
        assert 'PKG_URL="https://deb.debian.org/debian/pool/main/k/keyutils/keyutils_${PKG_VERSION}.orig.tar.gz"' in keyutils
        assert keyutils.count('PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.gz"') == 1
        assert 'PKG_SHA256="a61d5706136ae4c05bd48f86186bcfdbd88dd8bd5107e3e195c924cfc1b39bb4"' in keyutils
        usbutils = (checkout / "packages/sysutils/usbutils/package.mk").read_text()
        assert 'PKG_URL="https://mirrors.edge.kernel.org/pub/linux/utils/usb/usbutils/${PKG_NAME}-${PKG_VERSION}.tar.xz"' in usbutils
        assert usbutils.count('PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.xz"') == 1
        assert 'PKG_SHA256="a6a25ffdcf9103e38d7a44732aca17073f4e602b92e4ae55625231a82702e05b"' in usbutils
        connman = (checkout / "packages/network/connman/package.mk").read_text()
        assert 'PKG_VERSION="1.43"' in connman
        assert 'PKG_SHA256="b8f5ab5d109d033edebe5b0564d20c9b7b9546a607195cdadc6754eb328b6f6e"' in connman
        assert connman.count('PKG_SOURCE_NAME="connman-${PKG_VERSION}-release.tar.gz"') == 1
        marker = json.loads((checkout / ".e900-profile.json").read_text())
        managed = checkout / marker["patches"][0]["destination"]
        managed.write_text(managed.read_text() + "\nlocal user edit\n")
        try:
            installer.install(checkout, "identify")
        except RuntimeError as exc:
            assert "Local patch edits" in str(exc)
        else:
            raise AssertionError("User edits were silently overwritten")
    with mock.patch.object(installer.subprocess, "check_output", return_value="wrong-revision"):
        try:
            installer.install(checkout, "identify")
        except RuntimeError as exc:
            assert "unpinned" in str(exc)
        else:
            raise AssertionError("Unpinned checkout accepted")
    print("PASS: installer is repeatable and refuses local edits/unpinned revisions")
    # Separate checkout: exercise actual decoder board overlay and user edit guard.
    decoder = work / "decoder"
    shutil.copytree(checkout, decoder)
    (decoder / ".e900-profile.json").unlink()
    for patch in decoder.rglob("9000-e900-*.patch"):
        patch.unlink()
    with mock.patch.object(installer.subprocess, "check_output", return_value=installer.PINS["coreelec"]):
        installer.install(decoder, "decoder")
        installer.install(decoder, "decoder")
        state = json.loads((decoder / ".e900-profile.json").read_text())
        assert state["board_dtb"] == "gxlx2_p291_1g_e900v21c" and len(state["patches"]) == 5
        options = decoder / ".coreelec/options"
        assert options.read_bytes() == (ROOT / "boards/usb-build.options").read_bytes()
        options.write_text(options.read_text() + "# user edit\n")
        try:
            installer.install(decoder, "decoder")
        except RuntimeError as exc:
            assert "locally edited" in str(exc)
        else:
            raise AssertionError("Local board option edits were overwritten")
    print("PASS: decoder installs board patch/options and protects local options")
    bad_source = checkout / "packages/sysutils/keyutils/package.mk"
    bad_source.write_text(bad_source.read_text().replace('PKG_VERSION="1.6.3"', 'PKG_VERSION="0.0"'))
    try:
        installer.keyutils_download_fix(checkout)
    except RuntimeError as exc:
        assert "version or checksum" in str(exc)
    else:
        raise AssertionError("Download override accepted an unexpected source version")
    print("PASS: keyutils mirror keeps the pinned checksum/cache filename and rejects version drift")
    usbutils_path = checkout / "packages/sysutils/usbutils/package.mk"
    saved_usbutils = usbutils_path.read_text()
    for content, message in [
        (saved_usbutils.replace('PKG_VERSION="017"', 'PKG_VERSION="018"'), "version or checksum"),
        (saved_usbutils.replace('PKG_SHA256="a6', 'PKG_SHA256="b6'), "version or checksum"),
        (saved_usbutils.replace("https://mirrors.edge.kernel.org/", "https://example.invalid/"), "URL"),
        (saved_usbutils.replace('PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.xz"',
                               'PKG_SOURCE_NAME="changed.tar.xz"'), "filename"),
    ]:
        usbutils_path.write_text(content)
        try:
            installer.usbutils_download_fix(checkout)
        except RuntimeError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("usbutils override accepted source drift")
    usbutils_path.write_text(saved_usbutils)
    print("PASS: usbutils mirror keeps the pinned checksum/cache filename and rejects source drift")
    connman_path = checkout / "packages/network/connman/package.mk"
    saved_connman = connman_path.read_text()
    for content in [
        saved_connman.replace('PKG_VERSION="1.43"', 'PKG_VERSION="1.44"'),
        saved_connman.replace('PKG_SHA256="b8f', 'PKG_SHA256="c8f'),
        saved_connman.replace('PKG_SOURCE_NAME="connman-${PKG_VERSION}-release.tar.gz"',
                              'PKG_SOURCE_NAME="connman-${PKG_VERSION}.tar.gz"'),
        saved_connman.replace("https://mirrors.edge.kernel.org/", "https://example.invalid/"),
    ]:
        connman_path.write_text(content)
        try:
            installer.connman_download_fix(checkout)
        except RuntimeError as exc:
            assert "source configuration" in str(exc)
        else:
            raise AssertionError("ConnMan override accepted source drift")
    connman_path.write_text(saved_connman)
    print("PASS: ConnMan release override pins version/checksum and isolates its cache filename")

print("HOST CHECKS PASSED. Full ARM64 kernel/module compilation and hardware tests remain pending.")
