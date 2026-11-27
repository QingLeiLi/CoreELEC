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
from types import SimpleNamespace

P=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(P/'scripts/e900-playback-session.py'))
A=M['AUDIT']
REGS=M['REQUIRED_READBACKS']
SAMPLES=(0x1d28,0x1d28)+tuple(r for r in REGS if r!=0x1d28)
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
    for code in (3,11,12,13,14,8,9,18):
        rows.append(row(len(rows),phase,code,value=7 if code==18 else 0,handle=1 if code in (8,9) else 0))
    for reg in REGS:
        rows.append(row(len(rows),phase,reg,source=5,kind=7))
    return rows


rows=covered(1)
assert M['display_coverage'](rows)['complete']
wrong=copy.deepcopy(rows);wrong[-1]['session']=7
assert not M['display_coverage'](wrong)['complete']
wrong=copy.deepcopy(rows)
for r in wrong:
    if r['reg'] in (8,9):r['handle']=2
assert M['display_coverage'](wrong)['complete']
assert not M['display_coverage'](wrong)['disposition']['hdr_requested']
# Explicit CSC no-change/unsupported PPS are observed no-ops, not missing hooks.
skipped=[r for r in copy.deepcopy(rows) if not (r['source']==1 and r['reg'] in (8,9))]
for r in skipped:
    if r['source']==1 and r['reg']==18:r['value']=6
    if r['source']==1 and r['reg']==14:r['reg']=15
