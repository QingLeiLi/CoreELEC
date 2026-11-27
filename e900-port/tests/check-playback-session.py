#!/usr/bin/env python3
"""Regression cases from Build292: decoder-ready isn't display-ready; no gap on replay."""
from pathlib import Path
import copy
import json
import runpy
import tempfile
from unittest import mock
import contextlib
import io

P=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(P/'scripts/e900-playback-session.py'))
A=M['AUDIT']
B=P/'boards/evidence/build292'
first=json.loads((B/'paired-01/first.json').read_text())
replay=json.loads((B/'paired-01/replay.json').read_text())
assert 'frame count : 13' in first['after']['decoder']
assert not M['display_coverage'](first['records'])['complete']
assert not M['display_coverage'](replay['records'])['complete']
stop=json.loads((B/'paired-01/stop.json').read_text())
assert stop['after']['decoder']=='No vdec.'
assert not M['stopped'](stop['records'],stop['after'])
assert A['compare'](B/'paired-01')['classification']=='INCOMPLETE_TRANSITION'


def row(i,phase,reg,value=0,source=1,kind=2,session=8,handle=0):
    return dict(zip(A['FIELDS'],[i,1,100+i,source,kind,session,phase,0,handle,reg,value,0]))


def covered(phase):
    rows=[row(0,phase,1,8)]
    for code in (3,11,12,13,14,8,9):
        rows.append(row(len(rows),phase,code,handle=1 if code in (8,9) else 0))
    for reg in (0x1a50,0x1d26,0x1d28,0x3800):
        rows.append(row(len(rows),phase,reg,source=5,kind=7))
    return rows


rows=covered(1)
assert M['display_coverage'](rows)['complete']
wrong=copy.deepcopy(rows);wrong[-1]['session']=7
assert not M['display_coverage'](wrong)['complete']
wrong=copy.deepcopy(rows)
for r in wrong:
    if r['reg'] in (8,9):r['handle']=2
assert not M['display_coverage'](wrong)['complete']
wrong=copy.deepcopy(rows);wrong.append(row(len(wrong),1,11))
assert not M['display_coverage'](wrong)['complete']
# Live prefixes grow within a page; pages can contain a later append. Never
# skip rows, accept foreign generations, reset recording or infer display.
stream=covered(1);visible=[3];writes=[]
def read(name):
    if name=='scan':return f'generation=1 status=1 count={visible[0]} capacity=65536 overflow=0 phase=1'
    page=writes[-1][1]
    return '\n'.join(' '.join(str(r[k]) if i<2 else format(r[k],'x') for i,k in enumerate(A['FIELDS'])) for r in stream[page*8:(page+1)*8])
trace=M['LiveRows'](1,read,lambda name,value:writes.append((name,value)))
assert len(trace.poll())==3
visible[0]=len(stream)
assert trace.poll()==stream
assert all(name=='page' for name,_ in writes)
try:M['LiveRows'](2,read,lambda *_:None).poll()
except RuntimeError:pass
else:raise AssertionError('Foreign live generation accepted')
# Timeout remains a failure, including when a decoder exists but no display
# boundary arrives. It cannot trigger a second media action.
prior=A['snapshot'];A['snapshot']=lambda:{'decoder':'ammvdec_h264 frame count : 13'}
try:
    try:M['wait_for'](trace,lambda *_:False,.01)
    except RuntimeError:pass
    else:raise AssertionError('Missing display boundary accepted')
finally:A['snapshot']=prior

# Emulate the complete single-generation phase boundary; deleting the
# registration/disable edge must prevent localization from being accepted.
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    docs={}
    for name,phase in [('first',1),('reference',1),('transition',2)]:
        folder=root/name;folder.mkdir()
        rs=covered(1) if name=='first' else [row(0,1,0,1,kind=1),row(1,1,0x1d28,3,source=5,kind=7),row(2,1,0x1d28,4,source=5,kind=7)]+[row(3+i,1,reg,source=5,kind=7) for i,reg in enumerate((0x1a50,0x1d26,0x3800))]
        if name=='first':rs.insert(0,row(0,1,0,1,kind=1))
        if name=='transition':rs=[row(0,2,0,2,kind=1),row(1,2,1,1),row(2,2,2,1),row(3,3,0,3,kind=1)]+covered(3)
        for i,r in enumerate(rs):r['index']=i;r['stamp']=100+i
        st=dict(generation=1,status=2,count=len(rs),capacity=65536,overflow=0,phase=3 if name=='transition' else 1)
        text='\n'.join(' '.join(str(r[k]) if i<2 else format(r[k],'x') for i,k in enumerate(A['FIELDS'])) for r in rs)
        doc=dict(boot_id='boot',state=st,pages=[text],records=rs,after=dict(disable='0',global_output='1',**{'global':'1'}));docs[name]=doc
        (folder/('stop.json' if name=='transition' else 'first.json')).write_text(json.dumps(doc))
        (folder/('stop.owner.json' if name=='transition' else 'first.owner.json')).write_text(json.dumps(dict(boot_id='boot',generation=1)))
        (folder/'manifest.json').write_text(json.dumps(dict(boot_id='boot')))
        result=dict(boot_id='boot',status='COVERED_REQUIRES_VISUAL',file='test',confirmed_normal=name=='reference',stop_boundary=dict(context={'decoder':'No vdec.','disable':'1'}))
        (folder/'result.json').write_text(json.dumps(result))
    assert M['compare_session'](root)['classification']=='REVIEW_REQUIRED'
    d=docs['transition'];d['records'][1]['value']=8
    d['pages']=['\n'.join(' '.join(str(r[k]) if i<2 else format(r[k],'x') for i,k in enumerate(A['FIELDS'])) for r in d['records'])]
    (root/'transition/stop.json').write_text(json.dumps(d))
    try:M['compare_session'](root)
    except ValueError:pass
    else:raise AssertionError('No provider teardown accepted')
