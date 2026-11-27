#!/usr/bin/env python3
"""Collect bounded, source-defined intermediate pixel candidates; no address API.

Raw words and both packing hypotheses are retained. A completed scan is not
hardware/scene calibration and does not itself prove which physical tap works.
"""
import argparse
import fcntl
import json
from pathlib import Path
import re
import time

PORTS = {1:'vadj1_input',33:'vadj1_output',2:'vadj2_input',34:'vadj2_output',
         8:'postblend_input',40:'postblend_output',16:'osd1_input',48:'osd1_output'}
REASONS = {0:'none',1:'inactive_or_bus_unavailable',2:'epoch_or_geometry_changed',
           3:'selector_contended',4:'restore_readback_failed',5:'cancelled'}


def fields(text):
    return dict(re.findall(r'([A-Za-z0-9_]+)=([^\s]+)', text))


def decode_record(line):
    row = fields(line)
    required = ('sample','generation','port','grid','x','y','raw0','raw1','frame','pts')
    if set(row) != set(required):
        raise ValueError('Incomplete/unknown pixel record fields')
    row = {key:int(row[key],16 if key in ('raw0','raw1') else 10) for key in required}
    if not 0 <= row['sample'] < 128 or row['port'] not in PORTS or row['grid'] not in (0,1):
        raise ValueError('Invalid fixed probe record')
    a,b = row['raw0'],row['raw1']
    if not 0 <= a <= 0xffffffff or not 0 <= b <= 0xffffffff:
        raise ValueError('Invalid raw word')
    row['tap_candidate'] = PORTS[row['port']]
    row['legacy12_components'] = [((b&15)<<8)|((a>>24)&255),(a>>12)&4095,a&4095]
    row['g12_10_components'] = [(a>>20)&1023,(a>>10)&1023,a&1023]
    return row


