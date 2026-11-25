#!/usr/bin/env python3
"""Image pairs require moving colorbar positive control; never recover clocks."""
from pathlib import Path
import runpy,subprocess,tempfile
P=Path(__file__).resolve().parents[1];m=runpy.run_path(str(P/'scripts/e900-loopback.py'));ins=m['INSPECT'];H=ins['HEADER']
colors=[(235,128,128),(210,16,146),(170,166,16),(145,54,34),(106,202,222),(81,90,240),(41,240,110),(16,128,128)]
def packet(n,kind='bars',same=False,stale=False):
 w,h=64,36;row=b''.join(bytes(c)*8 for c in colors) if kind=='bars' else bytes((16,128,128))*w
 raw=bytearray(row*h)
 if kind=='bars':
  x=21 if same else 20+n%20;i=(18*w+x)*3;raw[i:i+3]=bytes(colors[0])
 raw=b''.join(raw[i:i+8][::-1] for i in range(0,len(raw),8))
 return H.pack(b'E9VDIN1\0',1,80,w,h,2,w*3,w*3,n%10,8,3,100 if stale else 100+n,200+n,300+n,len(raw))+raw
with tempfile.TemporaryDirectory(prefix='e900-image-pair-') as td:
 root=Path(td)
 def helper(label,kind='bars',same=False,stale=False,active=True):
  count=[0];calls=[]
  def run(args,**kw):
   assert args[0]=='sh' and args[-2].endswith('e900-capture-ready.sh')
   assert kw['env']['E900_CAPTURE_NO_GATE']=='1' and kw['env']['E900_CAPTURE_SKIP_SYNC']=='1'
   count[0]+=1;calls.append(args);f=root/(label+'-'+str(count[0])+'.e9cap');f.write_bytes(packet(count[0],kind,same,stale))
   return subprocess.CompletedProcess(args,0,stdout=str(f)+'\n')
  return m['Loopback'](root/label,runner=run,sleep=lambda _:None,decoder=lambda:'ammvdec_h264' if active else 'No vdec.',gui=lambda:{'status':'ok'}),calls
 h,c=helper('positive');r=h('before');assert r['status']=='fresh_completed_pair' and len(r['frames'])==2 and len(c)==2
 assert all(f['colorbar_reference'] and Path(f['png']).read_bytes().startswith(b'\x89PNG') for f in r['frames'])
 for label,opts in [('same',dict(same=True)),('stale',dict(stale=True)),('black-reference',dict(kind='black')),('inactive',dict(active=False))]:
  h,c=helper(label,**opts);r=h('before');assert r['status']=='failed',(label,r)
 h,c=helper('black-after',kind='black');r=h('after');assert r['status']=='fresh_completed_pair' and all(f['rgb_min']==f['rgb_max']==0 for f in r['frames'])
 # Same-session after-frame timestamps must advance beyond the last before image.
 h,c=helper('session');assert h('before')['status']=='fresh_completed_pair';assert h('after')['status']=='fresh_completed_pair'
print('PASS: real YUV decode/PNG pairs, moving positive reference, fresh completion/time, valid black-after images; no playback/start or clock recovery commands')
