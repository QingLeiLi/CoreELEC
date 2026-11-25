#!/usr/bin/env python3
"""A1 wrapper failure path, with all device paths redirected to a temp tree."""
import hashlib
import importlib.util
import json
import fcntl
from pathlib import Path
import shutil
import tempfile

source = Path(__file__).resolve().parents[1]/'scripts/e900-a1-run.py'
spec = importlib.util.spec_from_file_location('e900_a1_run', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    run = root/'A1-test'; run.mkdir()
    tools = run/'scripts'; tools.mkdir()
    tool = tools/'e900-register-transition.py'; tool.write_text('# archive\n')
    boot = root/'boot_id'; boot.write_text('test-boot\n')
    video = root/'video'; video.mkdir()
    (video/'video_global_output').write_text('1\n')
    (video/'disable_video').write_text('0\n')
    params = root/'params'; params.mkdir()
    (params/'gxlx2_blend_hold').write_text('0\n')
    (params/'gxlx2_gen3_clear_high').write_text('N\n')
    module.BOOT = boot
    module.VIDEO = video
    module.PARAM = params
    decoder = root/'decoder'; decoder.write_text('ammvdec_h264 active\n')
    module.DECODER = decoder
    manifest = {'boot_id': 'test-boot', 'output_mode': '1080p60hz', 'rdma': '1,0',
                'tool_sha256': {tool.name: hashlib.sha256(tool.read_bytes()).hexdigest()}}
    (run/'manifest.json').write_text(json.dumps(manifest))
    (run/'baseline.json').write_text(json.dumps({'status': 'first_playback_confirmed'}))
    (run/'CURRENT-CALIBRATION-CONFIRMED.txt').write_text('test route\n')
    def fake_snapshot():
        return {'utc':'test', 'boot_id':'test-boot', 'video_init':'2', 'decoder':'ammvdec_h264 active',
                'global_output':(video/'video_global_output').read_text().strip(),
                'hold':(params/'gxlx2_blend_hold').read_text().strip(),
                'gen3':'N', 'disable_video':'0', 'vdin_session':'boot_id=test-boot\n',
                'display_mode':'1080p60hz', 'rdma':'1,0'}
    module.snapshot = fake_snapshot
    module.save_dmesg = lambda *_: None
    module.playback_remaining = lambda *_: {'properties': {'speed': 1}}
    counts = iter(range(10, 100))
    module.frame_count = lambda *_: next(counts)
    module.time.sleep = lambda *_: None
    original_open = open
    module.open = lambda path, mode: original_open(root/Path(path).name, mode) if str(path).startswith('/run/') else original_open(path, mode)
    class FakeKernel:
        def read(self, _name): return 'edge'
    states = {'edge': {'status': 3, 'generation': 10},
              'submit': {'status': 2, 'generation': 20}}
    def fake_module(path):
        if str(path).endswith('e900-transition.py'):
            return {'Kernel': FakeKernel, 'state': lambda _text: dict(states['edge'])}
        return {'read': lambda _name: 'submit', 'state': lambda _text: dict(states['submit'])}
    module.runpy.run_path = fake_module
    module.run_collector = lambda *_: 2
    assert module.pulse(run) == 2
    assert (run/'exit-code.txt').read_text().strip() == '2'
    assert json.loads((run/'pulse.json').read_text())['status'] == 'collector_incomplete'
    assert (params/'gxlx2_blend_hold').read_text().strip() == '0'
    assert (video/'video_global_output').read_text().strip() == '1'
    assert (run/'collector.stdout').exists() and (run/'collector.stderr').exists()
    try: module.pulse(run)
    except RuntimeError as exc: assert 'already attempted' in str(exc)
    else: raise AssertionError('Repeated pulse was permitted')

    def new_run(name):
        target = root/name
        target.mkdir()
        shutil.copytree(tools, target/'scripts')
        for name in ('manifest.json', 'baseline.json', 'CURRENT-CALIBRATION-CONFIRMED.txt'):
            shutil.copy2(run/name, target/name)
        return target

    # A lock conflict must abort BEFORE changing hold or invoking collection.
    target = new_run('A1-lock-conflict')
    with (root/'e900-edge.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: module.pulse(target)
        except BlockingIOError: pass
        else: raise AssertionError('Locked session was entered')
    assert (params/'gxlx2_blend_hold').read_text().strip() == '0'
    assert json.loads((target/'pulse.json').read_text())['status'] == 'failed'

    # Even a frozen replacement generation belongs to someone else.
    target = new_run('A1-replaced-generation')
    def replaced(*_):
        states['edge']['generation'] += 2
        return 2
    module.run_collector = replaced
    assert module.pulse(target) == 2
    assert (params/'gxlx2_blend_hold').read_text().strip() == '3'
    assert 'hold_cleanup_blocked' in json.loads((target/'pulse.json').read_text())
    (params/'gxlx2_blend_hold').write_text('0\n')  # reset synthetic fixture only

    # An ordinary collection exception still records a nonzero code and cleanup.
    target = new_run('A1-exception')
    def interrupted(*_): raise RuntimeError('synthetic collection failure')
    module.run_collector = interrupted
    try: module.pulse(target)
    except RuntimeError as exc: assert 'synthetic' in str(exc)
    else: raise AssertionError('Collection exception suppressed')
    assert (target/'exit-code.txt').read_text().strip() == '125'
    assert (params/'gxlx2_blend_hold').read_text().strip() == '0'
    assert json.loads((target/'pulse.json').read_text())['status'] == 'failed'

    # TCP may coalesce a notification and split a UTF-8 character in the reply.
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def settimeout(self, value): pass
        def sendall(self, payload):
            request = json.loads(payload)
            response = ('{"method":"notification"}' + json.dumps(
                {'jsonrpc': '2.0', 'id': request['id'], 'result': '彩条'}, ensure_ascii=False)).encode()
            pos = response.index('彩'.encode()) + 1
            self.parts = iter((response[:pos], response[pos:]))
        def recv(self, _size): return next(self.parts, b'')
    module.socket.create_connection = lambda *_: Connection()
    assert module.rpc(run, 'Test.Method', {}) == '彩条'
    record = json.loads((run/'rpc.jsonl').read_text().splitlines()[-1])
    assert record['request']['method'] == 'Test.Method' and 'notification' in record['raw_reply']
print('PASS: incomplete/exception evidence preserved; exit code propagated; locks precede mutation; replacement generation untouched; repeat pulse refused; fragmented TCP RPC decoded')
