#!/usr/bin/env python3
"""Remove only explicit new observation statements and verify original policy."""
import json,os,re,shutil,subprocess,tempfile
from pathlib import Path
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
with tempfile.TemporaryDirectory(prefix='e900-returns-') as td:
 root=Path(td)
 for row in json.loads((PORT/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   p=root/row['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(AUDIT/'sources'/row['path'].replace('/','__'),p)
 names=['drivers/amlogic/media/video_sink/video_hw.c','drivers/amlogic/media/enhancement/amvecm/amcsc.c']
 before={}
 for patch in sorted((PORT/'patches/linux').glob('*.patch')):
  if patch.name.startswith('0042-'): before={name:(root/name).read_text() for name in names}
  subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
 after={name:(root/name).read_text() for name in names}
 csc=after[names[1]]
 pattern=r'(?m)^(\t+)\{ /\* e900-csc-return (\d+) \*/\n\1\tif \(vd_path == VD1_PATH\)\n\1\t\te900_playback_note\(1, 2, e900_hdr_recovery_video_session\(\),\n\1\t\t\t0, vd_path, 18, \2, ([012])\);\n\1\treturn \3;\n\1\}'
 blocks=list(re.finditer(pattern,csc));assert len(blocks)==7
 assert re.sub(pattern,lambda m:m[1]+'return '+m[3]+';',csc)==before[names[1]]
 hw=after[names[0]]
 hw,n=re.subn(r'^\t+e900_playback_note\(1, 2, e900_hdr_recovery_video_session\(\), 0, 0, (?:16|17),[^;]+;\n','',hw,flags=re.M)
 assert n==2
 hw=hw.replace('if (!setting || !setting->frame_par) {\n\t\treturn;\n\t}', 'if (!setting || !setting->frame_par)\n\t\treturn;')
 assert hw==before[names[0]]
 # Execute the exact added return blocks both taken/untaken and on VD1/VD2.
 pre='''#include <assert.h>
#define VD1_PATH 0
static unsigned events,reason,retval;
static unsigned e900_hdr_recovery_video_session(void){return 1;}
static void e900_playback_note(unsigned s,unsigned k,unsigned session,unsigned b,unsigned h,unsigned r,unsigned v,unsigned a){assert(s==1&&k==2&&session==1&&r==18);(void)b;(void)h;events++;reason=v;retval=a;}
'''
 for i,block in enumerate(blocks):pre+=f'int test{i}(int take,int vd_path){{if(take)\n'+block[0]+'\nreturn 9;}\n'
 pre+='int main(void){\n'
 for i,block in enumerate(blocks):
  value=int(block[3]);code=int(block[2])
  pre+=f'events=0;assert(test{i}(0,0)==9&&!events);assert(test{i}(1,1)=={value}&&!events);assert(test{i}(1,0)=={value}&&events==1&&reason=={code}&&retval=={value});\n'
 pre+='return 0;}\n';(root/'test.c').write_text(pre)
 subprocess.run(['cc','-std=gnu89','-Wall','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
print('PASS: DCU/PPS/CSC policy preserved; seven real return blocks retain conditional behavior and report VD1 reason/return code')
