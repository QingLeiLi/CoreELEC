#!/usr/bin/env python3
"""Exercise the actual collector against advancing and failing kernel sessions."""
from pathlib import Path
import importlib.util
P=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('edge',P/'scripts/e900-transition.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Clock:
 def __init__(self):self.now=0
 def time(self):return self.now
 def sleep(self,n):self.now+=n
class Kernel:
 def __init__(self,c):
  self.c=c;self.generation=0;self.status=0;self.start=0;self.global_=1;self.off_time=None;self.restore_time=None;self.page=0;self.writes=[];self.freeze=False;self.zero=False;self.bad_page=False;self.replace=False;self.raise_restore=False;self.reason=0
 def snapshot(self):
  elapsed=self.c.now-self.start;count=0 if self.freeze else min(512,int((elapsed+1e-8)*60)*2)
  if self.status==2 and self.restore_time is not None and self.c.now-self.restore_time>=16/60:self.status=3
  return dict(generation=self.generation,status=self.status,count=count,tick=count//2,off=int(self.off_time is not None),restored=int(self.status in (3,4)),reason=self.reason,guard=0,x=80,y=360)
 def read(self,name):
  s=self.snapshot()
  if name=='scan':return ' '.join(str(k)+'='+str(v) for k,v in s.items())
  assert name=='data';lines=[]
  for i in range(self.page*8,min(self.page*8+8,s['count'])):
   d={k:0 for k in m.FIELDS};d.update(index=i,generation=self.generation,stamp=i+100,tick=i//2+1,phase=i%2,flags=7 if i>=4 else 3,raw0=0 if self.zero else 0xac200200,raw1=0 if self.zero else 0x80000003)
   t=self.start+(i//2)/60;g=0 if self.off_time is not None and t>=self.off_time and (self.restore_time is None or t<self.restore_time) else 1;d.update(global_=g);d['global']=g;d['enabled']=g
   lines.append(' '.join(str(d[k]) if j<2 else format(d[k],'x') for j,k in enumerate(m.FIELDS)))
  if self.replace:self.generation+=1;self.replace=False
  return '\n'.join(lines)+('\n' if lines else '') if not self.bad_page else 'bad\n'
 def write(self,name,val):
  self.writes.append((name,val))
  if name=='scan':
   if val:self.generation=(self.generation+1)&0xffffffff;self.status=2;self.start=self.c.now
   else:self.status=4
  else:assert name=='page';self.page=val
 def global_read(self):return str(self.global_)
 def global_write(self,val):
  if val==1 and self.raise_restore:self.raise_restore=False;raise OSError('restore transient')
  self.global_=int(val);self.writes.append(('global',int(val)))
  if not val:self.off_time=self.c.now
  else:self.restore_time=self.c.now

def run(io,c):return m.collect(io,True,clock=c.time,sleep=c.sleep)
c=Clock();k=Kernel(c);r=run(k,c);assert r['status']=='collected_not_pixel_validated',r
assert [x for x in k.writes if x[0]=='global']==[('global',0),('global',1)]
assert r['boundaries']['before'] and r['boundaries']['during'] and r['boundaries']['after']
assert all(x['hardware_pixel_validity'] in ('unknown','not_read') for x in r['records'])
c=Clock();k=Kernel(c);k.generation=0xffffffff;r=run(k,c);assert r['final']['generation']==0
c=Clock();k=Kernel(c);k.zero=True;r=run(k,c);assert r['status']=='failed' and not [x for x in k.writes if x[0]=='global'] and k.status==4
c=Clock();k=Kernel(c);k.freeze=True;r=run(k,c);assert r['status']=='failed' and k.status==4
c=Clock();k=Kernel(c);k.raise_restore=True;r=run(k,c);assert r['status']=='failed' and r['global_restored'] and k.global_==1 and k.status==4
c=Clock();k=Kernel(c);k.status=6;r=run(k,c);assert r['status']=='failed' and not k.writes
c=Clock();k=Kernel(c);k.global_=0;r=run(k,c);assert r['status']=='failed' and not k.writes
# Parser rejects truncation, duplicates, bad generation/phase/flags. It retains
# all-zero raw data as unknown, not automatically valid black pixels.
row={key:0 for key in m.FIELDS};row.update(generation=4,flags=7)
def text(d):return ' '.join(str(d[k]) if i<2 else format(d[k],'x') for i,k in enumerate(m.FIELDS))+'\n'
r=m.decode([text(row)],{'count':1,'generation':4})[0];assert r['raw0']==r['raw1']==0 and r['hardware_pixel_validity']=='unknown'
for bad in ['bad\n',text(dict(row,index=1)),text(dict(row,generation=5)),text(dict(row,phase=2)),text(dict(row,flags=8)),text(row)+text(row)]:
 try:m.decode([bad],{'count':1,'generation':4})
 except ValueError:pass
 else:raise AssertionError('Accepted invalid export')
print('PASS: real collector transition, generation wrap, timeout/cancel, no-reference refusal, global restore and strict export; hardware validity remains unknown')
