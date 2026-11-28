#!/usr/bin/env python3
"""Run the pinned module installer and actual optional-wake C branches on host.

No radio or ARM execution; source-built kernel/modules and hardware remain pending.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get('E900_CE_REFERENCE', PORT/'reference/CoreELEC'))
AUDIT = Path(os.environ.get('E900_AUDIT_ROOT', PORT.parent/'coreelec-audit'))
spec = importlib.util.spec_from_file_location('wireless_installer', PORT/'scripts/install-patches.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
relative = 'projects/Amlogic-ce/packages/linux-drivers/amlogic/uwe5631-aml/package.mk'
modules = ['uwe5621_bsp_sdio', 'sprdwl_ng', 'sprdbt_tty']
with tempfile.TemporaryDirectory(prefix='e900-wireless-') as temporary:
    root = Path(temporary)
    recipe = root/relative
    recipe.parent.mkdir(parents=True)
    shutil.copy2(REFERENCE/relative, recipe)
    _, content, metadata = installer.uwe_module_install_fix(root)
    recipe.write_text(content)
    assert installer.uwe_module_install_fix(root)[1] == content
    assert 'c9621e32c743ed37bdb54a60f8aa8b329b4bb56f' in content
    build = root/'.e900-work/build/unisoc'
    for directory, name in zip(['BSP', 'WIFI', 'BT/tty-sdio'], modules):
        path = build/directory/(name+'.ko')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('test '+name).encode())
    hidden = build/'.tmp_versions'
    hidden.mkdir()
    (hidden/'hidden.ko').write_bytes(b'not a module')
    for path in ['BSP/fw/wcnmodem.bin', 'BT/libbt/conf/sprd/runtime/bt_configure_pskey.ini',
                 'BT/libbt/conf/sprd/runtime/bt_configure_rf.ini']:
        target = build/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'synthetic firmware test fixture')
    package = recipe.parent
    (package/'firmware').mkdir()
    (package/'firmware/wifi_56630001_3ant.ini').write_bytes(b'synthetic wifi config')
    program = '''source "$1"
PKG_BUILD="$2"
INSTALL="$3"
PKG_DIR="$4"
get_full_module_dir() { echo lib/modules/test; }
get_kernel_overlay_dir() { echo usr/lib/kernel-overlays/base; }
makeinstall_target
'''
    def install(destination):
        return subprocess.run(['bash', '-e', '-c', program, 'test', str(recipe),
                               str(build), str(destination), str(package)], capture_output=True, text=True)
    dest = root/'installed'
    result = install(dest)
    assert result.returncode == 0, result.stderr
    actual = dest/'lib/modules/test/uwe5631-aml'
    assert {p.name for p in actual.iterdir()} == {name+'.ko' for name in modules}
    firmware = dest/'usr/lib/kernel-overlays/base/lib/firmware/unisoc'
    assert {p.name for p in firmware.iterdir()} == {
        'wifi_56630001_3ant.ini', 'wcnmodem.bin', 'bt_configure_pskey.ini', 'bt_configure_rf.ini'}
    for name, directory in zip(modules, ['BSP', 'WIFI', 'BT/tty-sdio']):
        path = build/directory/(name+'.ko')
        data = path.read_bytes()
        path.unlink()
        result = install(root/('missing-'+name))
        assert result.returncode != 0 and 'Missing Unisoc module: '+name+'.ko' in result.stderr
        path.write_bytes(data)
    original = recipe.read_text()
    recipe.write_text(original+'\n# unmanaged edit\n')
    try:
        installer.uwe_module_install_fix(root)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Accepted local source recipe drift')
    state = dict(pins=installer.PINS, profile='decoder', host_codegen={}, patches=[],
                 build_options=None, package_install_fixes=[])
    new = dict(state, package_install_fixes=[metadata])
    assert installer.invalidated_packages(state, new) == ['uwe5631-aml']
    changed = dict(new, patches=[dict(source='linux/test.patch', sha256='test')])
    assert installer.invalidated_packages(new, changed) == ['linux', 'media_modules-aml', 'uwe5631-aml']
    print('PASS: real Unisoc installer below hidden build root installs 3 modules/4 firmware files; rejects missing modules and recipe edits')
    print('PASS: driver migration preserves toolchain; subsequent kernel changes rebuild Unisoc modules too')

    relative = 'drivers/amlogic/bluetooth/bt_device.c'
    row = next(r for r in json.loads((PORT/'tests/source-fixtures.json').read_text()) if r['path'] == relative)
    source = (AUDIT/'sources'/relative.replace('/', '__')).read_bytes()
    assert hashlib.sha256(source).hexdigest() == row['sha256']
    target = root/relative
    target.parent.mkdir(parents=True)
    target.write_bytes(source)
    subprocess.run(['git', 'apply', str(PORT/'patches/linux/0047-aml-bt-optional-host-wake.patch')], cwd=root, check=True)
    patched = target.read_text()
    probe = patched[patched.index('\tpdata->irqno_wakeup = -1;'):patched.index('\n\tINIT_WORK', patched.index('static int bt_probe'))]
    suspend = patched[patched.index('\tif (pdata->irqno_wakeup >= 0)'):patched.index('\n\treturn 0;', patched.index('static int bt_suspend'))]
    start = patched.index('\tif (pdata->irqno_wakeup >= 0)', patched.index('static int bt_resume'))
    resume = patched[start:patched.index('\n\tbtwake_evt = 0;', start)]
    c = root/'wake.c'
    c.write_text('''#include <assert.h>
#include <stdbool.h>
#define IRQF_TRIGGER_FALLING 1
#define pr_err(...) ((void)0)
#define bt_interrupt 0
struct bt_dev_data { int irqno_wakeup; int gpio_btwakeup; };
struct platform_device { int dev; };
static int requested, wake, disabled, enabled, fail, mapping;
static int gpio_to_irq(int gpio) { assert(gpio > 0); return mapping; }
static int request_irq(int irq, int handler, int flags, const char *name, void *data) {
 (void)handler; (void)flags; (void)name; (void)data; assert(irq >= 0); requested++; return fail;
}
static int device_init_wakeup(int *dev, int value) { (void)dev; (void)value; return 0; }
static int dev_pm_set_wake_irq(int *dev, int irq) { (void)dev; assert(irq >= 0); wake++; return 0; }
static void disable_irq(int irq) { assert(irq >= 0); disabled++; }
static void enable_irq(int irq) { assert(irq >= 0); enabled++; }
static void run(int gpio, int failure) {
 struct bt_dev_data data = {0, gpio}, *pdata = &data;
 struct platform_device device, *pdev = &device;
 int ret = 0;
 requested = wake = disabled = enabled = 0; fail = failure;
''' + probe + '\n' + suspend + '\n' + resume + '''
 if (!gpio || mapping < 0) {
  assert(!requested && !wake && !disabled && !enabled && pdata->irqno_wakeup == -1);
 } else if (failure) {
  assert(requested == 1 && !wake && !disabled && !enabled && pdata->irqno_wakeup == -1);
 } else {
  assert(requested == 1 && wake == 1 && disabled == 1 && enabled == 1);
 }
}
int main(void) {
 mapping = 123; run(0, 0); run(42, 0); run(42, -1);
 mapping = -6; run(42, 0);
 return 0;
}
''')
    subprocess.run([shutil.which('clang') or 'cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(root/'wake')], check=True)
    subprocess.run([str(root/'wake')], check=True)
    print('PASS: actual optional-wake probe/PM branches handle absent/present GPIO, IRQ mapping and request failures')
print('PENDING: full ARM kernel/module build, SDIO/firmware bring-up, Wi-Fi scan/connect and Bluetooth pair/audio')
