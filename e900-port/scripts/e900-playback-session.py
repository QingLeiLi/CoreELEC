#!/usr/bin/env python3
"""Explicit first/reference/Stop-replay experiments; fail closed on missing coverage."""
import argparse
import codecs
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import runpy
import socket
import subprocess
import time

AUDIT = runpy.run_path(str(Path(__file__).with_name('e900-playback-audit.py')))
# Pinned vframe_receiver.h: PROVIDER_UNREG=1, PROVIDER_REG=8.
UNREG, REG = 1, 8
LIVE_API_VERSION = 2
REQUIRED_READBACKS = (0x1a50, 0x1d26, 0x1d28, 0x3800, 0x1a6d, 0x1aa7, 0x1a63, 0x1d5f)


def create(path, value):
    AUDIT['new_json'](path, value)


def calls(rows, code):
    return [r for r in rows if r['source'] == 1 and r['kind'] == 2 and r['reg'] == code]


def display_coverage(rows):
    registrations = [r for r in calls(rows, 1) if r['value'] == REG]
    if not registrations:
        return {'complete': False, 'missing': ['provider_registration']}
    provider = registrations[-1]
    rows = [r for r in rows if r['index'] >= provider['index']]
    # This counter is a software lifecycle epoch, not provider identity:
    # _video_set_disable(nonzero), reset and unregister also increment it.
    boundaries = [r for r in rows if r['source']==1 and r['kind']==2 and r['reg'] in (1,2,3)]
    epoch = boundaries[-1]['session']
    rows = [r for r in rows if r['session'] == epoch]
    required = {3: 'first_frame', 11: 'dcu_entry', 13: 'pps_entry', 18: 'csc_return'}
    missing = [name for code, name in required.items() if not calls(rows, code)]
    # An observed no-op return is coverage, not proof of configuration success.
    # vd_scaler_setting's unsupported return (15) replaces its normal exit (14).
    for entry, exits in ((11, (12,)), (13, (14, 15))):
        pending = 0
        invalid = False
        for r in rows:
            if r['source'] != 1 or r['kind'] != 2:
                continue
            if r['reg'] == entry:
                pending += 1
            elif r['reg'] in exits:
                pending -= 1
                invalid |= pending < 0
        if pending or invalid:
            missing.append('unbalanced_'+required[entry])
    hdr_pending = []
    for r in rows:
        if r['source'] != 1 or r['kind'] != 2 or r['handle'] != 1:
            continue
        if r['reg'] == 8:
            hdr_pending.append(r['value'])
        elif r['reg'] == 9:
            if not hdr_pending or hdr_pending.pop(0) != r['value']:
                missing.append('unmatched_hdr_submission')
    if hdr_pending:
        missing.append('unreturned_hdr_request')
    for code, known in ((15, (0,)), (16, (1,)), (17, (1,2)), (18, tuple(range(1,8)))):
        if any(r['value'] not in known for r in calls(rows, code)):
            missing.append('unknown_return_reason_'+str(code))
    reads = {r['reg'] for r in rows if r['source'] == 5 and r['kind'] == 7}
    missing += ['read_'+hex(reg) for reg in REQUIRED_READBACKS if reg not in reads]
    return {'complete': not missing, 'missing': missing,
            'display_epoch': epoch, 'registration_epoch': provider['session'],
            'disposition': {'dcu_skipped': [r['value'] for r in calls(rows,16)],
                            'pps_unsupported': bool(calls(rows,15)),
                            'pps_skipped': [r['value'] for r in calls(rows,17)],
                            'csc_returns': sorted({r['value'] for r in calls(rows,18)}),
                            'hdr_requested': bool([r for r in calls(rows,8) if r['handle']==1]),
                            'hdr_flush_disabled': bool([r for r in calls(rows,10) if r['handle']==1])},
            'scope': 'Selected software boundaries and guarded reads, not pixel proof'}


def stopped(rows, context):
    return (context.get('decoder') == 'No vdec.' and context.get('disable') == '1'
            and any(r['value'] == UNREG for r in calls(rows, 1))
            and any(r['value'] == 1 for r in calls(rows, 2)))


