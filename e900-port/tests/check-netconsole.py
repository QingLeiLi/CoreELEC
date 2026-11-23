#!/usr/bin/env python3
"""Check the real netpoll callback and the receive/release workflow boundaries."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,tempfile
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
path='drivers/net/ethernet/stmicro/stmmac/stmmac_main.c'
row=next(r for r in json.loads((PORT/'tests/source-fixtures.json').read_text()) if r['path']==path)
data=(AUDIT/'sources'/path.replace('/','__')).read_bytes()
assert hashlib.sha256(data).hexdigest()==row['sha256']
with tempfile.TemporaryDirectory(prefix='e900-netpoll-') as directory:
 root=Path(directory);p=root/path;p.parent.mkdir(parents=True);p.write_bytes(data)
 subprocess.run(['git','init','-q',str(root)],check=True)
 subprocess.run(['git','apply',str(PORT/'patches/linux/0020-gxlx2-netpoll-no-sleep.patch')],cwd=root,check=True)
 text=p.read_text();start=text.index('static void stmmac_poll_controller(');end=text.index('\n}',start)+2
 callback=text[start:end]
 c=r'''
#include <assert.h>
#include <stdbool.h>
struct net_device {int irq;};
static int cpu,step,wait_calls,nowait_calls;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static void disable_irq(int irq){assert(irq==17 && step++==0);wait_calls++;}
static void disable_irq_nosync(int irq){assert(irq==17 && step++==0);nowait_calls++;}
static void stmmac_interrupt(int irq,struct net_device *dev){assert(irq==17 && dev->irq==17 && step++==1);}
static void enable_irq(int irq){assert(irq==17 && step++==2);}
'''+callback+r'''
int main(void){
 struct net_device dev={17};
 for(cpu=0;cpu<64;cpu++){
  step=wait_calls=nowait_calls=0;stmmac_poll_controller(&dev);
  assert(step==3 && wait_calls==(cpu!=0x2a) && nowait_calls==(cpu==0x2a));
 }
 return 0;
}
'''
 src=root/'test.c';src.write_text(c)
 subprocess.run([shutil.which('clang') or 'cc','-std=c99','-Wall','-Werror',str(src),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
arm=(PORT/'scripts/arm-netconsole.py').read_text()
assert 'gxlx2_hw_init_run' not in arm
release=(PORT/'scripts/release-video-init.sh').read_text()
assert release.index('systemctl stop kodi')<release.index('> "$p/gxlx2_hw_init_run"')
assert 'CONFIG_NETCONSOLE=m' in (PORT.parent/'projects/Amlogic-ce/devices/Amlogic-ng/linux/linux.aarch64.conf').read_text()
subprocess.run(['sh','-n',str(PORT/'scripts/release-video-init.sh')],check=True)
for script in ('receive-netconsole.py','arm-netconsole.py'):
 compile((PORT/'scripts'/script).read_text(),script,'exec')
print('PASS: real netpoll callback avoids waiting only on GXLX2; disable/poll/enable ordering preserved')
print('PASS: arming cannot release init; release stops Kodi and requires idle decoder; scripts parse')
print('Host checks only: ARM build, real UDP/netpoll and diagnostic-wait boot remain unverified.')
