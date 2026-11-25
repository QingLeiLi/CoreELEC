#!/usr/bin/env python3
"""Strict table export and ordered comparison including repeated coefficients."""
import copy,runpy
from pathlib import Path
m=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/e900-submit-trace.py'))
def row(i,b,kind,reg=0,value=0,item=0,h=1):return f'{i} 3 {100+i:x} {b:x} {h:x} {kind:x} {reg:x} {value:x} {item:x}\n'
page=row(0,1,0,value=1,item=4)+row(1,1,1,0x1d03,0,0)+row(2,1,1,0x1d04,22,1)+row(3,1,1,0x1d04,33,3)+row(4,1,2,value=0x1000000)+'\n'
state=dict(generation=3,status=2,count=5,capacity=4096,overflow=0)
text=lambda s:' '.join(f'{k}={v}' for k,v in s.items())
class IO:
 def __init__(self):self.calls=0;self.replace=False
 def read(self,name):
  if name=='data':return page
  self.calls+=1;s=dict(state)
  if self.replace and self.calls>1:s['generation']=4
  return text(s)
 def write(self,name,value):assert name=='page' and value==0
io=IO();a=m['export'](io.read,io.write);assert a['batches'][1]['words']==[[0,0x1d03,0],[1,0x1d04,22],[3,0x1d04,33]];assert a['batches'][1]['terminal']=='irq_observed'
assert m['compare'](a,a)['same_ordered_selected_batches']
b=copy.deepcopy(a);b['pages']=[page.replace('1d04 16','1d04 17')];assert not m['compare'](a,b)['same_ordered_selected_batches']
# Timestamp/batch identifiers do not determine table equality.
b=copy.deepcopy(a);b['pages']=[''.join(' '.join(str(int(v)+100) if j==2 else v for j,v in enumerate(line.split()))+'\n' for line in page.splitlines() if line.split())];assert m['compare'](a,b)['same_ordered_selected_batches']
for bad in [page.replace('1d04','dead',1),page.replace('3 3 ', '2 3 ',1),page.replace('1d04 16','1d04 -1'),page+row(5,1,2),page.replace('4 3 ', '9 3 ',1),'bad\n','\n',page.replace('1d04 21 3','1d04 21 0')]:
 try:m['decode']([bad],state)
 except ValueError:pass
 else:raise AssertionError('Malformed table accepted: '+bad)
io=IO();io.replace=True
try:m['export'](io.read,io.write)
except ValueError:pass
else:raise AssertionError('Changed generation accepted')
for key,value in [('overflow',1),('count',0)]:
 b=copy.deepcopy(a);b['state'][key]=value
 try:m['compare'](a,b)
 except ValueError:pass
 else:raise AssertionError('Incomplete comparison accepted')
# A canceled or pending batch is retained and never called IRQ completion.
for kind,expected in [(3,'canceled'),(None,'pending')]:
 p=page if kind is None else page.replace('1 1 2 0 1000000', '1 1 3 0 1')
 if kind is None:p='\n'.join(page.splitlines()[:4])+'\n'
 s=dict(state,count=4 if kind is None else 5);_,bs=m['decode']([p],s);assert bs[1]['terminal']==expected
print('PASS: strict sysfs export, duplicate/order/range checks, repeated coefficients, generation replacement, overflow refusal and non-causal comparison')
