#!/usr/bin/env python3
"""Exercise actual CE image overlay copying and checked cache/installer migration."""
import importlib.util
import json
import os
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import mock

PORT=Path(__file__).resolve().parents[1]
REF=Path(os.environ.get('E900_CE_REFERENCE',PORT/'reference/CoreELEC'))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
installer=load('overlay_installer',PORT/'scripts/install-patches.py')
cache=load('overlay_cache',PORT/'scripts/build-cache.py')
with tempfile.TemporaryDirectory(prefix='e900-osd-overlay-') as tmp:
 root=Path(tmp);checkout=root/'repo';port=root/'port'
 for name in ['scripts','patches','boards','config']:shutil.copytree(PORT/name,port/name,ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy2(PORT/'pins.json',port/'pins.json');installer.PORT=port
 recipes=['projects/Amlogic-ce/packages/linux/package.mk','projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk','projects/Amlogic-ce/packages/linux-drivers/amlogic/uwe5631-aml/package.mk','packages/sysutils/keyutils/package.mk','packages/sysutils/usbutils/package.mk','packages/network/connman/package.mk','packages/network/wireguard-linux-compat/package.mk','packages/network/wireguard-tools/package.mk','projects/Amlogic-ce/packages/tools/u-boot-tools/package.mk','packages/tools/megatools/package.mk','config/optimize','scripts/image']
 for rel in recipes:
  dest=checkout/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REF/rel,dest)
 with mock.patch.dict(os.environ,{'E900_SOURCE_TRACE':'0','E900_VDIN_CAPTURE':'0','E900_INCREMENTAL_REUSE':'1'}),mock.patch.object(installer.subprocess,'check_output',return_value=installer.PINS['coreelec']):
  installer.install(checkout,'decoder')
  state=json.loads((checkout/'.e900-profile.json').read_text());assert len(state['image_files'])==9
  # Run the pinned CE functions, rather than reimplementing their copy behavior.
  functions=(REF/'config/functions').read_text();a=functions.index('enable_service() {');b=functions.index('### MULTI-THREADED',a)
  image=(REF/'scripts/image').read_text();a=image.index('# Copy DEVICE related files');b=image.index('# Replace placeholders',a)
  target=root/'system';target.mkdir()
  program=functions[functions.index('enable_service() {'):functions.index('### MULTI-THREADED',functions.index('enable_service() {'))]+ '\nINSTALL="$1"\nPROJECT_DIR="$2"\nPROJECT=Amlogic-ce\nDEVICE=Amlogic-ng\n'+image[a:b]
  if sys.platform == 'darwin':
   # The synthetic destination is empty: GNU's remove-destination is a no-op.
   # Keep CE's actual script intact while adapting BSD cp's option parser only.
   assert not list(target.iterdir())
   program = 'cp() { if [ "$1" = "-PR" ] && [ "$2" = "--remove-destination" ]; then shift 2; command cp -PR "$@"; else command cp "$@"; fi; }\n' + program
  subprocess.run(['bash','-e','-c',program,'test',str(target),str(checkout/'projects')],check=True)
  unit=(target/'usr/lib/systemd/system/e900-osd-rdma-image.service').read_text()
  assert 'Before=kodi.service' in unit and 'After=graphical.target' in unit
  assert 'ExecStart=/usr/bin/python3 /usr/lib/e900-boot/e900-osd-rdma-boot.py' in unit
  assert 'ConditionKernelCommandLine=amvideo.gxlx2_hw_init_wait=0' in unit
  drop=(target/'usr/lib/systemd/system/kodi.service.d/30-e900-osd-rdma-image.conf').read_text()
  assert 'Requires=e900-osd-rdma-image.service' in drop and 'After=e900-osd-rdma-image.service' in drop
  network=(target/'usr/lib/systemd/system/kodi-waitonnetwork.service.d/20-e900-fast-boot.conf').read_text()
  assert 'ConditionPathExists=/storage/.config/e900-boot-wait-network' in network
  assert 'ExecStart=' not in network and 'connman.service' not in network
  wol=(target/'usr/lib/systemd/system/e900-wol.service').read_text()
  assert 'ExecStart=/bin/sh /usr/lib/e900-boot/e900-wol.sh' in wol and 'ExecStop=' not in wol
  assert (target/'usr/lib/e900-boot/e900-wol.sh').is_file()
  assert (target/'usr/lib/systemd/system/multi-user.target.wants/e900-wol.service').readlink()==Path('../e900-wol.service')
  boot=load('image_boot_policy',target/'usr/lib/e900-boot/e900-osd-rdma-boot.py')
  assert json.loads((target/'usr/lib/e900-boot/source-contract.json').read_text())==boot.SOURCE_CONTRACT
  assert all(x not in unit for x in ['/storage/.config/e900-osd-rdma-boot.py','ExecStartPre='])
  # An overlay-only revision must alter restore state but keep all compiled work.
  sentinel=checkout/'build.test/toolchain/keep';sentinel.parent.mkdir(parents=True);sentinel.write_text('compiler')
  linux=checkout/'build.test/build/linux-verified/keep';linux.parent.mkdir(parents=True);linux.write_text('kernel')
  host={'host':'test'};before=cache.identities(port,'decoder',root/'work',host)
  cfg=port/'config/e900-osd-rdma-image.service';cfg.write_text(cfg.read_text()+'\n# image-only revision\n')
  after=cache.identities(port,'decoder',root/'work',host)
  assert before['compat']==after['compat'] and before['state']!=after['state']
  installer.install(checkout,'decoder')
  updated=json.loads((checkout/'.e900-profile.json').read_text())
  assert installer.invalidated_packages(state,updated)==[]
  assert sentinel.read_text()=='compiler' and linux.read_text()=='kernel' and not (checkout/'.e900-invalidate.json').exists()
  managed=checkout/state['image_files'][0]['destination'];managed.write_bytes(managed.read_bytes()+b'\n# user edit\n')
  try:installer.install(checkout,'decoder')
  except RuntimeError as e:assert 'Locally edited image overlay' in str(e)
  else:raise AssertionError('Overwrote a local overlay edit')
 assert not installer.image_overlay_files('identify')
print('PASS: actual CE image copy installs helper, contract and Kodi dependency; overlay-only edits retain kernel/toolchain and reject local edits')
print('PENDING: full source image build and physical boot on that new image')
