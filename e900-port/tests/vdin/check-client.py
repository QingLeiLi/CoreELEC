from pathlib import Path
import os
import importlib.util,json,struct,zlib,subprocess,tempfile,shlex
H=Path(os.environ["E900_CAPTURE_TEST_ROOT"])
s=importlib.util.spec_from_file_location('snapshot_client',H/'inspect-snapshot.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
b=(H/'synthetic.e9cap').read_bytes();meta,pixels=m.inspect(b);assert meta['width']==2 and pixels==bytes(range(32,38))+bytes(range(40,46)) and meta['slot_association_valid'] and meta['payload_crc32_valid'];cases=1
values=list(m.HEADER.unpack_from(b))
for field,value in [(0,b'badmagic'),(1,3),(2,79),(3,0),(3,1921),(4,0),(4,1081),(6,7),(7,5),(8,10),(9,10),(10,0),(14,11)]:
 modified=values.copy();modified[field]=value
 try:m.inspect(m.HEADER.pack(*modified)+b[m.HEADER.size:])
 except ValueError:pass
 else:raise AssertionError((field,value))
 cases+=1
for broken in [b'',b[:79],b[:143],b[:-1],b+b'\0']:
 try:m.inspect(broken)
 except ValueError:pass
 else:raise AssertionError('Bad length accepted')
 cases+=1
# v1 remains inspectable for historical evidence but cannot meet the new association gate.
legacy_values=values.copy();legacy_values[1:3]=[1,80];legacy_values[10]=3
legacy=m.HEADER.pack(*legacy_values) + pixels
assert not m.inspect(legacy)[0]['slot_association_valid'];cases+=1
for offset in [10*4+8,80+24,80+32,80+40,80+64,80+72,144]:
 tampered=bytearray(b);tampered[offset]^=1
 try:bad_meta,_=m.inspect(bytes(tampered))
 except ValueError:pass
 else:assert not bad_meta['slot_association_valid'],offset
 cases+=1
for order in ['RGB','BGR']:
 png=m.png(2,2,pixels,order);assert png[:8]==b'\x89PNG\r\n\x1a\n';i=8;idat=b''
 while i<len(png):
  n=struct.unpack_from('>I',png,i)[0];kind=png[i+4:i+8];data=png[i+8:i+8+n];crc=struct.unpack_from('>I',png,i+8+n)[0];assert crc==zlib.crc32(kind+data)&0xffffffff
  if kind==b'IDAT':idat+=data
  i+=12+n
 expected=pixels if order=='RGB' else b''.join(pixels[i:i+3][::-1] for i in range(0,len(pixels),3))
 assert zlib.decompress(idat)==b'\0'+expected[:6]+b'\0'+expected[6:];cases+=1
subprocess.run(['sh','-n',str(H/'capture-ready.sh')],check=True)
with tempfile.TemporaryDirectory(prefix='e900-snapshot-client-') as t:
 root=Path(t);attr=root/'attr';attr.touch();folder=root/'captures'
 original=(H/'capture-ready.sh').read_text();script=original.replace('attr=/sys/class/vdin/vdin1/attr','attr='+shlex.quote(str(attr))).replace('folder=/storage/e900-capture','folder='+shlex.quote(str(folder)))
 for fail in [False,True]:
  shim=r'''printf() {
 if [ "$1" = 'capture_ready %s\n' ]; then
  cp SOURCE "$2"
  return STATUS
 fi
 command printf "$@"
}
sync() { :; }
'''.replace('SOURCE',shlex.quote(str(H/'synthetic.e9cap'))).replace('STATUS','1' if fail else '0')
  f=root/'capture.sh';f.write_text('#!/bin/sh\n'+shim+script);name='fail' if fail else 'ok'
  r=subprocess.run(['sh',str(f),name],capture_output=True,text=True);assert (r.returncode!=0)==fail
  final=folder/(name+'.e9cap');assert final.exists()!=fail and not Path(str(final)+'.partial').exists()
  if final.exists():assert final.read_bytes()==b
  cases+=1
 r=subprocess.run(['sh',str(f),'../escape'],capture_output=True);assert r.returncode==2;cases+=1
 # A slow/failing system-wide sync must be bypassable for continuous
 # calibration, while default publication keeps its existing sync behavior.
 shim=shim.replace('return 1', 'return 0').replace('sync() { :; }','sync() { return 99; }')
 f.write_text('#!/bin/sh\n'+shim+script)
 r=subprocess.run(['sh',str(f),'skip_sync'],env=dict(os.environ,E900_CAPTURE_SKIP_SYNC='1'),capture_output=True)
 assert r.returncode==0 and (folder/'skip_sync.e9cap').read_bytes()==b;cases+=1
 r=subprocess.run(['sh',str(f),'default_sync'],env=dict(os.environ,E900_CAPTURE_SKIP_SYNC='0'),capture_output=True)
 assert r.returncode==99;cases+=1

with tempfile.TemporaryDirectory(prefix='e900-capture-clock-') as t:
 root=Path(t);attr=root/'attr';attr.touch();gate=root/'gate';gate.touch();irq=root/'interrupts';folder=root/'captures'
 script=(H/'capture-ready.sh').read_text().replace('attr=/sys/class/vdin/vdin1/attr','attr='+shlex.quote(str(attr))).replace('folder=/storage/e900-capture','folder='+shlex.quote(str(folder))).replace('/sys/class/vpu/gate',str(gate)).replace('/proc/interrupts',str(irq))
 for no_gate in [False,True]:
  for fresh in [False,True]:
   if no_gate:
    if gate.exists():gate.unlink()
   else:gate.write_text('')
   irq.write_text('42: 0 0 0 0 GIC-0 117 Edge vdin1-irq\n')
   update='command printf "%s\\n" "42: 1 0 0 0 GIC-0 117 Edge vdin1-irq" > '+shlex.quote(str(irq)) if fresh else ':'
   shim=r'''printf() {
  if [ "$1" = 'w 72 1\n' ]; then
   :
  elif [ "$1" = 'capture_ready %s\n' ]; then
   cp SOURCE "$2"
   return 0
  fi
  command printf "$@"
 }
 sync() { :; }
 sleep() { UPDATE; }
 '''.replace('UPDATE',update).replace('SOURCE',shlex.quote(str(H/'synthetic.e9cap')))
   f=root/'capture.sh';f.write_text('#!/bin/sh\n'+shim+script);name=('nogate_' if no_gate else 'gate_')+('fresh' if fresh else 'stale')
   result=subprocess.run(['sh',str(f),name],env=dict(os.environ,E900_CAPTURE_NO_GATE='1' if no_gate else '0'),capture_output=True,text=True)
   assert not gate.exists() if no_gate else gate.read_text()=='w 72 1\n'
   assert (result.returncode==0)==fresh,result.stderr
   assert (folder/(name+'.e9cap')).exists()==fresh
   if not fresh:assert 'No fresh VDIN interrupt' in result.stderr
   cases+=1
print('PASS:',cases,'client cases: packet/PNG validity, publication cleanup, shared-clock recovery and stale-IRQ rejection.')
(H/'client-host-checks.json').write_text(json.dumps({'cases':cases,'scope':'Synthetic C-generated packet plus mocked collector kernel-store command. No real sysfs or device capture invoked.'},indent=2)+'\n')