print('PASS: Build292 incomplete windows rejected; same-session/VD1 display gates, live append/cross-page ownership, timeout and continuous Stop-replay checks')

# The actual executor must not launch replay after a Stop coverage timeout.
from types import SimpleNamespace
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);(root/'reference').mkdir()
    (root/'reference/result.json').write_text(json.dumps(dict(status='COVERED_REQUIRES_VISUAL',boot_id='boot',file='test',confirmed_normal=True)))
    execute=M['execute'];g=execute.__globals__;old={key:g[key] for key in ('preflight','rpc','wait_for','LiveRows','AUDIT')}
    requests=[]
    context=dict(boot_id='boot',decoder='ammvdec_h264',disable='0',global_output='1')
    def fake_rpc(method,params,log):
        requests.append(method)
        return {'item':{'file':'test'}} if method=='Player.GetItem' else 'OK'
    def fake_arm(folder,phase):
        (folder/(phase+'.owner.json')).write_text(json.dumps(dict(generation=1,boot_id='boot')))
    def fake_freeze(folder,phase,hdmi=False):
        (folder/(phase+'.json')).write_text(json.dumps(dict(state=dict(overflow=0),records=[])))
    def timeout(*_args,**_kwargs):raise RuntimeError('test missing asynchronous cleanup')
    try:
        g.update(preflight=lambda:context,rpc=fake_rpc,wait_for=timeout,LiveRows=lambda _:SimpleNamespace(rows=[]),
                 AUDIT=dict(A,arm=fake_arm,freeze=fake_freeze,snapshot=lambda:context))
        try:
            with mock.patch.object(g['subprocess'], 'run'), contextlib.redirect_stdout(io.StringIO()):
                execute(SimpleNamespace(run=root,action='transition',file='test',timeout=.01,confirmed_normal=False))
        except RuntimeError:pass
        else:raise AssertionError('Timeout reported success')
        assert requests==['Player.GetItem','Application.SetVolume','Player.Stop']
        assert json.loads((root/'transition/result.json').read_text())['status']=='INCOMPLETE'
    finally:g.update(old)
print('PASS: production executor archives Stop timeout and never issues replay afterward')

# Execute the production per-session toggle hook. It must not depend on
# upstream first_picture, and fake frames must not consume the session marker.
import subprocess
patch=(P/'patches/linux/0043-gxlx2-live-playback-windows.patch').read_text()
section=patch.split('+++ b/drivers/amlogic/media/video_sink/video.c\n',1)[1]
block='\n'.join(line[1:] for line in section.splitlines() if line.startswith('+') and not line.startswith('+++'))
source=r'''
#include <assert.h>
typedef unsigned u32;
#define atomic_read(p) (*(p))
#define VFRAME_FLAG_FAKE_FRAME 16
#define E900_PB_LIFE 1
#define E900_PB_STATE 2
#define E900_PB_FIRST_FRAME 3
static unsigned e900_hdr_session=1,notes,last;
struct vframe_s {unsigned flag,index,pts;};
static void e900_playback_note(unsigned s,unsigned k,unsigned session,unsigned b,unsigned h,unsigned r,unsigned v,unsigned a){assert(s==1&&k==2&&r==3);(void)b;(void)h;(void)v;(void)a;notes++;last=session;}
static void toggle(struct vframe_s *vf){
'''+block+r'''
}
int main(void){struct vframe_s vf={0,1,100};
 toggle(&vf);toggle(&vf);assert(notes==1&&last==1);
 e900_hdr_session=2;vf.flag=VFRAME_FLAG_FAKE_FRAME;toggle(&vf);assert(notes==1);
 vf.flag=0;toggle(&vf);assert(notes==2&&last==2);return 0;}
'''
with tempfile.TemporaryDirectory() as directory:
    c=Path(directory)/'test.c';c.write_text(source);exe=Path(directory)/'test'
    subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: actual session-first toggle note repeats on replay sessions, excludes fake frames and preserves upstream first_picture policy')
