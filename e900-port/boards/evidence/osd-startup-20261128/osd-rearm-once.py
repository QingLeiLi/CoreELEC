from pathlib import Path
import subprocess,re,time,json
base=Path('/storage/e900-boot-speed')
debug=Path('/sys/class/graphics/fb0/debug')
def value(path):return Path(path).read_text().strip()
def readreg(reg):
 debug.write_text('r '+reg)
 text=subprocess.check_output(['dmesg'],text=True)
 found=re.findall(r'fb: reg\[0x'+reg+r'\]: 0x([0-9a-fA-F]+)',text)
 if not found:raise RuntimeError('No fresh register readback')
 return int(found[-1],16)
def osd_irq():return int(value('/sys/module/fb/parameters/rdma_irq_count'))
assert value('/proc/sys/kernel/random/boot_id')=='2a016423-613c-402f-b41f-9bd02954b476'
assert value('/sys/class/vdec/vdec_status')=='No vdec.'
old=readreg('1110');start=readreg('1106');end=readreg('1107');before=osd_irq()
assert old==0x120 and before==0
assert start==0x34e10000 and start<=end<start+4096 and (end-start+1)%8==0
mask=0xff000088;want=0x01000080;new=(old & ~mask)|want
assert new==0x010001a0
record={'boot':value('/proc/sys/kernel/random/boot_id'),'before':{'AUTO':hex(old),'START3':hex(start),'END3':hex(end),'osd_irq':before},'write':hex(new),'samples':[],'success':False}
written=False
try:
 debug.write_text('w 1110 '+format(new,'x'));written=True
 for _ in range(2):
  time.sleep(1)
  record['samples'].append({'mono':time.monotonic(),'AUTO':hex(readreg('1110')),'osd_irq':osd_irq()})
 record['success']=all(x['osd_irq']>before for x in record['samples']) and record['samples'][1]['osd_irq']>record['samples'][0]['osd_irq']
finally:
 if written and not record['success']:
  current=readreg('1110');restore=(current & ~mask)|(old & mask)
  debug.write_text('w 1110 '+format(restore,'x'));record['rollback']=hex(readreg('1110'))
 (base/'osd-rearm-result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2),flush=True)
