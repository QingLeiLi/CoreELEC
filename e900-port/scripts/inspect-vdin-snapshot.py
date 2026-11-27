#!/usr/bin/env python3
"""Validate an E9VDIN1 packet; preview only with an explicit RGB byte order."""
import argparse,collections,hashlib,json,struct,zlib
from pathlib import Path
HEADER=struct.Struct('<8s10I4Q')
NAMES=['version','header_bytes','width','height','format_convert','active_row_bytes','source_stride','frame_index','bitdepth','flags','frame_timestamp','sample_jiffies','completion_count','payload_bytes']
EXT_V2=struct.Struct('<4Q4I2Q')
EXT_NAMES=['completion_generation','done_jiffies','slot_timestamp','postcopy_generation','slot_session','expected_canvas','observed_canvas','payload_crc32','slot_dma_address','payload_dma_address']
def inspect(data):
 if len(data)<HEADER.size:raise ValueError('Truncated snapshot header')
 values=HEADER.unpack_from(data);meta=dict(zip(NAMES,values[1:]))
 if values[0]!=b'E9VDIN1\0':raise ValueError('Wrong snapshot magic')
 version=meta['version'];header_bytes=meta['header_bytes']
 if (version,header_bytes) not in ((1,HEADER.size),(2,HEADER.size+EXT_V2.size)):
  raise ValueError('Unsupported snapshot version/header')
 if len(data)<header_bytes:raise ValueError('Truncated snapshot extension')
 if not 0<meta['width']<=1920 or not 0<meta['height']<=1080:raise ValueError('Invalid snapshot dimensions')
 row=meta['width']*3;expected=row*meta['height']
 if meta['active_row_bytes']!=row or meta['source_stride']<row or meta['frame_index']>=10:raise ValueError('Invalid snapshot layout/index')
 if meta['bitdepth']!=8 or (meta['flags']!=3 if version==1 else (meta['flags']&3)!=3):raise ValueError('Unsupported bit depth or incomplete software checks')
 if meta['payload_bytes']!=expected or len(data)!=header_bytes+expected:raise ValueError('Truncated payload or trailing bytes')
 pixels=data[header_bytes:]
 if version==2:
  meta.update(zip(EXT_NAMES,EXT_V2.unpack_from(data,HEADER.size)))
  meta['payload_crc32_valid']=zlib.crc32(pixels)==meta['payload_crc32']
  meta['slot_association_valid']=(
   meta['flags']==255 and meta['completion_generation']>0 and
   meta['completion_generation']==meta['postcopy_generation'] and
   meta['slot_session']>0 and 0<meta['done_jiffies']<=meta['slot_timestamp']==meta['frame_timestamp']<=meta['sample_jiffies'] and
   meta['expected_canvas']==meta['observed_canvas'] and meta['expected_canvas']<=255 and
   meta['slot_dma_address']>0 and meta['slot_dma_address']==meta['payload_dma_address'] and
   meta['payload_crc32_valid'])
 else:
  meta['slot_association_valid']=False
 counts=collections.Counter(pixels[i:i+3] for i in range(0,len(pixels),3))
 meta.update(packet_sha256=hashlib.sha256(data).hexdigest(),payload_sha256=hashlib.sha256(pixels).hexdigest(),unique_triplets=len(counts),dominant_triplets=[{'bytes':list(c),'pixels':n} for c,n in counts.most_common(12)],interpretation='Packed three-byte samples; channel order and color space require calibration. Slot addresses are driver software values, not Canvas LUT hardware readback; association and CRC do not prove pixel freshness or HDMI output.')
 return meta,pixels
def png(width,height,pixels,order):
 if order=='BGR':pixels=b''.join(pixels[i:i+3][::-1] for i in range(0,len(pixels),3))
 stride=width*3
 raw=b''.join(b'\0'+pixels[i*stride:(i+1)*stride] for i in range(height))
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
def decode_yuv444_bt601(pixels,width,reverse64=False):
 # Explicitly selected format; never guess channel/byte order from content.
 if reverse64:
  if (width*3)%8:raise ValueError('64-bit unpack requires complete words per active row')
  pixels=b''.join(pixels[i:i+8][::-1] for i in range(0,len(pixels),8))
 rgb=bytearray(len(pixels))
 for i in range(0,len(pixels),3):
  y,u,v=pixels[i:i+3];c=y-16;d=u-128;e=v-128
  rgb[i:i+3]=bytes(max(0,min(255,x)) for x in ((298*c+409*e+128)>>8,(298*c-100*d-208*e+128)>>8,(298*c+516*d+128)>>8))
 return bytes(rgb)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('packet',type=Path);p.add_argument('--out',type=Path);p.add_argument('--rgb-order',choices=['RGB','BGR']);p.add_argument('--yuv444-bt601',action='store_true');p.add_argument('--reverse64',action='store_true');args=p.parse_args()
 if (args.rgb_order or args.yuv444_bt601) and not args.out:p.error('Preview requires --out')
 if args.rgb_order and args.yuv444_bt601:p.error('Select RGB or YUV preview, not both')
 if args.reverse64 and not args.yuv444_bt601:p.error('--reverse64 requires --yuv444-bt601')
 meta,pixels=inspect(args.packet.read_bytes())
 if args.rgb_order:
  meta['preview_assumption']=args.rgb_order+' channel order; not validated for this VDIN format'
 if args.yuv444_bt601:
  if meta['format_convert']!=2:raise ValueError('YUV444 preview requires verified format_convert=2')
  meta['preview_assumption']='BT.601 limited YUV444; reverse64='+str(args.reverse64)+'; calibrated on E900 legacy ENCP first-play capture281'
 if args.out:
  args.out.mkdir(parents=True,exist_ok=True)
  (args.out/'snapshot.raw').write_bytes(pixels)
  (args.out/'snapshot.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
  if args.rgb_order:
   (args.out/'preview.png').write_bytes(png(meta['width'],meta['height'],pixels,args.rgb_order))
  if args.yuv444_bt601:
   rgb=decode_yuv444_bt601(pixels,meta['width'],args.reverse64)
   (args.out/'preview.png').write_bytes(png(meta['width'],meta['height'],rgb,'RGB'))
 print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