def readbacks_available(rows):
    # Group labels come from the user, never FIFO magnitude. Identical
    # structural gates retain zero-valued normal and black counterexamples.
    reads = [r for r in rows if r['source'] == 5 and r['kind'] == 7]
    if not reads:
        return False
    epoch = reads[-1]['session']
    boundaries=[r for r in rows if r['source']==1 and r['kind']==2 and r['reg'] in (1,2,3)]
    if boundaries and boundaries[-1]['session']!=epoch:
        return False
    reads=[r for r in reads if r['session']==epoch]
    fifo=[r for r in reads if r['reg']==0x1d28]
    return (len(fifo)>=2
            and all(any(r['reg']==reg for r in reads) for reg in REQUIRED_READBACKS))


def reference_ready(rows, context):
    # These are preconditions for deliberately stopping the known test video,
    # never preconditions for observing a failure after it has happened.
    return (context.get('disable')=='0' and context.get('global')=='1'
            and isinstance(context.get('decoder'),str) and 'ammvdec_h264' in context['decoder']
            and readbacks_available(rows))


def transition_hdmi(doc):
    # A continuous transition is exported through the old "stop" owner, whose
    # freeze() deliberately skips TX reads. Only its phase-3 endpoint is replay.
    if not any(r['source']==1 and r['kind']==1 and r['phase']==3 for r in doc['records']):
        return {'status': 'skipped_real_stop'}
    return AUDIT['hdmi_snapshot'](doc['after'])