assert M['display_coverage'](skipped)['complete']
assert M['display_coverage'](skipped)['disposition']['pps_unsupported']
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
    for generation,(name,phase) in enumerate([('first',1),('reference',1),('transition',2)],1):
        folder=root/name;folder.mkdir()
        rs=covered(1) if name=='first' else [row(0,1,0,1,kind=1),row(1,1,0x1d28,3,source=5,kind=7),row(2,1,0x1d28,4,source=5,kind=7)]+[row(3+i,1,reg,source=5,kind=7) for i,reg in enumerate(tuple(r for r in REGS if r!=0x1d28))]
        if name=='first':rs.insert(0,row(0,1,0,1,kind=1))
        if name=='transition':
            rs=[row(0,2,0,2,kind=1)]+[row(i+1,2,reg,value=3 if reg==0x1d28 else 0,source=5,kind=7) for i,reg in enumerate(SAMPLES)]+[row(6,2,1,1),row(7,2,2,1),row(8,2,0x3800,0x1c040,source=4,kind=4),row(9,3,0,3,kind=1)]+covered(3)
        for i,r in enumerate(rs):
            r['index']=i;r['stamp']=generation*100+i;r['generation']=generation
            if name=='transition' and r['phase']==3:
                r['session']=10
                if r['source']==5 and r['reg']==0x3800:r['value']=0x1c040
        st=dict(generation=generation,status=2,count=len(rs),capacity=65536,overflow=0,phase=3 if name=='transition' else 1)
        text='\n'.join(' '.join(str(r[k]) if i<2 else format(r[k],'x') for i,k in enumerate(A['FIELDS'])) for r in rs)
        doc=dict(boot_id='boot',state=st,pages=[text],records=rs,after=dict(disable='0',global_output='1',decoder='ammvdec_h264',**{'global':'1'}));docs[name]=doc
        (folder/('stop.json' if name=='transition' else 'first.json')).write_text(json.dumps(doc))
        (folder/('stop.owner.json' if name=='transition' else 'first.owner.json')).write_text(json.dumps(dict(boot_id='boot',generation=generation)))
        (folder/'manifest.json').write_text(json.dumps(dict(boot_id='boot',collector_sha256='a'*64)))
        result=dict(boot_id='boot',before=dict(checked_policy={'test':'0'},playback_api=2),state=st,runner_sha256='b'*64,status='COVERED_REQUIRES_VISUAL',file='test',confirmed_normal=name=='reference',pre_stop_reference={'rows':1+len(SAMPLES),'context':{'disable':'0','global':'1','decoder':'ammvdec_h264'}},stop_boundary=dict(context={'decoder':'No vdec.','disable':'1'}))
        result['rpc']=([{'method':'Player.Stop','sent':True}] if name=='transition' else [])+([{'method':'Player.Open','sent':True,'params':{'item':{'file':'test'}}}] if name in ('first','transition') else [])
        (folder/'result.json').write_text(json.dumps(result))
    assert M['compare_session'](root)['classification']=='REPLAY_OUTCOME_PENDING'
    # Same boot and individually valid pages are insufficient if phases were
    # collected out of order, by different tools, or from another provider.
    baseline=(root/'reference/result.json').read_text()
    forged=json.loads(baseline);forged['runner_sha256']='c'*64
    (root/'reference/result.json').write_text(json.dumps(forged))
    try:M['compare_session'](root)
    except ValueError:pass
    else:raise AssertionError('Mixed executor accepted')
    (root/'reference/result.json').write_text(baseline)
    original_ref=copy.deepcopy(docs['reference'])
    def save_doc(name,d):
        d['pages']=['\n'.join(' '.join(str(r[k]) if i<2 else format(r[k],'x') for i,k in enumerate(A['FIELDS'])) for r in d['records'])]
        (root/name/('stop.json' if name=='transition' else 'first.json')).write_text(json.dumps(d))
    for change in ('time','session'):
        d=copy.deepcopy(original_ref)
        for r in d['records']:
            if change=='time':r['stamp']=0
            elif r['source']==5:r['session']=999
        save_doc('reference',d)
        try:M['compare_session'](root)
        except ValueError:pass
        else:raise AssertionError('Mixed/reordered reference accepted')
    save_doc('reference',original_ref)
    # The actual goal is normal vs user-confirmed black, not merely two
    # successful startup paths. A missing replay call must remain analyzable.
    original_transition=copy.deepcopy(docs['transition'])
    original_transition_result=(root/'transition/result.json').read_text()
    out=root/'outcome';out.mkdir()
    rs=[row(0,3,0,3,kind=1)]+[row(i+1,3,reg,value=0,source=5,kind=7,session=10) for i,reg in enumerate(SAMPLES)]
    for i,r in enumerate(rs):r['generation']=4;r['stamp']=400+i
    st=dict(generation=4,status=2,count=len(rs),capacity=65536,overflow=0,phase=3)
    outcome_doc=dict(boot_id='boot',state=st,records=rs,after={'disable':'0','global':'1','decoder':'ammvdec_h264'})
    save_doc('outcome',outcome_doc)
    # save_doc's default name is first.json; outcome uses replay.json.
    (out/'first.json').rename(out/'replay.json')
    (out/'replay.owner.json').write_text(json.dumps({'boot_id':'boot','generation':4}))
    (out/'manifest.json').write_text(json.dumps({'boot_id':'boot','collector_sha256':'a'*64}))
    outcome_result=dict(boot_id='boot',state=st,runner_sha256='b'*64,status='COVERED_REQUIRES_VISUAL',file='test',before={'checked_policy':{'test':'0'},'playback_api':2},reported_outcome='black',player_identity_verified=True,pairing_verified=True)
    (out/'result.json').write_text(json.dumps(outcome_result))
    no_replay=json.loads(original_transition_result)
    no_replay['rpc'][-1]['sent']=False
    (root/'transition/result.json').write_text(json.dumps(no_replay))
    try:M['compare_session'](root)
    except ValueError:pass
    else:raise AssertionError('Stop-only black screen mislabeled as replay fault')
    (root/'transition/result.json').write_text(original_transition_result)
    comparison=M['compare_session'](root)
    assert comparison['classification']=='REVIEW_REQUIRED'
    assert comparison['visual_contrast']['replay']=='black'
    traced=next(p for p in comparison['transition_readback_provenance'] if p['read']['phase']==3 and p['read']['reg']==0x3800)
    assert traced['prior_selected_writes'][-1]['phase']==2 and traced['matches_last_selected_write']
    assert 'not a lost-write assertion' in traced['limitation']
    assert any(f['code_or_register']=='0x1d28' for f in comparison['normal_reference_vs_confirmed_outcome']['findings'])
    partial=copy.deepcopy(original_transition)
    partial['records']=[r for r in partial['records'] if not (r['source']==1 and r['kind']==2 and r['reg']==11)]
    for i,r in enumerate(partial['records']):r['index']=i
    partial['state']['count']=len(partial['records'])
    save_doc('transition',partial)
    result=json.loads(original_transition_result);result.update(status='INCOMPLETE',state=partial['state'])
    (root/'transition/result.json').write_text(json.dumps(result))
    comparison=M['compare_session'](root)
    assert comparison['classification']=='PARTIAL_REPLAY_CAPTURE'
    assert 'dcu_entry' in comparison['replay_coverage']['missing']
    assert comparison['normal_reference_vs_confirmed_outcome']
    outcome_result['player_identity_verified']=False
    (out/'result.json').write_text(json.dumps(outcome_result))
    assert M['compare_session'](root)['normal_reference_vs_confirmed_outcome'] is None
    outcome_result['reported_outcome']='normal'
    (out/'result.json').write_text(json.dumps(outcome_result))
    ambiguous=M['compare_session'](root)
    assert ambiguous['classification']=='PARTIAL_REPLAY_CAPTURE'
    assert ambiguous['visual_contrast']['replay']=='unverified'
    assert ambiguous['visual_contrast']['reported_current_picture']=='normal'
    outcome_result.update(player_identity_verified=True,reported_outcome='normal')
    (out/'result.json').write_text(json.dumps(outcome_result))
    assert M['compare_session'](root)['classification']=='FAULT_NOT_REPRODUCED'
    import shutil
    shutil.rmtree(out)
    save_doc('transition',original_transition)
    (root/'transition/result.json').write_text(original_transition_result)
    # Validate raw baseline *before* any Stop, not only in offline analysis.
    context={'boot_id':'boot','checked_policy':{'test':'0'}}
    scan=' '.join(f'{k}={v}' for k,v in docs['reference']['state'].items())
    with mock.patch.dict(A,read=lambda _:scan),mock.patch.object(M['validate_live_baseline'].__globals__['hashlib'],'sha256',return_value=SimpleNamespace(hexdigest=lambda:'b'*64)):
        M['validate_live_baseline'](root,context,'test')
        corrupt=copy.deepcopy(original_ref);corrupt['pages']=['bad raw data']
        (root/'reference/first.json').write_text(json.dumps(corrupt))
        try:M['validate_live_baseline'](root,context,'test')
        except ValueError:pass
        else:raise AssertionError('Corrupt normal baseline accepted before Stop')
    save_doc('reference',original_ref)
    d=docs['transition'];next(r for r in d['records'] if r['source']==1 and r['kind']==2 and r['reg']==1)['value']=8
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
    execute=M['execute'];g=execute.__globals__;old={key:g[key] for key in ('preflight','rpc','wait_for','LiveRows','AUDIT','validate_live_baseline')}
    requests=[]
    context=dict(boot_id='boot',decoder='ammvdec_h264',disable='0',global_output='1')
    def fake_rpc(method,params,log):
        requests.append(method)
        return {'item':{'file':'test'}} if method=='Player.GetItem' else 'OK'
    def fake_arm(folder,phase):
        (folder/(phase+'.owner.json')).write_text(json.dumps(dict(generation=1,boot_id='boot')))
    def fake_freeze(folder,phase,hdmi=False):
        (folder/(phase+'.json')).write_text(json.dumps(dict(state=dict(overflow=0),records=[])))
    def timeout(*_args,**_kwargs):
        if _args[1] is M['reference_ready']:return
        raise RuntimeError('test missing asynchronous cleanup')
    try:
        g.update(preflight=lambda **_:context,rpc=fake_rpc,wait_for=timeout,LiveRows=lambda _:SimpleNamespace(rows=[],require_phase=lambda _:None),validate_live_baseline=lambda *_:None,
                 AUDIT=dict(A,arm=fake_arm,freeze=fake_freeze,snapshot=lambda:context))
        try:
            with mock.patch.object(g['subprocess'], 'run'), contextlib.redirect_stdout(io.StringIO()):
                execute(SimpleNamespace(run=root,action='transition',file='test',timeout=.01,confirmed_normal=False))
        except RuntimeError:pass
        else:raise AssertionError('Timeout reported success')
        assert requests==['Player.GetItem','Player.Stop']
        assert json.loads((root/'transition/result.json').read_text())['status']=='INCOMPLETE'
        requests.clear()
        g['validate_live_baseline']=old['validate_live_baseline']
        second=root/'bad-baseline';(second/'reference').mkdir(parents=True)
        (second/'reference/result.json').write_text((root/'reference/result.json').read_text())
        try:
            with mock.patch.object(g['subprocess'],'run'),contextlib.redirect_stdout(io.StringIO()):
                execute(SimpleNamespace(run=second,action='transition',file='test',timeout=.01,confirmed_normal=False))
        except RuntimeError:pass
        else:raise AssertionError('Invalid raw baseline reported success')
        assert not requests  # Not even Player.GetItem or SetVolume; never Stop.

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
#define VFRAME_FLAG_FAKE_FRAME 0x1000
#define E900_PB_LIFE 1
#define E900_PB_STATE 2
#define E900_PB_FIRST_FRAME 3
static unsigned e900_hdr_session=1,notes,last;
struct vframe_s {unsigned flag,index,pts;};
static void e900_playback_note(unsigned s,unsigned k,unsigned session,unsigned b,unsigned h,unsigned r,unsigned v,unsigned a){assert(s==1&&k==2&&r==3);(void)b;(void)h;(void)v;(void)a;notes++;last=session;}
static void toggle(struct vframe_s *vf){
'''+block+r'''
}
int main(void){struct vframe_s vf={0x10,1,100}; /* real SYNCFRAME, not fake */
 toggle(&vf);toggle(&vf);assert(notes==1&&last==1);
 e900_hdr_session=2;vf.flag=VFRAME_FLAG_FAKE_FRAME;toggle(&vf);assert(notes==1);
 vf.flag=0x10;toggle(&vf);assert(notes==2&&last==2);return 0;}
