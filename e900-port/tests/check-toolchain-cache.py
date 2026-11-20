#!/usr/bin/env python3
"""Exercise fallback roundtrip without claiming a real toolchain build."""
from pathlib import Path
import importlib.util,json,tempfile
from unittest import mock
PORT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('toolchain_snapshot',PORT/'scripts/toolchain-cache.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='e900-toolchain-cache-') as t:
 work=Path(t);repo=work/'CoreELEC-decoder';build=repo/'build.CoreELEC-test'
 tools=build/'toolchain/bin';tools.mkdir(parents=True)
 (tools/'cmake').write_text('installed host tool');(tools/'cmake').chmod(0o755)
 (tools/'alias').symlink_to('cmake')
 stamps=build/'.stamps/cmake';stamps.mkdir(parents=True)
 for name in ['build_host','build_bootstrap','build_target','install_target']:(stamps/name).write_text(name)
 (build/'build/cmake-3.28.3').mkdir(parents=True)
 (build/'build/cmake-3.28.3/object.o').write_text('unneeded compiler scratch')
 identity=work/'cache-identity.json';identity.write_text(json.dumps({'compat':'same','previous_compat':'prior'}))
 assert m.prepare(repo,work)==(True,True)
 snapshot=work/'toolchain-snapshot'/build.name
 assert (snapshot/'toolchain/bin/cmake').read_text()=='installed host tool'
 assert (snapshot/'toolchain/bin/alias').is_symlink()
 assert (snapshot/'.stamps/cmake/build_host').exists()
 assert not (snapshot/'.stamps/cmake/build_target').exists()
 assert not (snapshot/'.stamps/cmake/install_target').exists()
 assert not (snapshot/'build').exists()
 import shutil
 shutil.rmtree(build);m.restore(repo,work)
 assert (tools/'cmake').stat().st_mode&0o111
 assert not (stamps/'build_target').exists()
 try:m.restore(repo,work)
 except ValueError as e:assert 'overlay' in str(e)
 else:raise AssertionError('Existing build overlay accepted')
 shutil.rmtree(build);identity.write_text(json.dumps({'compat':'different','previous_compat':'other'}))
 try:m.restore(repo,work)
 except ValueError as e:assert 'Incompatible' in str(e)
 else:raise AssertionError('Incompatible snapshot accepted')
 assert not build.exists()
 identity.write_text(json.dumps({'compat':'same','previous_compat':'prior'}))
 (snapshot/'.stamps/cmake/build_target').write_text('bad')
 try:m.restore(repo,work)
 except ValueError as e:assert 'Target' in str(e)
 else:raise AssertionError('Incomplete target output marked built')
 (snapshot/'.stamps/cmake/build_target').unlink();m.restore(repo,work)
 with mock.patch.object(m,'size',side_effect=lambda p:4*m.GIB+1 if p==repo else 100):
  assert m.prepare(repo,work)==(True,False)
 with mock.patch.object(m,'size',return_value=5*m.GIB):
  assert m.prepare(repo,work)==(False,False)
print('PASS: independent installed tools and host stamps roundtrip; no target stamps, oversized full cache, incompatible restore or existing-tree overwrite')