class LiveRows:
    """Read immutable append-only prefixes; never re-arm to make space."""
    def __init__(self, generation, reader=None, writer=None):
        self.generation = generation
        self.read = reader or AUDIT['read']
        self.write = writer or AUDIT['write']
        self.rows = []

    def require_phase(self, phase):
        current = AUDIT['state'](self.read('scan'))
        if (current['generation']!=self.generation or current['status']!=1 or current['overflow']
                or current['phase']!=phase or current['count']>=current['capacity']):
            raise RuntimeError('Recorder no longer owns the active phase; no media action permitted')

    def poll(self):
        before = AUDIT['state'](self.read('scan'))
        if before['generation'] != self.generation or before['overflow'] or before['status'] != 1:
            raise RuntimeError('Foreign/frozen/overflowed recorder; keep evidence and stop')
        count = before['count']
        if count < len(self.rows):
            raise RuntimeError('Live prefix shrank')
        for page in range(len(self.rows)//8, (count+7)//8):
            self.write('page', page)
            for line in self.read('data').splitlines():
                words = line.split()
                if not words:
                    continue
                if len(words) != len(AUDIT['FIELDS']):
                    raise RuntimeError('Malformed live row')
                r = {key: int(value, 10 if i < 2 else 16)
                     for i, (key, value) in enumerate(zip(AUDIT['FIELDS'], words))}
                if r['generation'] != self.generation:
                    raise RuntimeError('Live row generation replaced')
                if r['index'] < len(self.rows) or r['index'] >= count:
                    continue
                if r['index'] != len(self.rows):
                    raise RuntimeError('Gap in live prefix')
                self.rows.append(r)
        after = AUDIT['state'](self.read('scan'))
        if after['generation'] != self.generation or after['overflow'] or after['status'] != 1:
            raise RuntimeError('Recorder changed during live read')
        if len(self.rows) != count:
            raise RuntimeError('Incomplete live prefix')
        return self.rows


def rpc(method, params, log):
    item = {'method': method, 'params': params, 'send_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
    log.append(item)
    deadline = time.monotonic()+5
    try:
        with socket.create_connection(('127.0.0.1', 9090), 3) as conn:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RPC deadline exceeded before send')
            conn.settimeout(remaining)
            conn.sendall(json.dumps({'jsonrpc': '2.0', 'id': 71, 'method': method, 'params': params}).encode())
            item['sent'] = True
            buf = ''
            received = 0
            decoder = codecs.getincrementaldecoder('utf-8')()
            while received < 65536:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('RPC total deadline exceeded')
                conn.settimeout(remaining)
                chunk = conn.recv(8192)
                if not chunk:
                    raise RuntimeError('Incomplete RPC response')
                received += len(chunk)
                if received > 65536:
                    raise RuntimeError('RPC total response limit exceeded')
                buf += decoder.decode(chunk)
                while buf.strip():
                    try:
                        value, end = json.JSONDecoder().raw_decode(buf.lstrip())
                    except ValueError:
                        break
                    buf = buf.lstrip()[end:]
                    if value.get('id') != 71:
                        continue
                    item['response'] = value
                    if 'error' in value:
                        raise RuntimeError(str(value['error']))
                    if time.monotonic() >= deadline:
                        raise TimeoutError('RPC reply arrived after total deadline')
                    return value['result']
        raise RuntimeError('RPC response too large')
    except Exception as error:
        item['error'] = str(error)
        raise
    finally:
        item['return_boottime_ns'] = time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def wait_for(trace, predicate, timeout, stable=0):
    deadline, since = time.monotonic()+timeout, None
    while time.monotonic() < deadline:
        rows = trace.poll()
        ready = predicate(rows, AUDIT['snapshot']())
        if time.monotonic() >= deadline:
            break
        if ready:
            since = since if since is not None else time.monotonic()
            if time.monotonic()-since >= stable:
                return
        else:
            since = None
        time.sleep(.02)
    raise RuntimeError('Coverage/state timeout; no further media action permitted')


def checked_policy(reader=None):
    reader = reader or (lambda module, name: Path('/sys/module',module,'parameters',name).read_text().strip())
    values = {}
    for module, name in (('amvideo','gxlx2_g12_mif'), ('amvideo','gxlx2_gen3_clear_high'),
                         ('fb','gxlx2_osd_blender_only')):
        value = reader(module,name)
        values[module+'.'+name] = value
        if value not in ('N','0'):
            raise RuntimeError('Display experiment still enabled: '+module+'.'+name)
    for name in ('gxlx2_pixel_scan','gxlx2_edge_scan'):
        value = dict(word.split('=',1) for word in reader('amvideo',name).split() if '=' in word)
        if value.get('status') not in ('0','3','4') or value.get('owned','0') != '0':
            raise RuntimeError('Pixel/edge probe active or not safely retired: '+name)
        values['amvideo.'+name] = {key:value.get(key) for key in ('status','owned')}
    for module in ('amvideo','am_vecm','rdma','rdma_mgr','fb','register_ops','di','vpu'):
        for name in ('gxlx2_debug_events','gxlx2_gen3_rmw_events'):
            try:
                value = reader(module,name)
            except FileNotFoundError:
                continue  # This optional logging knob is not compiled in.
            values[module+'.'+name] = value
            if value != '0':
                raise RuntimeError('Verbose event channel active: '+module+'.'+name)
    return values


def preflight(observation=False):
    api = Path('/sys/module/rdma_mgr/parameters/gxlx2_playback_live_api')
    if not api.is_file() or api.read_text().strip() != str(LIVE_API_VERSION):
        raise RuntimeError('Requires updated 0043 live API v2 (27 readbacks); no media action performed')
    status = AUDIT['state'](AUDIT['read']('scan'))
    if status['status'] == 1 or status['capacity'] < 65536:
        raise RuntimeError('Busy recorder or insufficient supported capacity')
    c = AUDIT['snapshot']()
    if (c.get('hdr_experiment') not in ('N', '0') or c.get('hold') != '0'
            or (not observation and c.get('global') != '1')):
        raise RuntimeError('Nondefault display policy; refusing experiment')
    if Path('/sys/module/amvideo/parameters/gxlx2_hw_init_status').read_text().strip() != '2':
        raise RuntimeError('Video init incomplete')
    if Path('/sys/module/amvideo/parameters/gxlx2_stage_samples').read_text().strip() != '0':
        raise RuntimeError('Verbose legacy stage probes active')
    if Path('/sys/module/rdma/parameters/enable').read_text().strip() != '1,0':
        raise RuntimeError('RDMA policy differs from reference')
    c['checked_policy'] = checked_policy()
    c['playback_api'] = LIVE_API_VERSION
    return c


class StopHDRGuard:
    """Own the existing HDR-family flush switch only across asynchronous Stop."""
    def __init__(self, report, parameter=None):
        self.parameter = parameter or Path('/sys/module/am_vecm/parameters/disable_flush_flag')
        self.report = report
        self.active = False

    def set(self):
        if self.parameter.read_text().strip() != '0':
            raise RuntimeError('HDR flush switch is not zero; no Stop permitted')
        # Mark ownership before write: finally must restore even if readback fails.
        self.active = True
        self.parameter.write_text('1\n')
        self.report.append({'event':'stop_hdr_guard_set','value':self.parameter.read_text().strip(),
                            'boottime_ns':time.clock_gettime_ns(time.CLOCK_BOOTTIME)})
        if self.report[-1]['value'] != '1':
            raise RuntimeError('HDR Stop guard failed readback; no Stop permitted')

    def restore(self):
        if not self.active:
            return
        value = self.parameter.read_text().strip()
        if value not in ('0','1'):
            raise RuntimeError('HDR switch externally changed; refusing to overwrite')
        self.parameter.write_text('0\n')
        value = self.parameter.read_text().strip()
        self.report.append({'event':'stop_hdr_guard_restore','value':value,
                            'boottime_ns':time.clock_gettime_ns(time.CLOCK_BOOTTIME)})
        if value != '0':
            raise RuntimeError('HDR Stop guard restore failed; no replay permitted')
        self.active = False


def execute(args):
    context = preflight(observation=args.action=='outcome')
    args.run.mkdir(parents=True, exist_ok=True)
    folder = args.run/args.action
    folder.mkdir(exist_ok=False)
    phase = 'stop' if args.action == 'transition' else 'replay' if args.action == 'outcome' else 'first'
    report = {'status': 'INCOMPLETE', 'action': args.action, 'boot_id': context['boot_id'],
              'rpc': [], 'file': args.file, 'before': context,
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'kernel_version': platform.uname().version, 'timeout_seconds': args.timeout}
    if args.action == 'outcome':
        report['reported_outcome'] = args.reported_outcome
    armed = False
    stop_guard = None
    if getattr(args, 'stop_hdr_flush_guard', False):
        if args.action != 'transition':
            raise ValueError('HDR Stop guard is valid only for transition')
        report['intervention'] = 'suppress_hdr_family_flush_during_stop_only'
        report['intervention_events'] = []
        stop_guard = StopHDRGuard(report['intervention_events'])
    try:
        if args.action == 'first':
            if context['decoder'] != 'No vdec.':
                raise RuntimeError('First playback requires no existing decoder')
        elif args.action == 'outcome':
            try:
                previous = compare_session(args.run)
                if previous['boot_id'] != context['boot_id'] or previous['file'] != args.file:
                    raise ValueError('Outcome belongs to another boot/file')
                report['pairing_verified'] = True
            except Exception as error:
                # Broken prior exports cannot suppress a read-only snapshot of
                # the current reported failure. Keep it explicitly unpaired.
                report['pairing_verified'] = False
                report['pairing_error'] = str(error)
            # This is an observation, never a new playback action. Identity
            # failure is retained as missing context, not repaired by replaying.
            try:
                active = rpc('Player.GetItem', {'playerid':1,'properties':['file']}, report['rpc'])
                report['player_identity_verified'] = active.get('item',{}).get('file') == args.file
            except Exception as error:
                report['player_identity_error'] = str(error)
                report['player_identity_verified'] = False
        else:
            previous = json.loads((args.run/('reference' if args.action == 'transition' else 'first')/'result.json').read_text())
            if previous['status'] != 'COVERED_REQUIRES_VISUAL' or previous['boot_id'] != context['boot_id'] or previous['file'] != args.file:
                raise RuntimeError('Missing covered same-boot/file prerequisite')
            if args.action == 'reference' and not args.confirmed_normal:
                raise RuntimeError('Explicit normal visual confirmation required')
            if args.action == 'transition' and not previous.get('confirmed_normal'):
                raise RuntimeError('No independent confirmed normal reference')
            if args.action == 'transition':
                validate_live_baseline(args.run,context,args.file)
            active = rpc('Player.GetItem', {'playerid': 1, 'properties': ['file']}, report['rpc'])
            if active.get('item', {}).get('file') != args.file or context['disable'] != '0':
                raise RuntimeError('Baseline player/file/layer changed')
        # Establish volume once before first playback; measurement phases must
        # not issue an extra application/UI mutation between the comparisons.
        if args.action == 'first':
            rpc('Application.SetVolume', {'volume': 0}, report['rpc'])
        with (folder/'before.dmesg').open('w') as stream:
            subprocess.run(['dmesg'], stdout=stream, check=True)
        AUDIT['arm'](folder, phase)
        owner = json.loads((folder/(phase+'.owner.json')).read_text())
        armed = True
        trace = LiveRows(owner['generation'])
        if args.action == 'first':
            trace.require_phase(1)
            rpc('Player.Open', {'item': {'file': args.file}}, report['rpc'])
            wait_for(trace, lambda rows, c: display_coverage(rows)['complete'] and c['disable']=='0', args.timeout, stable=.3)
        elif args.action == 'reference':
            # The user already confirmed the physical picture; collect a separate
            # guarded reference before issuing any Stop. No playback action here.
            wait_for(trace, reference_ready, args.timeout)
            report['confirmed_normal'] = True
        elif args.action == 'outcome':
            wait_for(trace, lambda rows,c:readbacks_available(rows),args.timeout)
        else:
            trace.require_phase(2)
            # Recheck normal reads inside the same continuous window that will
            # contain Stop. A formerly healthy sample is not a fresh baseline.
            wait_for(trace, reference_ready,args.timeout)
            report['pre_stop_reference']={'rows':len(trace.rows),'context':AUDIT['snapshot']()}
            trace.require_phase(2)
            if stop_guard:
                stop_guard.set()
            rpc('Player.Stop', {'playerid': 1}, report['rpc'])
            wait_for(trace, stopped, args.timeout, stable=.3)
            report['stop_boundary'] = {'rows': len(trace.rows), 'context': AUDIT['snapshot'](),
                'scope': 'Provider/disable observed, No vdec and disable=1 stable 300ms; not proof every delayed work item completed'}
            # Same generation, no freeze/re-arm/export gap across Stop→replay.
            if stop_guard:
                stop_guard.restore()
            AUDIT['write']('phase', 3)
            trace.require_phase(3)
            rpc('Player.Open', {'item': {'file': args.file}}, report['rpc'])
            wait_for(trace, lambda rows, c: display_coverage([r for r in rows if r['phase']==3])['complete'] and c['disable']=='0', args.timeout, stable=.3)
        report['status'] = 'COVERED_REQUIRES_VISUAL'
    except Exception as error:
        report['error'] = str(error)
        report['primary_error'] = repr(error)
    finally:
        if stop_guard:
            try:
                stop_guard.restore()
            except Exception as error:
                report.update(status='INCOMPLETE', cleanup_error=str(error))
        if not armed and (folder/(phase+'.owner.json')).exists():
            # arm() can fail after claiming a generation (e.g. snapshot I/O).
            # Let freeze() verify ownership; never touch an unowned recorder.
            try:
                owner = json.loads((folder/(phase+'.owner.json')).read_text())
                armed = owner['boot_id'] == context['boot_id']
            except (OSError, ValueError, KeyError):
                pass
        if armed:
            try:
                AUDIT['freeze'](folder, phase, hdmi=(args.action!='transition'))
                doc = json.loads((folder/(phase+'.json')).read_text())
                report['state'] = doc['state']
                if args.action == 'transition' and stop_guard:
                    start = report.get('pre_stop_reference', {}).get('rows', len(doc['records']))
                    stop_rows = [r for r in doc['records'][start:] if r['phase']==2]
                    report['stop_hdr_guard_evidence'] = {
                        'disabled_calls':[r for r in stop_rows if r['source']==1 and r['reg']==10 and r['kind']==2],
                        'unblocked_requests':[r for r in stop_rows if r['source']==1 and r['reg'] in (8,9) and r['kind']==2],
                        'hdr_bank_writes':[r for r in stop_rows if r['source'] in (2,3,4) and r['kind']==4 and 0x3800<=r['reg']<=0x38ff],
                        'scope':'HDR family switch includes OSD/update entries; not VD1-only causal isolation'}
                if args.action == 'transition':
                    report['hdmi'] = transition_hdmi(doc)
                report['coverage'] = {str(p): display_coverage([r for r in doc['records'] if r['phase']==p]) for p in (1,3)}
                if doc['state']['overflow']:
                    report.update(status='INCOMPLETE', error='Recorder overflow')
                elif args.action in ('first', 'transition'):
                    required_phase = '3' if args.action == 'transition' else '1'
                    if not report['coverage'][required_phase]['complete']:
                        report.update(status='INCOMPLETE', error='Final frozen window lacks display coverage')
                elif args.action == 'outcome':
                    if not readbacks_available(doc['records']):
                        report.update(status='INCOMPLETE',error='Outcome readbacks unavailable; keep reported picture and software state')
                elif not reference_ready(doc['records'], doc['after']):
                    report.update(status='INCOMPLETE', error='Final frozen normal reference invalid')
            except Exception as error:
                report.update(status='INCOMPLETE', export_error=str(error))
        report['after'] = AUDIT['snapshot']()
        try:
            with (folder/'after.dmesg').open('w') as stream:
                subprocess.run(['dmesg'], stdout=stream, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            report['dmesg_error'] = str(error)
        create(folder/'result.json', report)
    print(json.dumps(report, indent=2))
    if report['status'] == 'INCOMPLETE':
        raise RuntimeError('Experiment incomplete; inspect saved result, do not continue')


def load_windows(run, names):
    results, docs, manifests = {}, {}, {}
    boot = None
    for name in names:
        phase = 'stop' if name == 'transition' else 'replay' if name == 'outcome' else 'first'
        folder = run/name
        result = json.loads((folder/'result.json').read_text())
        doc = json.loads((folder/(phase+'.json')).read_text())
        owner = json.loads((folder/(phase+'.owner.json')).read_text())
        manifest = json.loads((folder/'manifest.json').read_text())
        boot = boot or result['boot_id']
        if any(x['boot_id'] != boot for x in (result, doc, owner, manifest)):
            raise ValueError('Foreign boot in session')
        baseline = name in ('first','reference')
        if result.get('before',{}).get('playback_api')!=LIVE_API_VERSION:
            raise ValueError('Missing/mismatched recorded playback API contract')
        if doc['state']['status'] != 2 or (baseline and (result['status'] != 'COVERED_REQUIRES_VISUAL' or doc['state']['overflow'])):
            raise ValueError('Invalid normal baseline or unfrozen phase: '+name)
        if owner['generation'] != doc['state']['generation'] or result.get('state') != doc['state']:
            raise ValueError('Result/owner belongs to another frozen window')
        rows = AUDIT['decode'](doc['pages'], doc['state'])
        if rows != doc['records']:
            raise ValueError('Altered raw records')
        initial = 2 if name=='transition' else 3 if name=='outcome' else 1
        if not rows or rows[0]['source']!=1 or rows[0]['kind']!=1 or rows[0]['phase']!=initial:
            raise ValueError('Missing initial marker')
        if name!='transition' and (doc['state']['phase']!=initial or any(r['phase']!=initial for r in rows)):
            raise ValueError('Mixed window phases')
        results[name], docs[name], manifests[name] = result, doc, manifest
    for source, field in ((results,'runner_sha256'),(manifests,'collector_sha256')):
        hashes={r.get(field,'') for r in source.values()}
        if len(hashes)!=1 or len(next(iter(hashes)))!=64:
            raise ValueError('Missing/mixed tools: '+field)
    policies=[r['before'].get('checked_policy') for r in results.values()]
    if not policies[0] or any(policy!=policies[0] for policy in policies):
        raise ValueError('Missing/mixed experiment policy snapshots')
    if len({r['file'] for r in results.values()})!=1:
        raise ValueError('File changed')
    for left,right in zip(names,names[1:]):
        if (docs[right]['state']['generation']-docs[left]['state']['generation']) & 0xffffffff != 1:
            raise ValueError('Nonconsecutive experiment generations')
        if docs[right]['records'][0]['stamp'] < docs[left]['records'][-1]['stamp']:
            raise ValueError('Reordered/overlapping experiment windows')
    return results,docs


def validate_baseline(run):
    results,docs=load_windows(run,('first','reference'))
    if not any(r.get('method')=='Player.Open' and r.get('sent') and
               r.get('params',{}).get('item',{}).get('file')==results['first']['file']
               for r in results['first'].get('rpc',[])):
        raise ValueError('First-play request/file not evidenced')
    coverage=display_coverage(docs['first']['records'])
    if not coverage['complete']:
        raise ValueError('Missing first-play observation coverage')
    ref=docs['reference']
    if not results['reference'].get('confirmed_normal') or not reference_ready(ref['records'],ref['after']):
        raise ValueError('No confirmed guarded normal reference')
    if any(r['session']!=coverage['display_epoch'] for r in ref['records'] if r['source']==5 and r['kind']==7):
        raise ValueError('Normal reference belongs to another display epoch')
    return results,docs


def validate_live_baseline(run,context,file):
    results,docs=validate_baseline(run)
    ref=results['reference']
    if ref['boot_id']!=context['boot_id'] or ref['file']!=file or ref['before']['checked_policy']!=context['checked_policy']:
        raise ValueError('Live baseline identity/policy changed before Stop')
    if ref['runner_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Executor changed after reference')
    if AUDIT['state'](AUDIT['read']('scan'))!=docs['reference']['state']:
        raise ValueError('Recorder changed after normal reference; no Stop permitted')


def compare_session(run):
    validate_baseline(run)
    names=['first','reference','transition']
    if (run/'outcome/result.json').is_file():names.append('outcome')
    results,docs=load_windows(run,names)
    requests=results['transition'].get('rpc',[])
    opens=[i for i,r in enumerate(requests) if r.get('method')=='Player.Open' and r.get('sent')
           and r.get('params',{}).get('item',{}).get('file')==results['transition']['file']]
    stops=[i for i,r in enumerate(requests) if r.get('method')=='Player.Stop' and r.get('sent')]
    if len(opens)!=1 or len(stops)!=1 or stops[0]>=opens[0]:
        raise ValueError('No single evidenced Stop/replay request pair; do not label a Stop-only black screen as replay')
    rows=docs['transition']['records']
    split=next((i for i,r in enumerate(rows) if r['source']==1 and r['kind']==1 and r['phase']==3),None)
    if split is None or any(r['phase']!=2 for r in rows[:split]) or any(r['phase']!=3 for r in rows[split:]):
        raise ValueError('No intact Stop-to-replay boundary; replay comparison unavailable')
    if not stopped(rows[:split],results['transition'].get('stop_boundary',{}).get('context',{})):
        raise ValueError('Missing asynchronous Stop boundary')
    replay=rows[split:]
    before=results['transition'].get('pre_stop_reference',{})
    count=before.get('rows',0)
    if not 0<count<=split or not reference_ready(rows[:count],before.get('context',{})):
        raise ValueError('No fresh normal reference before Stop inside continuous window')
    coverage=display_coverage(replay)
    # Missing calls/reads may be the fault itself. Keep intact partial evidence
    # and its absence list; never require the failing path to have succeeded.
    classification='REPLAY_OUTCOME_PENDING'
    outcome=results.get('outcome')
    outcome_comparable = False
    identity_verified = False
    if outcome:
        if outcome.get('reported_outcome') not in ('black','normal'):
            raise ValueError('Missing explicit replay visual outcome')
        identity_verified = bool(outcome.get('pairing_verified')) and bool(outcome.get('player_identity_verified'))
        outcome_comparable = identity_verified and readbacks_available(
            docs['outcome']['records'])
        partial = (not coverage['complete'] or not outcome_comparable
                   or results['transition']['status']!='COVERED_REQUIRES_VISUAL'
                   or outcome['status']!='COVERED_REQUIRES_VISUAL'
                   or docs['transition']['state']['overflow'] or docs['outcome']['state']['overflow'])
        if outcome['reported_outcome']=='normal' and identity_verified:classification='FAULT_NOT_REPRODUCED'
        else:classification='PARTIAL_REPLAY_CAPTURE' if partial else 'REVIEW_REQUIRED'
    reference=docs['reference']
    live=lambda rs:[r for r in rs if r['source']==5 and r['kind']==7]
    after=docs.get('outcome')
    return {'classification':classification,'boot_id':results['first']['boot_id'],'file':results['first']['file'],
            'visual_contrast':{'first':'reference_normal_user_confirmed',
                               'replay':outcome.get('reported_outcome') if identity_verified else 'unverified' if outcome else 'not_reported',
                               'reported_current_picture':outcome.get('reported_outcome') if outcome else None},
            'replay_coverage':coverage,'transition_overflow':docs['transition']['state']['overflow'],
            'localization':AUDIT['localization'](docs['first']['records'],replay),
            'transition_readback_provenance':AUDIT['readback_provenance'](rows),
            'stop_lifecycle':[AUDIT['event_detail'](r) for r in rows[:split] if r['source']==1 and r['kind']==2],
            'software_state_timeline':{name:[AUDIT['blend_state'](r) for r in selected if r['source']==1 and r['kind']==2 and r['reg']==5]
                                       for name,selected in (('first',docs['first']['records']),('stop',rows[:split]),('replay',replay))},
            'intervention': results['transition'].get('intervention', 'none'),
            'intervention_events': results['transition'].get('intervention_events', []),
            'stop_hdr_guard_evidence': results['transition'].get('stop_hdr_guard_evidence'),
            'normal_reference_vs_confirmed_outcome':AUDIT['localization'](live(reference['records']),live(after['records'])) if after and outcome_comparable else None,
            'outcome_readbacks_comparable':outcome_comparable,
            'normal_reference_vs_replay_startup':AUDIT['localization'](live(reference['records']),live(replay)),
            'normal_reference_vs_pre_stop':AUDIT['localization'](live(reference['records']),live(rows[:count])),
            'pre_stop_context':before.get('context'),
            'outcome_context':outcome,'continuous_transition':rows,
            'endpoint_status':{'reference':reference.get('hdmi',{'status':'not_collected'}),
                               'replay_startup':results['transition'].get('hdmi',{'status':'not_collected'}),
                               'confirmed_outcome':after.get('hdmi',{'status':'not_collected'}) if after else {'status':'not_collected'}},
            'limitations':['Missing replay observations remain unknown, not proof hardware is healthy.',
                           'Outcome readback is a separate window after visual confirmation; not a continuous trace of the human response gap.',
                           'Selected software/configuration observations do not prove physical pixels or an earliest physical failure.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('first','reference','transition','outcome','compare'))
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--file', default='/storage/videos/Test-H264-720p-20min.mp4')
    p.add_argument('--timeout', type=float, default=6)
    p.add_argument('--confirmed-normal', action='store_true')
    p.add_argument('--stop-hdr-flush-guard', action='store_true', help='Explicit experiment: suppress HDR-family flush only across Stop, restore before replay')
    p.add_argument('--reported-outcome', choices=('black','normal'))
    a = p.parse_args()
    if a.stop_hdr_flush_guard and a.action != 'transition':
        p.error('--stop-hdr-flush-guard is valid only for transition')
    if a.action == 'compare':
        print(json.dumps(compare_session(a.run), indent=2))
        return
    if a.action == 'outcome' and not a.reported_outcome:
        p.error('outcome requires the user-reported picture: --reported-outcome black|normal')
    if not 0 < a.timeout <= 15:
        p.error('timeout must be >0 and <=15 seconds; never implies ring capacity is sufficient')
    with open('/run/e900-playback.lock','w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(a)


if __name__ == '__main__':
    main()
