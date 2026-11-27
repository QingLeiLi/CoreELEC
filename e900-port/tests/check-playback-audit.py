#!/usr/bin/env python3
"""Reject incomplete/raw-tampered replay evidence; preserve repeated writes."""
import copy
import json
from pathlib import Path
import runpy
import tempfile

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/e900-playback-audit.py'))
def row(index, phase, reg, value, kind=4):
    return dict(zip(M['FIELDS'], [index, phase, 100+index, 4, kind, phase, phase, 1, 1, reg, value, index]))
def doc(phase, values):
    rows = [row(0, phase, 0, phase, 1)]
    rows += [row(i+1, phase, reg, value) for i, (reg, value) in enumerate(values)]
    state = dict(generation=phase, status=2, count=len(rows), capacity=8192, overflow=0, phase=phase)
    text = '\n'.join(' '.join(str(r[k]) if i<2 else format(r[k], 'x') for i,k in enumerate(M['FIELDS'])) for r in rows)
    return dict(boot_id='boot', state=state, pages=[text], records=rows)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    (root/'manifest.json').write_text(json.dumps({'boot_id':'boot'}))
    docs = {'first':doc(1, [(0x1d04,7),(0x1d04,7),(0x3800,1)]),
            'stop':doc(2, []), 'replay':doc(3, [(0x1d04,7),(0x3801,2)])}
    def save():
        for name, d in docs.items(): (root/(name+'.json')).write_text(json.dumps(d))
    def rejects(key, mutate):
        prior = copy.deepcopy(docs[key]); mutate(docs[key]); save()
        try: M['compare'](root)
        except ValueError: pass
        else: raise AssertionError('Invalid evidence accepted')
        docs[key] = prior
    save(); result=M['compare'](root)
    assert result['changed_ordered_values']['direct_write:1d04'] == {'first':[7,7], 'replay':[7]}
    assert 'direct_write:3800' in result['first_only'] and 'direct_write:3801' in result['replay_only']
    assert result['classification']=='REVIEW_REQUIRED'
    rejects('first', lambda d:d['state'].update(overflow=1))
    rejects('replay', lambda d:d.update(boot_id='foreign'))
    rejects('replay', lambda d:d['records'][1].update(value=999))
    rejects('stop', lambda d:d['pages'].clear())
    rejects('first', lambda d:d['state'].update(generation=22))
# Parse the independent table stream, including mutable OSD overwrite order.
rows = [row(0, 1, 0, 0, 3), row(1, 1, 0x1a10, 7), row(2, 1, 0x1a10, 8), row(3, 1, 0, 1, 5)]
for r in rows: r.update(source=3, batch=7, handle=3)
rows[0]['aux'] = 500
rows[1]['aux'] = rows[2]['aux'] = 4
rows[3]['aux'] = 6
st = dict(generation=1, count=4)
def pages(values):
    return ['\n'.join(' '.join(str(r[k]) if i<2 else format(r[k], 'x') for i,k in enumerate(M['FIELDS'])) for r in values)]
assert len(M['decode'](pages(rows), st)) == 4
bad = copy.deepcopy(rows); bad[0]['source'] = 2
for r in bad: r['source'] = 2
try: M['decode'](pages(bad), st)
except ValueError: pass
else: raise AssertionError('Immutable table accepted duplicate item')
bad = copy.deepcopy(rows); bad[1]['batch'] = 99
try: M['decode'](pages(bad), st)
except ValueError: pass
else: raise AssertionError('Orphan word accepted')
print('PASS: raw pages/boot/phase/overflow and batch ownership validated; repeated values/mutable OSD writes and missing baseline preserved; no hardware verdict inferred')

# Audited TX reads never run config/AVMUTE on an inactive or disconnected output.
context = {'global':'1','disable':'0','decoder':'ammvdec_h264','mode':'1080p60hz'}
calls=[]
def tx_get(name):
    calls.append(name)
    return {'hpd_state':'1','config':'test config','avmute':'0'}[name]
report=M['hdmi_snapshot'](context,tx_get)
assert report['status']=='collected_status_only' and calls==['hpd_state','config','avmute']
calls.clear()
assert M['hdmi_snapshot'](dict(context,disable='1'),tx_get)['status']=='skipped_inactive'
assert calls==['hpd_state']
calls.clear()
assert M['hdmi_snapshot'](context,lambda name:'0')['status']=='skipped_inactive'
print('PASS: TX getters require active H264/global/layer/mode/HPD; status never treated as physical pixel proof')
