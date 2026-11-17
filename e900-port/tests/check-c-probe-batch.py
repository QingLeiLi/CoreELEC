#!/usr/bin/env python3
import subprocess,pathlib
import sys
kit=pathlib.Path(sys.argv[1])
h=r'''
ledger="$1"; ram="$2"; mode="$3"; bootargs=android
setenv() { printf -v "$1" '%s' "$2"; }
fatload() { filesize=200; if [ "$4" = E9LOG.TXT ]; then old="$ledger"; else next="$4"; fi; return 0; }
cmp.b() { if [ "$2" = 0x04001000 ]; then [ "$old" = "$next" ]; elif [ "$1" = 0x04000000 ]; then [ "$old" = "$readbuf" ]; else [ "$next" = "$readbuf" ]; fi; }
usb() { case "$1" in start|dev) return 0;; read) readbuf="$ledger"; return 0;; write) [ "$mode" != fail ] || return 1; ledger="$next"; return 0;; esac; return 1; }
itest.l() { [ "$ram" = "${3#0x}" ]; }
setexpr() { return 1; }
booti() { printf 'BOOT %s\n' "$ledger"; exit 0; }
. "$4" >/dev/null
printf 'END %s %s\n' "$ledger" "$bootargs"
'''
# Source output redirected by dot would hide BOOT too; emit on stderr.
h=h.replace("printf 'BOOT %s\\n' \"$ledger\";", "printf 'BOOT %s\\n' \"$ledger\" >&2;")
import json
meta=json.loads((kit/'batch-provenance.json').read_text())
late=meta.get('batch')=='batch13'
n=len(meta['stages'])
cases=[]
for i in range(n):
    cases.append(('old' if i==0 else f'E9B{i-1}ARM.BIN',
                  '0' if i==0 else f'{0xe9130000+i:x}' if late else 'e9120001',
                  'ok',f'BOOT E9B{i}ARM.BIN'))
cases += [(f'E9B{n-1}ARM.BIN',f'{0xe9130000+n:x}' if late else 'e9120001','ok',f'END E9B{n-1}PASS.BIN'),
          ('E9B1ARM.BIN','0','ok','END E9B1FAIL.BIN'),
          ('E9B1FAIL.BIN','0','ok','END E9B1FAIL.BIN'),('old','0','fail','END old')]
if late: cases.append(('E9B2ARM.BIN','e9130002','ok','END E9B2FAIL.BIN'))
for ledger,ram,mode,expected in cases:
 if meta.get('batch')=='bisect14': break
 p=subprocess.run(['bash','-c',h,'test',ledger,ram,mode,str(kit/'batch.src')],capture_output=True,text=True,check=True)
 assert expected in p.stdout+p.stderr,(ledger,p.stdout,p.stderr)
if meta.get('batch')=='bisect14':
 cases=[('old','0','ok','BOOT E9B1ARM.BIN'),
        ('E9B1ARM.BIN','e9140002','ok','BOOT E9B2ARM.BIN'),
        ('E9B1ARM.BIN','0','ok','BOOT E9B0ARM.BIN'),
        ('E9B2ARM.BIN','e9140003','ok','BOOT E9B3ARM.BIN'),
        ('E9B2ARM.BIN','0','ok','END E9B2FAIL.BIN'),
        ('E9B0ARM.BIN','e9140001','ok','END E9B0PASS.BIN'),
        ('E9B0ARM.BIN','0','ok','END E9B0FAIL.BIN'),
        ('E9B3ARM.BIN','e9140004','ok','END E9B3PASS.BIN'),
        ('E9B3ARM.BIN','0','ok','END E9B3FAIL.BIN'),
        ('old','0','fail','END old')]
 for ledger,ram,mode,expected in cases:
  p=subprocess.run(['bash','-c',h,'test',ledger,ram,mode,str(kit/'batch.src')],capture_output=True,text=True,check=True)
  assert expected in p.stdout+p.stderr,(ledger,p.stdout,p.stderr)
 print('PASS: middle-first binary branches and all terminal intervals')
print('PASS:',n,'stage progression, final pass, failed marker, no retry and write failure')
