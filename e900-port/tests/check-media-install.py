#!/usr/bin/env python3
"""Execute the real module install recipe below a hidden build directory."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get('E900_CE_REFERENCE',PORT/'reference/CoreELEC'))
spec=importlib.util.spec_from_file_location('media_installer',PORT/'scripts/install-patches.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
relative='projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk'
with tempfile.TemporaryDirectory(prefix='e900-media-install-') as tmp:
    root=Path(tmp);recipe=root/relative;recipe.parent.mkdir(parents=True);shutil.copy2(REFERENCE/relative,recipe)
    path,content,metadata=installer.media_module_install_fix(root);recipe.write_text(content)
    assert installer.media_module_install_fix(root)[1]==content
    build=root/'.e900-work/build/drivers';build.mkdir(parents=True)
    (build/'visible.ko').write_bytes(b'test module payload')
    hidden=build/'.tmp_versions';hidden.mkdir();(hidden/'ignored.ko').write_bytes(b'ignored')
    fw=build.parent/'firmware';fw.mkdir();(fw/'test.bin').write_bytes(b'test firmware')
    dest=root/'install'
    program='''source "$1"
PKG_BUILD="$2"
INSTALL="$3"
get_full_module_dir() { echo lib/modules/test; }
get_full_firmware_dir() { echo lib/firmware; }
makeinstall_target
'''
    subprocess.run(['bash','-e','-c',program,'test',str(recipe),str(build.parent),str(dest)],check=True)
    assert (dest/'lib/modules/test/media_modules-aml/visible.ko').read_bytes()==b'test module payload'
    assert not (dest/'lib/modules/test/media_modules-aml/ignored.ko').exists()
    assert (dest/'lib/firmware/video/test.bin').read_bytes()==b'test firmware'
    empty=root/'empty';empty.mkdir();(empty/'firmware').mkdir()
    result=subprocess.run(['bash','-e','-c',program,'test',str(recipe),str(empty),str(root/'empty-install')],capture_output=True,text=True)
    assert result.returncode!=0 and 'No media modules were installed' in result.stderr
    previous=dict(pins=installer.PINS,profile='decoder',host_codegen={},patches=[],build_options=None)
    updated=dict(previous,package_install_fixes=[metadata])
    assert installer.invalidated_packages(previous,updated)==['media_modules-aml']
    recipe.write_text(content+'\n# unmanaged edit\n')
    try:installer.media_module_install_fix(root)
    except RuntimeError:pass
    else:raise AssertionError('Unmanaged recipe edit accepted')
print('PASS: hidden build root installs visible modules/firmware, excludes hidden files, rejects empty output and local edits')
print('PASS: install policy migration invalidates media only, preserving kernel and toolchain')
