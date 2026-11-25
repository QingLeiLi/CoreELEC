#!/usr/bin/env python3
"""Exercise register-only capture/export and consent/ownership failure paths."""
from pathlib import Path
import runpy
P=Path(__file__).resolve().parents[1]
m=runpy.run_path(str(P/'scripts/e900-register-transition.py'));fields=m['EDGE']['FIELDS'];ext=m['META']+m['REG_FIELDS']
class Clock:
 def __init__(self):self.now=0
 def time(self):return self.now
 def sleep(self,n):self.now+=n
class IO:
 def __init__(self,c):
  self.c=c;self.gen=0;self.status=0;self.mode=1;self.start=0;self.page=0;self.global_=1;self.off=None;self.restored=None;self.writes=[];self.freeze=False;self.replace=False;self.bad_regs=False;self.fail_on_restore=False;self.busy_race=False;self.bad_mode=False
 def snapshot(self):
  count=0 if self.freeze else min(512,int((self.c.now-self.start+1e-8)*60)*2)
  if self.status==2 and self.restored is not None and self.c.now-self.restored>=16/60:self.status=3
  return dict(generation=self.gen,status=self.status,count=count,tick=count//2,off=int(self.off is not None),restored=1,reason=0,guard=0,x=0,y=0,mode=self.mode)
 def read(self,name):
  s=self.snapshot()
  if name=='scan':return ' '.join(f'{k}={v}' for k,v in s.items())
  assert name in ('data','regs');lines=[]
  for i in range(self.page*8,min(s['count'],self.page*8+8)):
   r={k:0 for k in fields};r.update(index=i,generation=self.gen,stamp=i+100,tick=i//2+1,phase=i%2,flags=1,live=0x100054b0,gen=0x38420043)
   t=self.start+(i//2)/60;g=not (self.off is not None and t>=self.off and (self.restored is None or t<self.restored));r['global']=r['enabled']=int(g)
   r.update({k:0x1000+j for j,k in enumerate(m['REG_FIELDS'])})
   names=fields if name=='data' else ext
   if self.bad_regs and name=='regs':r['generation']+=1
   lines.append(' '.join(str(r[k]) if j<2 else format(r[k],'x') for j,k in enumerate(names)))
  if self.replace:self.gen+=1;self.replace=False
  return '\n'.join(lines)+'\n\n'
 def write(self,name,val):
  self.writes.append((name,val))
  if name=='scan':
   if val:
    if self.busy_race:self.gen+=1;self.status=2;raise OSError('another session armed first')
    assert val==2;self.gen=(self.gen+1)&0xffffffff;self.status=2;self.mode=1 if self.bad_mode else 2;self.start=self.c.now
   else:self.status=4
  else:assert name=='page';self.page=val
 def global_read(self):return str(self.global_)
 def global_write(self,v):
  self.writes.append(('global',v))
  if v==1 and self.fail_on_restore:self.fail_on_restore=False;raise OSError('restore transient')
  self.global_=int(v)
  if not v:self.off=self.c.now
  else:self.restored=self.c.now

def run(io,c,confirmed=True):return m['collect'](io,True,confirmed,clock=c.time,sleep=c.sleep)
c=Clock();io=IO(c);r=run(io,c);assert r['status']=='collected_register_transition',r
assert r['pixels']=='not_collected' and not r['submission_evidence_complete']
assert all(row['flags']==1 and not row['pixel_read_coherent'] for row in r['records'])
assert r['summary']['row_indices']['before'] and r['summary']['row_indices']['during'] and r['summary']['row_indices']['after']
assert [v for k,v in io.writes if k=='global']==[0,1]
assert all(row['registers']['canvas']==0x1000 for row in r['records'])
c=Clock();io=IO(c);io.gen=0xffffffff;r=run(io,c);assert r['state']['generation']==0
c=Clock();io=IO(c);r=run(io,c,False);assert r['status']=='failed' and not io.writes
c=Clock();io=IO(c);io.bad_regs=True;r=run(io,c);assert r['status']=='failed' and 'misaligned' in r['error']
c=Clock();io=IO(c);io.freeze=True;r=run(io,c);assert r['status']=='failed' and io.status==4 and not [x for x in io.writes if x[0]=='global']
c=Clock();io=IO(c);io.bad_mode=True;r=run(io,c);assert r['status']=='failed' and io.status==4
c=Clock();io=IO(c);io.fail_on_restore=True;r=run(io,c);assert r['status']=='failed' and io.global_==1 and r['global_restored']
c=Clock();io=IO(c);io.busy_race=True;r=run(io,c);assert r['status']=='failed' and io.status==2 and ('scan',0) not in io.writes
# An extension with a matching row index but different phase is not accepted.
row={k:0 for k in fields};row.update(index=0,generation=1,stamp=1,tick=1,phase=0,flags=1)
vals=[row[k] for k in m['META']]+[0]*16
text=lambda vs:' '.join(str(v) if i<2 else format(v,'x') for i,v in enumerate(vs))+'\n\n'
assert len(m['decode_extensions']([text(vals)],[row]))==1
for pos in (0,1,2,3,4,5):
 bad=list(vals);bad[pos]+=1
 try:m['decode_extensions']([text(bad)],[row])
 except ValueError:pass
 else:raise AssertionError('misassociated extension accepted')
for bad in ['bad\n','\n',text(vals)+text(vals)]:
 try:m['decode_extensions']([bad],[row])
 except ValueError:pass
 else:raise AssertionError('malformed extension accepted')
# Joint capture freezes only its own submit generation; overflow remains partial.
submit_module=runpy.run_path(str(P/'scripts/e900-submit-trace.py'))
def submission(foreign=False,overflow=False,active=False):
 data=dict(generation=4,status=1 if active else 2,count=0,capacity=4096,overflow=0);calls=[];reads=[0]
 def read(name):
  assert name=='scan';reads[0]+=1
  if foreign and reads[0]==3:data['generation']+=1
  return ' '.join(f'{k}={v}' for k,v in data.items())
 def write(name,value):
  assert name=='scan';calls.append(value)
  if value:data['generation']+=1;data['status']=1
  else:data['status']=2
 def export():
  assert data['status']==2
  return dict(status='overflow_partial' if overflow else 'collected_software_tables',state=dict(data))
 return dict(state=submit_module['state'],read=read,write=write,export=export),calls
for overflow in (False,True):
 c=Clock();io=IO(c);sub,calls=submission(overflow=overflow);r=m['collect'](io,True,True,sub,clock=c.time,sleep=c.sleep)
 assert r['status']=='collected_register_transition' and r['submission_evidence_complete']==(not overflow) and calls==[1,0]
c=Clock();io=IO(c);sub,calls=submission(foreign=True);r=m['collect'](io,True,True,sub,clock=c.time,sleep=c.sleep)
assert 'not stopping foreign' in r['submission_error'] and calls==[1] and not r['submission_evidence_complete']
c=Clock();io=IO(c);sub,calls=submission(active=True);r=m['collect'](io,True,True,sub,clock=c.time,sleep=c.sleep)
assert r['status']=='failed' and not calls and not io.writes
print('PASS: mode2 export alignment, sysfs newline, before/off/restore windows, explicit baseline consent, timeouts/restore, generation wrap and foreign-session ownership')