'''
with tempfile.TemporaryDirectory() as directory:
    c=Path(directory)/'test.c';c.write_text(source);exe=Path(directory)/'test'
    subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: actual session-first toggle note repeats on replay sessions, excludes fake frames and preserves upstream first_picture policy')

# Leftover experimental or verbose state must be rejected before media RPC.
def policy(module,name):
    if name in ('gxlx2_pixel_scan','gxlx2_edge_scan'):return 'status=0 owned=0'
    return 'N' if name in ('gxlx2_g12_mif','gxlx2_gen3_clear_high','gxlx2_osd_blender_only') else '0'
assert M['checked_policy'](policy)
for bad in ('gxlx2_gen3_clear_high','gxlx2_osd_blender_only','gxlx2_debug_events'):
    try:M['checked_policy'](lambda module,name:'1' if name==bad else policy(module,name))
    except RuntimeError:pass
    else:raise AssertionError('Leftover experiment/logging state accepted')
print('PASS: display experiment and verbose-channel preflight checks reject leftover state')

# session is a lifecycle epoch: disable-for-next may advance it without a new
# provider registration. Complete records in that new epoch must remain usable.
epoch_rows=copy.deepcopy(covered(1))
for r in epoch_rows[1:]:r['session']=9
epoch_rows.insert(1,row(1,1,2,2,session=9))
for i,r in enumerate(epoch_rows):r['index']=i
coverage=M['display_coverage'](epoch_rows)
assert coverage['complete'] and coverage['registration_epoch']==8 and coverage['display_epoch']==9
epoch_rows.append(row(len(epoch_rows),1,2,1,session=10))
assert not M['display_coverage'](epoch_rows)['complete']

# Exercise actual RPC parsing without network: persistent notifications cannot
# extend the total deadline or evade the aggregate byte bound; split UTF-8 is
# valid input, and a late matching reply is still a timeout.
class Clock:
    CLOCK_BOOTTIME=7
    def __init__(self):self.now=0
    def monotonic(self):return self.now
    def clock_gettime_ns(self,_):return int(self.now*1e9)
    def sleep(self,n):self.now+=n
class Connection:
    def __init__(self,clock,chunks,step=0):self.clock=clock;self.chunks=iter(chunks);self.step=step;self.reads=0
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def settimeout(self,n):assert n>0
    def sendall(self,_):pass
    def recv(self,_):self.reads+=1;self.clock.now+=self.step;return next(self.chunks,b'')
g=M['rpc'].__globals__
notification=b'{"jsonrpc":"2.0","method":"notice"}'
for step,count in ((1,100),(0,10000)):
    clock=Clock();conn=Connection(clock,[notification]*count,step)
    with mock.patch.dict(g,time=clock),mock.patch.object(g['socket'],'create_connection',return_value=conn):
        try:M['rpc']('test',{},[])
        except (TimeoutError,RuntimeError):pass
        else:raise AssertionError('Notification stream evaded RPC bounds')
    assert conn.reads<count
clock=Clock();reply=json.dumps({'id':71,'result':{'text':'中文'}},ensure_ascii=False).encode()
conn=Connection(clock,[bytes([b]) for b in reply])
with mock.patch.dict(g,time=clock),mock.patch.object(g['socket'],'create_connection',return_value=conn):
    assert M['rpc']('test',{},[])=={'text':'中文'}
clock=Clock();conn=Connection(clock,[b'{"id":71,"result":"OK"}'],6)
with mock.patch.dict(g,time=clock),mock.patch.object(g['socket'],'create_connection',return_value=conn):
    try:M['rpc']('test',{},[])
    except TimeoutError:pass
    else:raise AssertionError('Late matching response accepted')
clock=Clock()
def slow_poll():clock.now+=2;return []
with mock.patch.dict(g,time=clock),mock.patch.dict(A,snapshot=lambda:{}):
    try:M['wait_for'](SimpleNamespace(poll=slow_poll),lambda *_:True,1)
    except RuntimeError:pass
    else:raise AssertionError('Late predicate accepted after timeout')
print('PASS: lifecycle epoch changes, bounded notification streams, split UTF-8, late replies and slow polling deadlines')

# Continuous transitions use the stop owner; nevertheless a replay endpoint
# needs guarded TX status. Real Stop must not read any TX registers.
calls_tx=[]
with mock.patch.dict(A,hdmi_snapshot=lambda c:calls_tx.append(c) or {'status':'test_guarded'}):
    assert M['transition_hdmi']({'records':[]})['status']=='skipped_real_stop'
    assert not calls_tx
    d={'records':[row(0,3,0,3,kind=1)],'after':{'disable':'0'}}
    assert M['transition_hdmi'](d)['status']=='test_guarded' and calls_tx==[d['after']]
print('PASS: continuous replay endpoint invokes existing guarded HDMI collector; Stop endpoint performs no TX read')

# A ready-looking but frozen/full recorder must not be followed by Player.Open.
for text in ('generation=1 status=2 count=10 capacity=65536 overflow=0 phase=3',
             'generation=1 status=1 count=65536 capacity=65536 overflow=0 phase=3'):
    t=M['LiveRows'](1,lambda _:text,lambda *_:None)
    try:t.require_phase(3)
    except RuntimeError:pass
    else:raise AssertionError('Inactive/full recorder allowed a media action')

# Execute outcome and transition code with no hardware access. Outcome accepts
# zero FIFO as observed failure and issues only GetItem, never Open/Stop/Volume.
for scenario in ('outcome','unpaired_outcome','unpaired_type_outcome','transition'):
    action='outcome' if scenario.startswith('unpaired') else scenario
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'reference').mkdir()
        (root/'reference/result.json').write_text(json.dumps(dict(status='COVERED_REQUIRES_VISUAL',boot_id='boot',file='test',confirmed_normal=True)))
        g=M['execute'].__globals__;keys=('preflight','rpc','wait_for','LiveRows','AUDIT','validate_live_baseline','compare_session')
        old={key:g[key] for key in keys};requests=[]
        context={'boot_id':'boot','decoder':'ammvdec_h264','disable':'0','global':'1','checked_policy':{'test':'0'}}
        def fake_rpc(method,params,log):
            requests.append(method)
            return {'item':{'file':'test'}} if method=='Player.GetItem' else 'OK'
        def fake_arm(folder,phase):
            (folder/(phase+'.owner.json')).write_text(json.dumps({'boot_id':'boot','generation':1}))
        rs=[row(i,3,reg,value=0,source=5,kind=7) for i,reg in enumerate(SAMPLES)]
        def fake_freeze(folder,phase,hdmi=False):
            (folder/(phase+'.json')).write_text(json.dumps({'state':{'overflow':0},'records':rs,'after':context}))
        class FakeTrace:
            def __init__(self,_):self.rows=[]
            def require_phase(self,phase):
                if phase==3:raise RuntimeError('test recorder froze before replay')
        try:
            g.update(preflight=lambda **_:context,rpc=fake_rpc,wait_for=lambda *_args,**_kwargs:None,
                     LiveRows=FakeTrace,validate_live_baseline=lambda *_:None,
                     compare_session=(lambda _:(_ for _ in ()).throw((TypeError if scenario=='unpaired_type_outcome' else ValueError)('prior export broken'))) if scenario.startswith('unpaired') else (lambda _:{'boot_id':'boot','file':'test'}),
                     AUDIT=dict(A,arm=fake_arm,freeze=fake_freeze,snapshot=lambda:context,write=lambda *_:None))
            try:
                with mock.patch.object(g['subprocess'],'run'),contextlib.redirect_stdout(io.StringIO()):
                    M['execute'](SimpleNamespace(run=root,action=action,file='test',timeout=.01,confirmed_normal=False,reported_outcome='black'))
            except RuntimeError:
                assert action=='transition'
            result=json.loads((root/action/'result.json').read_text())
            if action=='outcome':
                assert requests==['Player.GetItem']
                assert result['reported_outcome']=='black' and result['status']=='COVERED_REQUIRES_VISUAL'
                assert result['pairing_verified']==(not scenario.startswith('unpaired'))
            else:
                assert requests==['Player.GetItem','Player.Stop']
                assert result['status']=='INCOMPLETE'
        finally:g.update(old)
print('PASS: invalid baseline blocks Stop; missing replay calls remain analyzable; confirmed black/zero FIFO snapshots perform no media mutation; frozen recorder blocks replay')

# Normal/black grouping is user-reported: FIFO zero must never exclude a
# normal counterexample or be silently reclassified as a fault.
ctx={'disable':'0','global':'1','decoder':'ammvdec_h264'}
recent=[row(i,2,reg,value=5 if reg==0x1d28 else 0,source=5,kind=7) for i,reg in enumerate(tuple(r for r in REGS if r!=0x1d28)+(0x1d28,0x1d28))]
assert M['reference_ready'](recent,ctx)
recent += [row(len(recent)+i,2,0x1d28,value=0,source=5,kind=7) for i in range(2)]
assert M['reference_ready'](recent,ctx)
assert not M['reference_ready'](recent,dict(ctx,decoder='No vdec.'))

# Read-only outcome collection must not require global_output to be healthy;
# a failed global restore is a state to preserve, not a reason to fix/replay.
class Param:
    def __init__(self,*parts):self.name='/'.join(map(str,parts))
    def is_file(self):return True
    def read_text(self):
        return {'gxlx2_playback_live_api':'2','gxlx2_hw_init_status':'2','gxlx2_stage_samples':'0','enable':'1,0'}[self.name.rsplit('/',1)[-1]]
g=M['preflight'].__globals__
with mock.patch.dict(g,Path=Param,checked_policy=lambda:{'test':'0'}),mock.patch.dict(A,
        read=lambda _:'generation=3 status=2 count=10 capacity=65536 overflow=0 phase=3',
        snapshot=lambda:{'hdr_experiment':'N','hold':'0','global':'0'}):
    try:M['preflight']()
    except RuntimeError:pass
    else:raise AssertionError('Unhealthy global output permitted a fault-triggering action')
    assert M['preflight'](observation=True)['global']=='0'
print('PASS: normal/black sampling uses identical value-neutral criteria; read-only outcome admits failed global restore without allowing a new playback trial')

# Advertised old API must fail before media actions; a sparse old read set
# cannot silently stand in for the newly required GEN2/GEN3/matrix scope.
sparse=[r for r in recent if r['reg'] not in (0x1a6d,0x1aa7,0x1a63,0x1d5f)]
assert not M['readbacks_available'](sparse)
class OldParam(Param):
    def read_text(self):
        if self.name.endswith('gxlx2_playback_live_api'):return '1'
        return super().read_text()
g=M['preflight'].__globals__
with mock.patch.dict(g,Path=OldParam):
    try:M['preflight']()
    except RuntimeError as error:assert 'v2' in str(error)
    else:raise AssertionError('Old API accepted without four required readbacks')
print('PASS: Stop-phase write provenance survives replay; broken earlier exports do not suppress unpaired read-only outcome; old API/sparse coverage rejected')
