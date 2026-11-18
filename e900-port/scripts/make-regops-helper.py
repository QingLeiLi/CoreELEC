#!/usr/bin/env python3
"""Build a one-boot GXLX2 registration experiment using the existing kernel API.

Uses ABI metadata from a pinned matching module, not a kernel source rebuild.
Kernel callback addresses are taken from an audited live boot and must never
be persisted or reused with a different kernel/boot without a fresh audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

TEMPLATE_SHA='d5e5bcd6069ac93c14119078fc06f47a2c8c92e2094b4705dfcebbe34e4450e5'
VERMAGIC='4.9.269 SMP preempt mod_unload modversions aarch64'

def sections(data):
    assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0]==183
    off=struct.unpack_from('<Q',data,40)[0];size,count,index=struct.unpack_from('<HHH',data,58)
    assert size==64
    rows=[struct.unpack_from('<IIQQQQIIQQ',data,off+i*size) for i in range(count)]
    names=data[rows[index][4]:rows[index][4]+rows[index][5]]
    return {names[s[0]:].split(b'\0',1)[0].decode():s for s in rows}

def make(template,symbols,output,mask_vsync=False):
    assert not output.exists()
    data=template.read_bytes();assert hashlib.sha256(data).hexdigest()==TEMPLATE_SHA
    sec=sections(data);this=sec['.gnu.linkonce.this_module'];raw=data[this[4]:this[4]+this[5]]
    assert len(raw)==832 and raw[24:35]==b'fake_video\0'
    assert not any(raw[:24]+raw[80:])
    versions=sec['__versions'];blob=data[versions[4]:versions[4]+versions[5]]
    records=[blob[i:i+64] for i in range(0,len(blob),64)]
    record=next(x for x in records if x[8:].split(b'\0',1)[0]==b'module_layout')
    assert struct.unpack_from('<Q',record)[0]==434193837
    audit=json.loads(symbols.read_text());assert audit['amports_ops_all_null'] is True
    s=audit['symbols'];lo,hi=s['_text'],s['_etext']
    buses=[(0,0,'dosbus'),(1,0,'aobus'),(2,-0x1000,'hiubus'),(3,0,'cbus'),(4,0,'vcbus'),(13,0,'vcbus'),(14,0,'dmcbus')]
    for name,value in s.items():
        if name not in {'_text','_etext','amports_ops'}:assert lo<=value<hi,name
    irq_call=''
    if mask_vsync:
        irq=audit['vsync_irq']
        assert irq['number']==27 and set(irq['handlers'])=={'osd-vsync','vsync'}
        irq_call='((void (*)(unsigned int))0x%xULL)(27);' % s['disable_irq']
    entries=[]
    for bus,offset,name in buses:
        entries.append('{%d,%d,(read_fn)0x%xULL,(write_fn)0x%xULL,0,0}'%(bus,offset,s['codecio_read_'+name],s['codecio_write_'+name]))
    source='''// SPDX-License-Identifier: GPL-2.0-only
// Temporary GXLX2 registration experiment for one audited running kernel.
typedef int (*read_fn)(unsigned int);
typedef void (*write_fn)(unsigned int,unsigned int);
struct chip_register_ops { int bus_type,ext_offset;read_fn read;write_fn write;int r_cnt,w_cnt; };
_Static_assert(sizeof(struct chip_register_ops)==32,"Kernel ops ABI");
static struct chip_register_ops ops[] = { ENTRIES };
__attribute__((section(".init.text"))) int init_module(void) {
 IRQ_CALL
 int result=((int (*)(int,struct chip_register_ops*,int))REGAPI)(42,ops,7);
 if (result) return result;
 int value=((int (*)(unsigned int,unsigned int))READAPI)(14,0x32);
 ((int (*)(const char*,...))PRINTAPI)("<6>e900-regops: registered 7 direct buses; DMC status=0x%x\\n",value);
 return 0;
}
__attribute__((section(".exit.text"))) void cleanup_module(void) { }
struct module_abi {
 unsigned char prefix[24];char name[56];unsigned char before_init[264];
 int (*init)(void);unsigned char before_exit[416];void (*exit)(void);unsigned char tail[56];
};
_Static_assert(sizeof(struct module_abi)==832,"Kernel module ABI");
_Static_assert(__builtin_offsetof(struct module_abi,init)==0x158,"Init relocation ABI");
_Static_assert(__builtin_offsetof(struct module_abi,exit)==0x300,"Exit relocation ABI");
__attribute__((section(".gnu.linkonce.this_module"),used,aligned(64)))
struct module_abi __this_module={.name="e900_regops",.init=init_module,.exit=cleanup_module};
__attribute__((section("__versions"),used,aligned(8)))
static const unsigned char versions[64]={VERSION_BYTES};
__attribute__((section(".modinfo"),used))
static const char info[]="license=GPL\\0vermagic=VERMAGIC\\0name=e900_regops\\0description=Temporary GXLX2 direct-bus registration\\0";
asm(".pushsection .plt,\\"ax\\",%progbits\\n.byte 0\\n.popsection\\n");
'''
    source=source.replace('IRQ_CALL',irq_call).replace('ENTRIES',','.join(entries)).replace('REGAPI',hex(s['register_reg_ops_per_cpu'])+'ULL').replace('READAPI',hex(s['codec_reg_read'])+'ULL').replace('PRINTAPI',hex(s['printk'])+'ULL').replace('VERSION_BYTES',','.join(str(x) for x in record)).replace('VERMAGIC',VERMAGIC)
    # Generate actual C string escapes, not doubled source backslashes.
    source=source.replace('\\\\','\\')
    output.mkdir(parents=True);c=output/'e900_regops.c';c.write_text(source)
    module=output/'e900_regops.ko'
    subprocess.run(['clang','-target','aarch64-none-elf','-O2','-ffreestanding','-fno-stack-protector','-fno-pic','-mcmodel=large','-fno-asynchronous-unwind-tables','-c',str(c),'-o',str(module)],check=True)
    generated=module.read_bytes();gs=sections(generated)
    assert gs['.gnu.linkonce.this_module'][5]==832 and '__versions' in gs and '.plt' in gs
    # This 4.9 loader rejects ADR_PREL_PG_HI21 (275); large-model code must
    # use only its supported absolute data/function-address relocations.
    for section in gs.values():
        if section[1]!=4:continue  # SHT_RELA
        assert section[9]==24
        for pos in range(section[4],section[4]+section[5],24):
            relocation=struct.unpack_from('<QQq',generated,pos)[1]&0xffffffff
            assert relocation in {257,264,266,268,269},relocation
    sym=gs['.symtab'];rows=[struct.unpack_from('<IBBHQQ',generated,sym[4]+i*24) for i in range(sym[5]//24)]
    assert not any(row[3]==0 and row[0]!=0 for row in rows),'Unresolved external symbol'
    (output/'helper-provenance.json').write_text(json.dumps({'boot_id':audit['boot_id'],'template_sha256':TEMPLATE_SHA,'module_sha256':hashlib.sha256(generated).hexdigest(),'vermagic':VERMAGIC,'buses':[x[0] for x in buses],'purpose':'Temporary direct bus registration via existing kernel API','persistent':False,'masked_vsync_irq':27 if mask_vsync else None,'mask_recovery':'reboot restores IRQ state' if mask_vsync else None,'hardware_tested':False},indent=2)+'\n')
    print('Prepared helper with matching module ABI/version CRC; no unresolved external symbols')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['template','symbols','output']:p.add_argument(name,type=Path)
    p.add_argument('--mask-vsync',action='store_true',help='One-boot isolation: mask audited shared VSYNC IRQ27 before registration; reboot restores it')
    a=p.parse_args();make(a.template,a.symbols,a.output,a.mask_vsync)
