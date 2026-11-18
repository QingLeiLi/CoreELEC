#!/usr/bin/env python3
"""Package the hardware-tested diagnostic kernel/MP2 DT with original CE init."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

PORT = Path(__file__).resolve().parents[1]
PINNED = {
    'kernel': '2126e5a3aac587db015ec3bb879421c28ae045dccf24f12361f653bcbe3a11b8',
    'dtb': 'c1d06d03a2eac0a10f6623977100e675222732dd47a34d49c584c57f6ecbda9a',
    'initrd': '73ec69b4b84df29c6423f8f76835a8a51b161bae615d1081fe857e54f7eb58e2',
}
CPIO = '4fc9c4036c03d6ed64366957cb690e554eb87cffacc8e406d1546e48881951e2'
SYSTEM = '2096dbc4fc8b8a1fb0a81cb73ebdc8af3fdd9c27ae086f31fd53a15c9c08f40e'

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def make(kernel, dtb, initrd, output, mkimage):
    assert not output.exists()
    for name,p in [('kernel',kernel),('dtb',dtb),('initrd',initrd)]: assert digest(p) == PINNED[name],name
    spec = importlib.util.spec_from_file_location('normal_board', PORT/'scripts/validate-board.py')
    board = importlib.util.module_from_spec(spec); spec.loader.exec_module(board)
    board.validate(dtb)
    data = initrd.read_bytes(); h = bytearray(data[:64]); f = struct.unpack('>7I4B32s',h); h[4:8]=bytes(4)
    assert f[0] == 0x27051956 and zlib.crc32(h) == f[1]
    assert f[3] == len(data)-64 and zlib.crc32(data[64:]) == f[6]
    assert f[7:11] == (5,22,3,1)
    assert hashlib.sha256(gzip.decompress(data[64:])).hexdigest() == CPIO
    source = PORT/'boards/e900-usb-normal.src'; text = source.read_text()
    assert text.count('booti ') == 1 and text.count('fatload ') == 3
    assert all(x not in text for x in ['usb write','mmc write','store write','saveenv','E9LOG','E9RSEED','setexpr','reset'])
    output.mkdir(parents=True)
    for p,name in [(kernel,'e900-Image-guard'),(dtb,'e900-full.dtb'),(initrd,'e900-uInitrd-normal')]: shutil.copy2(p,output/name)
    shutil.copy2(source,output/'normal.src')
    subprocess.run([str(mkimage),'-A','arm','-O','linux','-T','script','-C','none','-n','E900 normal USB boot','-d',str(source),str(output/'s905_autoscript')],check=True)
    for name in ['aml_autoscript','cfgload']: shutil.copy2(output/'s905_autoscript',output/name)
    manifest={p.name:digest(p) for p in output.iterdir() if p.is_file()}
    (output/'SHA256SUMS').write_text(''.join(f'{sha}  {name}\n' for name,sha in sorted(manifest.items())))
    (output/'normal-provenance.json').write_text(json.dumps({'files':manifest,'required_existing_SYSTEM_sha256':SYSTEM,'original_ce_initramfs':True,'persistent_boot':True,'bootloader_writes':False,'emmc_writes':False,'hardware_status':'kernel+MP2 DT tested; normal loader/original initrd combination awaits reboot validation','limitations':['kernel still contains tested binary DI guard','physical HDMI output pending display HPD','source fixes not yet fully ARM-built']},indent=2)+'\n')
    print('Prepared normal boot candidate:',output)

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['kernel','dtb','initrd','output']:p.add_argument(name,type=Path)
    p.add_argument('--mkimage',type=Path,required=True)
    a=p.parse_args();make(a.kernel,a.dtb,a.initrd,a.output,a.mkimage)
