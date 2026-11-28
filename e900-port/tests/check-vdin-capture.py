#!/usr/bin/env python3
"""Check the optional VDIN source bundle, host C logic, tools and cache policy."""
from pathlib import Path
import hashlib,importlib.util,json,os,shutil,subprocess,sys,tempfile
from unittest import mock
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
REFERENCE=Path(os.environ.get('E900_CE_REFERENCE',PORT/'reference/CoreELEC'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
installer=load('capture_installer',PORT/'scripts/install-patches.py')
cache=load('capture_cache',PORT/'scripts/build-cache.py')
with tempfile.TemporaryDirectory(prefix='e900-vdin-capture-') as d:
 root=Path(d);linux=root/'linux';linux.mkdir()
 for row in json.loads((PORT/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  source=AUDIT/'sources'/row['path'].replace('/','__')
  data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
  dest=linux/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
 subprocess.run(['git','init','--quiet'],cwd=linux,check=True)
 for patch in sorted((PORT/'patches/linux').glob('*.patch')):
  subprocess.run(['git','apply','--check',str(patch.resolve())],cwd=linux,check=True)
  subprocess.run(['git','apply',str(patch.resolve())],cwd=linux,check=True)
 print('PASS: complete optional VDIN bundle applies to verified pinned Linux fixtures',flush=True)
 harness=root/'harness';harness.mkdir();base='drivers/amlogic/media/vin/tvin/vdin/'
 for name in ['vdin_drv.c','vdin_canvas.c']:
  dest=harness/'patched'/base/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(linux/base/name,dest)
 debug=(linux/base/'vdin_debug.c').read_text();a=debug.index('#ifdef CONFIG_CMA\nstruct e900_vdin_snapshot_header');b=debug.index('\n#endif',debug.index('static int e900_vdin_snapshot_save',a))+len('\n#endif')
 (harness/'snapshot.c').write_text(debug[a:b]+'\n')
 shutil.copy2(PORT/'scripts/inspect-vdin-snapshot.py',harness/'inspect-snapshot.py')
 shutil.copy2(PORT/'scripts/e900-capture-ready.sh',harness/'capture-ready.sh')
 env=dict(os.environ,E900_AUDIT_ROOT=str(AUDIT),E900_CAPTURE_TEST_ROOT=str(harness),E900_CAPTURE_LINUX_ROOT=str(linux),E900_CAPTURE_CONFIG_BASE=str(REFERENCE/installer.CAPTURE_CONFIG))
 for check in ['check-snapshot.py','check-pin-policy.py','check-linkage.py','check-ring-mode.py','check-client.py','check-matrix-policy.py','check-completion-order.py']:
  subprocess.run([sys.executable,str(PORT/'tests/vdin'/check)],env=env,check=True)
 # Real installer transitions and compatible-cache retention.
 repo=root/'repo';repo.mkdir()
 paths=['projects/Amlogic-ce/packages/linux/package.mk','projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk','projects/Amlogic-ce/packages/linux-drivers/amlogic/uwe5631-aml/package.mk','packages/sysutils/keyutils/package.mk','packages/sysutils/usbutils/package.mk','packages/network/connman/package.mk','packages/network/wireguard-linux-compat/package.mk','packages/network/wireguard-tools/package.mk','projects/Amlogic-ce/packages/tools/u-boot-tools/package.mk','packages/tools/megatools/package.mk','config/optimize','scripts/image']
 for path in paths:
  dest=repo/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REFERENCE/path,dest)
 baseline=installer.capture_config_fix(REFERENCE,False)[1]
 config=repo/installer.CAPTURE_CONFIG;config.parent.mkdir(parents=True,exist_ok=True);config.write_text(baseline)
 host=dict(os_release='Ubuntu 22.04',machine='x86_64',packages='test-compiler')
 with mock.patch.dict(os.environ,{'E900_VDIN_CAPTURE':'0','E900_SOURCE_TRACE':'0','E900_INCREMENTAL_REUSE':'1'}),mock.patch.object(installer.subprocess,'check_output',return_value=installer.PINS['coreelec']):
  installer.install(repo,'decoder');identity_off=cache.identities(PORT,'decoder',root/'work',host)
  sentinel=repo/'build.test/toolchain/keep';sentinel.parent.mkdir(parents=True);sentinel.write_text('compiler')
  os.environ['E900_VDIN_CAPTURE']='1';identity_on=cache.identities(PORT,'decoder',root/'work',host)
  assert identity_off['compat']==identity_on['compat'] and identity_off['compiler']==identity_on['compiler'] and identity_off['state']!=identity_on['state']
  installer.install(repo,'decoder');state=json.loads((repo/'.e900-profile.json').read_text())
  assert len(state['patches'])==len(installer.PROFILES['decoder'])+len(installer.CAPTURE_PATCHES) and state['capture_config']
  assert all(line in config.read_text().splitlines() for line in ['CONFIG_AMLOGIC_MEDIA_VIN=y','CONFIG_AMLOGIC_MEDIA_TVIN=y','CONFIG_AMLOGIC_MEDIA_VDIN=y','CONFIG_AMLOGIC_MEDIA_VIUIN=y'])
  assert all('CONFIG_'+name+'=y' in config.read_text().splitlines() for name in installer.CAPTURE_BUILTIN_DEPS)
  assert json.loads((repo/'.e900-invalidate.json').read_text())==['linux','media_modules-aml','uwe5631-aml'] and sentinel.read_text()=='compiler'
  # A failed older run may have left the exact formerly managed module config.
  new_config=config.read_text()
  legacy_config=baseline.replace('# CONFIG_AMLOGIC_MEDIA_VIN is not set','CONFIG_AMLOGIC_MEDIA_VIN=y',1)+installer.CAPTURE_CONFIG_LEGACY_EXTRA
  config.write_text(legacy_config)
  old_state=json.loads((repo/'.e900-profile.json').read_text())
  old_state['capture_config']['sha256']=hashlib.sha256(legacy_config.encode()).hexdigest()
  old_state['patches']=[entry for entry in old_state['patches'] if not entry['source'].endswith('0016-gxlx2-vdin-builtin-linkage.patch')]
  (repo/'.e900-profile.json').write_text(json.dumps(old_state))
  installer.install(repo,'decoder')
  assert config.read_text()==new_config and sentinel.read_text()=='compiler'
  assert json.loads((repo/'.e900-invalidate.json').read_text())==['linux','media_modules-aml','uwe5631-aml']
  print('PASS: failed module-build cache migrates to built-in capture without discarding the toolchain',flush=True)
  before=config.read_text();config.write_text(before+'\n# local edit\n')
  for enabled in ['0','1']:
   os.environ['E900_VDIN_CAPTURE']=enabled
   try:installer.install(repo,'decoder')
   except RuntimeError as exc:assert 'locally edited capture' in str(exc)
   else:raise AssertionError('Locally edited kernel configuration overwritten')
  config.write_text(before);os.environ['E900_VDIN_CAPTURE']='0';installer.install(repo,'decoder')
  assert config.read_text()==baseline and sentinel.exists()
  assert not json.loads((repo/'.e900-profile.json').read_text())['capture_config']
  assert all(not (repo/installer.LINUX_DIR/('9000-e900-'+Path(p).name)).exists() for p in installer.CAPTURE_PATCHES)
  os.environ['E900_VDIN_CAPTURE']='1'
  try:installer.selected_patches('identify')
  except RuntimeError:pass
  else:raise AssertionError('Capture accepted for a non-board profile')
 print('PASS: capture enable/disable restores exact kernel config, protects local edits and preserves compatible toolchain/cache identity',flush=True)
print('HOST CAPTURE CHECKS PASSED. Full ARM build, hardware completion/coherency and downstream pixels remain unverified.')
