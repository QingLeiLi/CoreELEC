#!/usr/bin/env python3
"""Compile the real patched DI lookup with stubs to check SoC/error scope."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]
AUDIT = Path(os.environ.get('E900_AUDIT_ROOT', PORT.parent/'coreelec-audit'))
FILE = 'drivers/amlogic/media/deinterlace/deinterlace.c'
with tempfile.TemporaryDirectory(prefix='e900-di-clock-') as tmp:
    root = Path(tmp)
    target = root/FILE
    target.parent.mkdir(parents=True)
    shutil.copy2(AUDIT/'sources'/FILE.replace('/','__'),target)
    subprocess.run(['git','apply',str(PORT/'patches/linux/0005-gxlx2-optional-di-clock.patch')],cwd=root,check=True)
    source = target.read_text()
    start = source.index('static void di_get_vpu_clkb(')
    end = source.index('\nstatic struct div1_meson_data',start)
    function = source[start:end]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#define CLK_TREE_SUPPORT 1
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define pr_err(...) ((void)0)
#define pr_info(...) ((void)0)
struct device { void *of_node; };
struct clk { int value; };
struct di_dev_s { unsigned long clkb_min_rate, clkb_max_rate; struct clk *vpu_clkb; };
static struct clk valid;
static struct clk *lookup;
static bool gxlx2;
static bool is_meson_gxlx2_cpu(void) { return gxlx2; }
static struct clk *clk_get(struct device *dev, const char *name) {
    (void)dev; return name[0] == 'v' && name[4] == 'm' ? &valid : lookup;
}
static int clk_prepare_enable(struct clk *clk) { assert(clk == &valid); return 0; }
static int of_property_read_u32_array(void *node, const char *name, unsigned int *out, int size) {
    (void)node; (void)name; (void)out; (void)size; return -ENOENT;
}
'''
    harness += function + r'''
int main(void) {
    struct device dev = {0}; struct di_dev_s di = {0};
    gxlx2 = true; lookup = (struct clk *)(intptr_t)-ENOENT;
    di_get_vpu_clkb(&dev, &di); assert(di.vpu_clkb == NULL);
    assert(di.clkb_min_rate == 250000000 && di.clkb_max_rate == 500000000);
    lookup = &valid; di_get_vpu_clkb(&dev, &di); assert(di.vpu_clkb == &valid);
    lookup = (struct clk *)(intptr_t)-517; di_get_vpu_clkb(&dev, &di); assert(di.vpu_clkb == lookup);
    gxlx2 = false; lookup = (struct clk *)(intptr_t)-ENOENT;
    di_get_vpu_clkb(&dev, &di); assert(di.vpu_clkb == lookup);
    return 0;
}
'''
    c = root/'test.c'; c.write_text(harness)
    compiler = shutil.which('clang') or shutil.which('cc')
    subprocess.run([compiler,'-std=c99','-Wall','-Werror',str(c),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('PASS: real DI function clears only GXLX2 ENOENT; valid, deferred and other-SoC paths preserved')