def collect(root=Path('/'), timeout=15):
    root=Path(root)
    base=root/'sys/module/amvideo/parameters'
    scan,page,data=[base/name for name in ('gxlx2_pixel_scan','gxlx2_pixel_page','gxlx2_pixel_data')]
    boot_path=root/'proc/sys/kernel/random/boot_id'
    boot_id=boot_path.read_text().strip() if boot_path.is_file() else None
    report={'boot_id':boot_id,'schema':1,'point':'legacy_vpp_matrix_sparse_candidates',
            'calibration_status':'unverified','physical_tap_verified':False,
            'atomic_frame':False,'records':[], 'monotonic_start':time.monotonic()}
    if not all(p.is_file() for p in (scan,page,data)):
        return dict(report,status='unavailable',error='Kernel has no fixed intermediate pixel probe')
    started=False;generation=None;original_page=None
    lockpath=root/'run/e900-pixel-probe.lock';lockpath.parent.mkdir(parents=True,exist_ok=True)
    with lockpath.open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(report,status='busy',error='Another pixel collector owns the paged result')
        try:
            before=fields(scan.read_text());report['before']=before
            if before.get('status') in ('1','2','6') or before.get('owned')=='1':
                raise RuntimeError('Prior scan active or needs restore; refusing to overwrite it')
            original_page=page.read_text().strip()
            generation=(int(before['generation'])+1)&0xffffffff
            scan.write_text('1\n');started=True
            deadline=time.monotonic()+timeout
            while True:
                current=fields(scan.read_text());report['state']=current
                if int(current['generation'])!=generation:
                    raise RuntimeError('Unexpected scan generation')
                if current['status']=='3':break
                if current['status'] not in ('1','2'):
                    reason=REASONS.get(int(current.get('reason',0)),'unknown')
                    raise RuntimeError('Pixel scan invalid: '+reason+' guard='+current.get('guard','unknown'))
                if time.monotonic()>=deadline:raise TimeoutError('Pixel scan did not complete before deadline')
                time.sleep(0.05)
            if current.get('count')!='128' or current.get('owned')!='0' or current.get('restored')!='1':
                raise RuntimeError('Incomplete scan or probe fields were not restored')
            raw_pages=[]
            for index in range(8):
                page.write_text(str(index)+'\n');raw=data.read_text();raw_pages.append(raw)
                report['records'].extend(decode_record(line) for line in raw.splitlines() if line.strip())
            report['raw_pages']=raw_pages
            after=fields(scan.read_text());report['after']=after
            if after.get('generation')!=str(generation) or after.get('status')!='3':
                raise RuntimeError('Pixel results changed while reading pages')
            records=report['records']
            if len(records)!=128 or [r['sample'] for r in records]!=list(range(128)):
                raise RuntimeError('Missing/duplicate/out-of-order samples')
            for row in records:
                if row['generation']!=generation or row['port']!=list(PORTS)[row['sample']//16] or row['grid']!=(row['sample']%16)//8:
                    raise RuntimeError('Mixed generation or unexpected tap/grid')
            report['status']='collected_uncalibrated'
        except Exception as error:
            report.update(status='failed',error=str(error))
        finally:
            # Cancel only this generation. Never cancel another actor's scan.
            if started:
                try:
                    state=fields(scan.read_text())
                    if generation is None or state.get('generation')==str(generation):
                        scan.write_text('0\n')
                        limit=time.monotonic()+2
                        while fields(scan.read_text()).get('owned')=='1' and time.monotonic()<limit:
                            time.sleep(0.05)
                        report['cleanup_state']=fields(scan.read_text())
                        if report['cleanup_state'].get('owned')=='1':
                            report['restore_pending']=True
                            report['status']='failed'
                except Exception as error:report['cleanup_error']=str(error);report['status']='failed'
            if original_page is not None:
                try:page.write_text(original_page+'\n')
                except OSError as error:report['page_restore_error']=str(error);report['status']='failed'
            report['monotonic_end']=time.monotonic()
    return report



def compare_scans(left, right):
    """Compare corresponding raw points; never infer a root cause from zeros."""
    result={'status':'unavailable','calibration_status':'unverified',
            'physical_tap_verified':False,'groups':[],
            'note':'Sparse interval samples; moving content and uncalibrated taps prevent automatic localization.'}
    if any(x.get('status')!='collected_uncalibrated' for x in (left,right)):
        result['error']='Both scans must complete with restored selectors'
        return result
    a,b=left.get('records',[]),right.get('records',[])
    if len(a)!=128 or len(b)!=128:
        return dict(result,status='failed',error='Incomplete records')
    for x,y in zip(a,b):
        if any(x.get(k)!=y.get(k) for k in ('sample','port','grid','x','y')):
            return dict(result,status='incompatible',error='Tap or coordinate grids differ')
    for port,name in PORTS.items():
        for grid in (0,1):
            aa=[x for x in a if x['port']==port and x['grid']==grid]
            bb=[x for x in b if x['port']==port and x['grid']==grid]
            result['groups'].append({'port':port,'tap_candidate':name,'grid':grid,
                'changed_raw_pairs':sum((x['raw0'],x['raw1'])!=(y['raw0'],y['raw1']) for x,y in zip(aa,bb)),
                'left_raw':[[x['raw0'],x['raw1']] for x in aa],
                'right_raw':[[x['raw0'],x['raw1']] for x in bb]})
    result['status']='compared_uncalibrated'
    return result


def render_svg(report):
    """Sparse component previews under two RGB hypotheses; never a frame image."""
    if report.get('status')!='collected_uncalibrated':
        raise ValueError('Refusing to preview failed/incomplete scan')
    rows={(r['port'],r['grid'],r['sample']%8):r for r in report['records']}
    if len(rows)!=128:raise ValueError('Incomplete preview points')
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="480" viewBox="0 0 1080 480">',
         '<rect width="1080" height="480" fill="#fafafa"/>',
         '<text x="12" y="22" font-family="sans-serif" font-size="15" fill="#a00">UNCALIBRATED sparse samples; RGB hypotheses; NOT a screenshot</text>']
    for panel,(key,shift) in enumerate((('legacy12_components',4),('g12_10_components',2))):
        left=12+panel*540
        out.append(f'<text x="{left}" y="48" font-family="sans-serif" font-size="13">{key} (input/output coordinate grids)</text>')
        for pi,(port,name) in enumerate(PORTS.items()):
            for grid in (0,1):
                y=60+(pi*2+grid)*24
                out.append(f'<text x="{left}" y="{y+15}" font-family="monospace" font-size="11">{name} {grid}</text>')
                for col in range(8):
                    row=rows[port,grid,col];rgb=[v>>shift for v in row[key]]
                    color='#'+''.join(f'{v:02x}' for v in rgb)
                    out.append(f'<rect x="{left+180+col*40}" y="{y}" width="38" height="20" fill="{color}" stroke="#888"><title>port={port} grid={grid} x={row["x"]} y={row["y"]} raw0={row["raw0"]:08x} raw1={row["raw1"]:08x}</title></rect>')
    out.append('</svg>')
    return '\n'.join(out)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();result=collect()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    pending=a.out.with_suffix(a.out.suffix+'.partial');pending.write_text(json.dumps(result,indent=2)+'\n');pending.replace(a.out)
    if result['status']=='collected_uncalibrated':
        a.out.with_suffix('.svg').write_text(render_svg(result))
    print(json.dumps({'status':result['status'],'error':result.get('error'),'output':str(a.out)}))
    return 0 if result['status']=='collected_uncalibrated' else 1

if __name__=='__main__':raise SystemExit(main())
