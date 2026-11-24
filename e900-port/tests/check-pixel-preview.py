#!/usr/bin/env python3
"""Check byte unpacking and explicit YUV interpretation against known colors."""
import importlib.util
from pathlib import Path
import struct
import zlib
P=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('vdin_preview',P/'scripts/inspect-vdin-snapshot.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
# Eight pixels, crossing 64-bit words and three-byte pixel boundaries.
yuv=bytes([81,90,240]*4+[235,128,128]*4)
packed=b''.join(yuv[i:i+8][::-1] for i in range(0,len(yuv),8))
rgb=m.decode_yuv444_bt601(packed,8,True)
assert rgb==bytes([255,0,0]*4+[255,255,255]*4)
assert m.decode_yuv444_bt601(bytes([16,128,128]*8),8)==bytes(24)
try:m.decode_yuv444_bt601(bytes(18),6,True)
except ValueError:pass
else:raise AssertionError('Partial active-row word was silently unpacked')
png=m.png(8,1,rgb,'RGB');i=8;idat=b''
while i<len(png):
 n=struct.unpack_from('>I',png,i)[0];kind=png[i+4:i+8];payload=png[i+8:i+8+n]
 assert zlib.crc32(kind+payload)&0xffffffff==struct.unpack_from('>I',png,i+8+n)[0]
 if kind==b'IDAT':idat+=payload
 i+=12+n
assert zlib.decompress(idat)==b'\0'+rgb
print('PASS: known red/white/black pixels across 64-bit packing boundaries; PNG payload and CRC; incomplete-row rejection')
print('Hardware layout calibration is separately recorded in LEGACY-LOOPBACK-CALIBRATION-20261124.md.')
