#!/usr/bin/env python3
"""Validate an E9VDIN1 packet; preview only with an explicit RGB byte order."""
import argparse,collections,hashlib,json,struct,zlib
from pathlib import Path
HEADER=struct.Struct('<8s10I4Q')
NAMES=['version','header_bytes','width','height','format_convert','active_row_bytes','source_stride','frame_index','bitdepth','flags','frame_timestamp','sample_jiffies','completion_count','payload_bytes']
def inspect(data):
 if len(data)<HEADER.size:raise ValueError('Truncated snapshot header')
 values=HEADER.unpack_from(data);meta=dict(zip(NAMES,values[1:]))
 if values[0]!=b'E9VDIN1\0':raise ValueError('Wrong snapshot magic')
 if meta['version']!=1 or meta['header_bytes']!=HEADER.size:raise ValueError('Unsupported snapshot version/header')
 if not 0<meta['width']<=1920 or not 0<meta['height']<=1080:raise ValueError('Invalid snapshot dimensions')
 row=meta['width']*3;expected=row*meta['height']
 if meta['active_row_bytes']!=row or meta['source_stride']<row or meta['frame_index']>=10:raise ValueError('Invalid snapshot layout/index')
 if meta['bitdepth']!=8 or meta['flags']!=3:raise ValueError('Unsupported bit depth or incomplete software checks')
 if meta['payload_bytes']!=expected or len(data)!=HEADER.size+expected:raise ValueError('Truncated payload or trailing bytes')
 pixels=data[HEADER.size:];counts=collections.Counter(pixels[i:i+3] for i in range(0,len(pixels),3))
 meta.update(packet_sha256=hashlib.sha256(data).hexdigest(),payload_sha256=hashlib.sha256(pixels).hexdigest(),unique_triplets=len(counts),dominant_triplets=[{'bytes':list(c),'pixels':n} for c,n in counts.most_common(12)],interpretation='Packed three-byte samples; channel order and color space require calibration. Software checks do not prove HDMI output.')
 return meta,pixels
def png(width,height,pixels,order):
 if order=='BGR':pixels=b''.join(pixels[i:i+3][::-1] for i in range(0,len(pixels),3))
 stride=width*3
 raw=b''.join(b'\0'+pixels[i*stride:(i+1)*stride] for i in range(height))
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('packet',type=Path);p.add_argument('--out',type=Path);p.add_argument('--rgb-order',choices=['RGB','BGR']);args=p.parse_args()
 if args.rgb_order and not args.out:p.error('--rgb-order requires --out')
 meta,pixels=inspect(args.packet.read_bytes())
 if args.rgb_order:
  meta['preview_assumption']=args.rgb_order+' channel order; not validated for this VDIN format'
 if args.out:
  args.out.mkdir(parents=True,exist_ok=True)
  (args.out/'snapshot.raw').write_bytes(pixels)
  (args.out/'snapshot.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
  if args.rgb_order:
   (args.out/'preview.png').write_bytes(png(meta['width'],meta['height'],pixels,args.rgb_order))
 print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
