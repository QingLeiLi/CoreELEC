from pathlib import Path
import json,socket,time,runpy,sys,subprocess
base=Path('/storage/e900-build292');run=base/'paired-01';tools=base/'debug-tools';phase=sys.argv[1]
report={'phase':phase,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'steps':[]}
def save():(base/(phase+'-rpc.json')).write_text(json.dumps(report,indent=2))
def rpc(method,params):
 with socket.create_connection(('127.0.0.1',9090),3) as conn:
  conn.settimeout(5);conn.sendall(json.dumps({'jsonrpc':'2.0','id':41,'method':method,'params':params}).encode());buf=''
  while len(buf)<65536:
   chunk=conn.recv(8192)
   if not chunk:raise RuntimeError('Incomplete RPC reply')
   buf+=chunk.decode()
   while buf.strip():
    try:obj,end=json.JSONDecoder().raw_decode(buf.lstrip())
    except ValueError:break
    buf=buf.lstrip()[end:]
    if obj.get('id')!=41:continue
    report['steps'].append({'method':method,'response':obj});save()
    if 'error' in obj:raise RuntimeError(str(obj['error']))
    return obj['result']
 raise RuntimeError('RPC reply too large')

audit=runpy.run_path(str(tools/'e900-playback-audit.py'))
if Path('/sys/module/amvideo/parameters/gxlx2_hw_init_status').read_text().strip()!='2':raise RuntimeError('Video init not complete')
if Path('/sys/module/am_vecm/parameters/gxlx2_hdr_recovery').read_text().strip() not in ('0','N'):raise RuntimeError('HDR experiment enabled')
if phase in ('first','replay') and Path('/sys/class/vdec/vdec_status').read_text().strip()!='No vdec.':raise RuntimeError('Decoder already active')
rpc('Application.SetVolume',{'volume':0})
subprocess.run(['dmesg'],stdout=(base/(phase+'-before.dmesg')).open('w'),check=True)
audit['arm'](run,phase)
try:
 if phase=='stop':
  rpc('Player.Stop',{'playerid':1})
  for i in range(100):
   if Path('/sys/class/vdec/vdec_status').read_text().strip()=='No vdec.':break
   time.sleep(.02)
 else:
  rpc('Player.Open',{'item':{'file':'/storage/videos/Test-H264-720p-20min.mp4'}})
  for i in range(200):
   dec=Path('/sys/class/vdec/vdec_status').read_text()
   if 'ammvdec_h264' in dec:
    time.sleep(.12);break
   if audit['state'](audit['read']('scan'))['status']!=1:break
   time.sleep(.02)
finally:
 audit['freeze'](run,phase,hdmi=(phase!='stop'))
 report['decoder']=Path('/sys/class/vdec/vdec_status').read_text();save()
 subprocess.run(['dmesg'],stdout=(base/(phase+'-after.dmesg')).open('w'),check=True)
print(json.dumps(report,indent=2))
