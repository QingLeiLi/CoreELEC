#!/usr/bin/env python3
"""Exercise fixed-map boot guards and rollback without real MMIO or hardware."""
from pathlib import Path
import importlib.util

PORT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('boot_recovery',PORT/'scripts/e900-osd-rdma-boot.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Fake:
    def __init__(self):
        self.values={'/etc/os-release':f'ID="coreelec"\nVERSION="{m.BUILD}"\n',
                     '/proc/device-tree/coreelec-dt-id':m.BOARD+'\0',
                     '/proc/version':'Linux version 4.9.269',
                     '/proc/cmdline':'amvideo.gxlx2_hw_init_wait=0',
                     '/sys/module/amvideo/parameters/gxlx2_hw_init_status':'2',
                     '/sys/class/vdec/vdec_status':'No vdec.'}
        self.regs={'1110':0x120,'1106':0x34e10000,'1107':0x34e10e07}
        self.counts=iter([0,0,0,12,24]);self.writes=[];self.race=False;self.auto_reads=0
    def text(self,p):return self.values[p].strip()
    def irq(self):return next(self.counts)
    def sleep(self,s):pass
    def read_reg(self,r):
        assert r in self.regs
        if r=='1110':
            self.auto_reads+=1
            if self.race and self.auto_reads==2:return 0x140
        return self.regs[r]
    def write_auto(self,v):
        self.writes.append(v);self.regs['1110']=v
        if len(self.writes)==1:self.regs['1110']|=0x00400040  # legitimate CH2 callback

def reject(f):
    try:m.recover(f,{})
    except RuntimeError:pass
    else:raise AssertionError('Unsafe/unexpected state accepted')
    assert not f.writes

f=Fake();r={};m.recover(f,r);assert r['result']=='recovered' and f.writes==[0x010001a0]
f=Fake();r={};m.recover(f,r,check=True);assert r['result']=='would-recover' and not f.writes
f=Fake();f.counts=iter([100,106]);r={};m.recover(f,r);assert r['result']=='already-completing' and not f.writes
f=Fake();f.values['/etc/os-release']='VERSION="future-image"';r={};m.recover(f,r);assert r['result']=='skipped-other-build' and not f.writes
f=Fake();f.values['/proc/cmdline']='amvideo.gxlx2_hw_init_wait=1';r={};m.recover(f,r);assert r['result']=='skipped-diagnostic-wait' and not f.writes
for path,value in [('/proc/device-tree/coreelec-dt-id','different-board'),('/proc/version','Linux 6.6'),
                   ('/sys/module/amvideo/parameters/gxlx2_hw_init_status','1'),('/sys/class/vdec/vdec_status','active frame')]:
    f=Fake();f.values[path]=value;reject(f)
for reg,value in [('1110',0),('1110',0x010001a0),('1106',0),('1106',0x34e20000),
                  ('1107',0x34e0ffff),('1107',0x34e11000),('1107',0x34e10008)]:
    f=Fake();f.regs[reg]=value;reject(f)
f=Fake();f.counts=iter([10,10]);reject(f)
f=Fake();f.race=True;reject(f)
f=Fake();f.counts=iter([0,0,0,0,0]);r={}
try:m.recover(f,r)
except RuntimeError:pass
else:raise AssertionError('No OSD completion accepted')
assert f.writes==[0x010001a0,0x00400160]  # rollback CH3, preserve callback's CH2
assert r['rollback']=='0x400160'
print('PASS: boot recovery preserves other channels, skips healthy/new builds/diagnostic mode, rejects unsafe states and rolls back failed completion')
print('PENDING: actual boot ordering, hardware completion and physical first menu')
