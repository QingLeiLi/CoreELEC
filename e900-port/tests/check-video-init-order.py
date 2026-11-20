#!/usr/bin/env python3
"""Exercise real bus dispatch and init wrappers; hardware init is simulated."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]
AUDIT = Path(os.environ.get('E900_AUDIT_ROOT', PORT.parent / 'coreelec-audit'))
PATHS = [
    'drivers/amlogic/media/video_sink/video.c',
    'drivers/amlogic/media/common/arch/registers/register_ops.c',
    'include/linux/amlogic/media/registers/register_ops.h',
    'include/linux/amlogic/media/utils/vdec_reg.h',
]


def function(source, name):
    match = re.search(r'^(?:static )?(?:bool|int|void)(?: __init)? ' + name
                      + r'\([^;]*?\)\s*\{', source, re.M)
    if not match:
        raise AssertionError('Missing function: ' + name)
    start = source.index('{', match.start())
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end] + '\n'


with tempfile.TemporaryDirectory(prefix='e900-video-init-') as directory:
    root = Path(directory)
    rows = {r['path']: r for r in json.loads((PORT / 'tests/source-fixtures.json').read_text())}
    for path in PATHS:
        data = (AUDIT / 'sources' / path.replace('/', '__')).read_bytes()
        if hashlib.sha256(data).hexdigest() != rows[path]['sha256']:
            raise AssertionError('Fixture mismatch: ' + path)
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    subprocess.run(['git', 'apply', str(PORT / 'patches/linux/0010-gxlx2-late-video-init-probe.patch')],
                   cwd=root, check=True)
    video = (root / PATHS[0]).read_text()
    ops = (root / PATHS[1]).read_text()
    header = (root / PATHS[2]).read_text()
    vdec_header = (root / PATHS[3]).read_text()
    buses = header[header.index('enum\n'):header.index('};') + 2]
    start = header.index('struct chip_register_ops {')
    struct = header[start:header.index('};', start) + 2]
    wrappers = video[video.index('static bool gxlx2_late_video_init;'):
                     video.index('late_initcall_sync(e900_video_init_late);')
                     + len('late_initcall_sync(e900_video_init_late);')]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define __init
#define GFP_KERNEL 0
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define AIU_AIFIFO_CTRL 0
#define AIU_MEM_AIFIFO_MEM_CTL 255
#define CODEC_OPS_START(...) ((void)0)
#define CODEC_OPS_ERROR(...) ((void)0)
#define pr_debug(...) ((void)0)
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
#define module_param_named(...)
#define MODULE_PARM_DESC(...)
#define module_init(f) static int (*early_init)(void) = f
#define late_initcall_sync(f) static int (*late_init)(void) = f
''' + buses + '\n' + struct + r'''
static struct chip_register_ops *amports_ops[BUS_MAX];
static int cpu, init_calls, writes, reads, init_error, allocation_error;
static void *allocation;
static int get_cpu_type(void) { return cpu; }
static bool is_meson_gxlx2_cpu(void) { return cpu == 0x2a; }
static void *kmalloc_array(size_t count, size_t size, int flags) {
    (void)flags;
    if (allocation_error) return NULL;
    allocation = calloc(count, size);
    return allocation;
}
static int fake_read(unsigned int reg) { (void)reg; reads++; return 7; }
static void fake_write(unsigned int reg, unsigned int value) {
    (void)reg; (void)value; writes++;
}
'''
    for name in ['codec_reg_bus_ready', 'codec_reg_read', 'codec_reg_write',
                 'codec_reg_write_bits']:
        harness += function(ops, name)
    # The upstream registration helper contains an intentional empty if-body.
    harness += '#pragma GCC diagnostic push\n#pragma GCC diagnostic ignored "-Wempty-body"\n'
    harness += function(ops, 'register_reg_onebus_ops')
    harness += '#pragma GCC diagnostic pop\n'
    harness += function(ops, 'register_reg_ops_per_cpu')
    macro_start = header.index('#define DEF_BUS_OPS(')
    macro_end = header.index('\n\n/*', macro_start)
    harness += header[macro_start:macro_end] + '\nDEF_BUS_OPS(IO_VC_BUS, vc);\n'
    macro = re.search(r'^#define WRITE_VCBUS_REG\(r, val\)[^\n]+', vdec_header, re.M)
    if not macro:
        raise AssertionError('Missing actual video register macro')
    harness += macro.group() + '\n'
    harness += r'''
static int video_init(void) {
    init_calls++;
    if (init_error) return init_error;
    /* Simulate a probe write through the actual dispatch function. */
    WRITE_VCBUS_REG(0x1d07, 4096);
    return 0;
}
''' + wrappers + r'''
static void reset(int id, bool opt_in) {
    free(allocation); allocation = NULL;
    memset(amports_ops, 0, sizeof(amports_ops));
    cpu = id; gxlx2_late_video_init = opt_in;
    init_calls = writes = reads = init_error = allocation_error = 0;
}
static int publish(void) {
    struct chip_register_ops table[] = {
        {IO_VC_BUS, 0, fake_read, fake_write, 0, 0},
        {IO_HHI_BUS, -0x1000, fake_read, fake_write, 0, 0},
        {IO_DMC_BUS, 0, fake_read, fake_write, 0, 0},
    };
    return register_reg_ops_per_cpu(cpu, table, 3);
}
int main(void) {
    assert(!gxlx2_late_video_init); /* Default preserves known boot. */
    reset(0x2a, false);
    assert(early_init() == 0 && init_calls == 1 && writes == 0);
    assert(publish() == 0 && late_init() == 0 && writes == 0);
    /* Reproduce the baseline lost write; no accidental replay with opt-in off. */
    for (int id = 0; id < 0x40; id++) {
        for (int option = 0; option < 2; option++) {
            for (int failure = 0; failure < 2; failure++) {
                reset(id, option != 0);
                init_error = failure ? -EIO : 0;
                if (id == 0x2a && option) {
                    assert(early_init() == 0 && init_calls == 0 && writes == 0);
                    assert(late_init() == -ENODEV && init_calls == 0);
                    allocation_error = 1;
                    assert(publish() == -ENOMEM);
                    assert(late_init() == -ENODEV && init_calls == 0);
                    allocation_error = 0;
                    assert(publish() == 0);
                    assert(late_init() == init_error && init_calls == 1);
                } else {
                    assert(publish() == 0);
                    assert(early_init() == init_error && init_calls == 1);
                    assert(late_init() == 0 && init_calls == 1);
                }
                assert(writes == (failure ? 0 : 1));
                assert(reads == 0); /* Readiness never performs register I/O. */
            }
        }
    }
    reset(0x2a, true);
    assert(!codec_reg_bus_ready(BUS_MAX));
    assert(!codec_reg_bus_ready(UINT32_MAX));
    assert(publish() == 0);
    for (int missing = 0; missing < 3; missing++) {
        int bus[] = {IO_VC_BUS, IO_HHI_BUS, IO_DMC_BUS};
        struct chip_register_ops *saved = amports_ops[bus[missing]];
        amports_ops[bus[missing]] = NULL;
        assert(late_init() == -ENODEV && init_calls == 0);
        amports_ops[bus[missing]] = saved;
        saved->read = NULL;
        assert(!codec_reg_bus_ready(bus[missing]));
        saved->read = fake_read; saved->write = NULL;
        assert(!codec_reg_bus_ready(bus[missing]));
        saved->write = fake_write;
    }
    assert(reads == 0 && writes == 0);
    assert(codec_vcbus_read(0) == 7 && reads == 1);
    codec_clear_vcbus_mask(0, 1);
    codec_set_vcbus_mask(0, 2);
    codec_set_vcbus_bits(0, 1, 3, 1);
    assert(reads == 4 && writes == 3);
    reset(0, false);
    return 0;
}
'''
    c = root / 'test.c'
    c.write_text(harness)
    subprocess.run([shutil.which('clang') or 'cc', '-std=c99', '-Wall', '-Werror',
                    str(c), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)

print('PASS: baseline early probe write is lost; opt-in GXLX2 init waits for real bus callbacks')
print('PASS: all CPU IDs 0..0x3f/default paths, init/allocation errors and missing buses exercised')
print('Host simulation only: full ARM build, linked late-init order and physical playback remain pending.')
