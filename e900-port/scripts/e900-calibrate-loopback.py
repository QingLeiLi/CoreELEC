#!/usr/bin/env python3
"""Keep ONE legacy VDIN session across first playback and Stop/replay.

Requires a fresh boot with completed video initialization and idle Kodi.
Starts/stops the chosen sample and existing diagnostic VDIN service. Does not
use arbitrary register access. Optional GEN3/OSD experiments are explicit and
mutually exclusive; policy is restored on exit. --control-only avoids VDIN.
"""
import argparse
import runpy
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample', default='/storage/videos/Test-H264-720p-60s.mp4')
    p.add_argument('--output', default='/storage/e900-loopback-pairs')
    local_debug=Path(__file__).resolve().with_name('e900-debug.py')
    p.add_argument('--debug-tool', default=str(local_debug) if local_debug.exists() else '/storage/e900-debug.py')
    p.add_argument('--wait', type=int, default=18)
    p.add_argument('--gen3-experiment', action='store_true', help='After baseline repeat, explicitly enable the source GEN3 experiment for a third playback; restore on exit')
    p.add_argument('--pipeline-pixels', action='store_true', help='Explicit legacy sparse pixel experiment; default off for loopback calibration')
    p.add_argument('--control-only', action='store_true', help='Collect state/Canvas only; do not start VDIN')
    p.add_argument('--osd-blender-only', action='store_true', help='Enable source OSD experiment before first playback; restore on exit')
    p.add_argument('--osd-cycle', action='store_true', help='Explicitly hide/restore OSD during first playback; requires --control-only')
    a = p.parse_args()
    if a.gen3_experiment and a.osd_blender_only:
        p.error('GEN3 and OSD experiments must use separate boots')
    if a.osd_cycle and not a.control_only:
        p.error('--osd-cycle requires --control-only: validate scene response separately')
    if not 15 <= a.wait <= 20:
        p.error('--wait must be 15..20 seconds; use the known 60-second sample')
    scripts = Path(__file__).resolve().parent
    for f in [Path(a.sample), Path(a.debug_tool), scripts/'e900-start-capture.sh', scripts/'e900-capture-ready.sh']:
        if not f.is_file():
            p.error('Missing '+str(f))
    if Path('/sys/module/amvideo/parameters/gxlx2_hw_init_status').read_text().strip() != '2':
        p.error('Complete initialization before calibration')
    decoder = Path('/sys/class/vdec/vdec_status')
    if decoder.read_text().strip() != 'No vdec.':
        p.error('Decoder active; refusing to interrupt another playback')
    # Record the UI state at each packet, not just at the earlier Canvas snapshot.
    # A menu in a downstream frame must not be mislabeled as missing video.
    kodi_state = runpy.run_path(a.debug_tool)['kodi_state']
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    output = Path(a.output); output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output).free < 16*1024*1024:
        p.error('At least16MiB free required')
    out = output/(boot+'-'+str(time.time_ns())); out.mkdir()
    report = {'schema':1,'boot_id':boot,'screen_observed':False,'output':str(out),
              'point':'display_canvas_via_ge2d' if a.control_only else 'legacy_ENCP_output_loopback','sample':a.sample,
              'control_only':a.control_only, 'osd_cycle':a.osd_cycle, 'pipeline_pixels':a.pipeline_pixels,
              'vdin_start_count':0,'steps':[], 'captures':[]}
    started = False; playing = False
    gen3 = Path('/sys/module/amvideo/parameters/gxlx2_gen3_clear_high')
    gen3_original = None
    osd = Path('/sys/module/fb/parameters/gxlx2_osd_blender_only')
    blank = Path('/sys/class/graphics/fb0/blank')
    osd_original = None
    if a.osd_blender_only or a.osd_cycle:
        if not osd.exists() or not blank.exists():
            p.error('This kernel has no OSD source experiment; no playback started')
        osd_original = osd.read_text()
        report['osd_original'] = osd_original.strip()
        if gen3.exists() and gen3.read_text().strip() not in ('N', '0'):
            p.error('Disable GEN3 experiment before OSD test')
        if Path('/sys/module/rdma/parameters/enable').read_text().strip() != '1,0':
            p.error('Restore default RDMA before OSD test')
    if a.gen3_experiment:
        if not gen3.exists():
            p.error('This kernel has no source GEN3 experiment; no playback started')
        gen3_original = gen3.read_text()
        report['gen3_original'] = gen3_original.strip()

    def save():
        report['checkpoint_monotonic'] = time.monotonic()
        tmp=out/'result.json.partial'; tmp.write_text(json.dumps(report,indent=2)+'\n');tmp.rename(out/'result.json')

    def run(argv, timeout=12):
        report['pending']={'argv':argv,'monotonic':time.monotonic()};save()
        r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
        report['steps'].append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'monotonic':time.monotonic()})
        report.pop('pending',None);save()
        if r.returncode:
            raise RuntimeError('Command failed: '+repr(argv)+' '+r.stderr[-500:])
        return r.stdout

    def active():
        text=decoder.read_text()
        if 'ammvdec_h264' not in text:raise RuntimeError('No active H264; refusing to label old data as video')
        return text

    def snapshot(label):
        command=['python3',a.debug_tool,'snapshot','--label',label,'--pixels']
        # Only the active playback scan is useful. Stopped state remains software
        # evidence; it must not request reads from powered-down pixel banks.
        if a.pipeline_pixels and label != 'stopped_unobserved' and Path('/sys/module/amvideo/parameters/gxlx2_pixel_scan').exists():
            command.append('--pipeline-pixels')
        result=run(command,timeout=25)
        report[label+'_state_path']=result.strip();save()

    inspector=runpy.run_path(str(scripts/'inspect-vdin-snapshot.py'))
    def pair(label):
        if a.control_only:
            return
        for i in range(2):
            active()
            observation_start=time.monotonic()
            gui_before=kodi_state()
            name='PAIR_'+str(time.time_ns())+'_'+label+'_'+str(i)
            packet=run(['env','E900_CAPTURE_SKIP_SYNC=1','sh',str(scripts/'e900-capture-ready.sh'),name],timeout=12).strip().splitlines()[-1]
            gui_after=kodi_state()
            observation_end=time.monotonic()
            source=Path(packet);target=out/(label+'_'+str(i)+'.e9cap')
            data=source.read_bytes()
            target.write_bytes(data)
            meta,_=inspector['inspect'](data)
            if not meta['slot_association_valid']:
                raise ValueError('Invalid/mismatched v2 VDIN slot association or payload CRC')
            report['captures'].append({'phase':label,'gui_before':gui_before,'gui_after':gui_after,'observation_start':observation_start,'observation_end':observation_end,'file':target.name,'source':packet,'sha256':hashlib.sha256(data).hexdigest(),'completion_count':meta['completion_count'],'frame_timestamp':meta['frame_timestamp'],'sample_jiffies':meta['sample_jiffies'],'slot_association_valid':meta['slot_association_valid'],'decoder':active()});save()
            time.sleep(1)
    try:
        run(['python3',a.debug_tool,'arm','--budget','256'])
        if osd_original is not None:
            osd.write_text('Y\n' if a.osd_blender_only else 'N\n')
            report['osd_requested']=osd.read_text().strip();save()
        run(['kodi-send','--action=SetVolume(0)'])
        run(['kodi-send','--action=PlayMedia('+a.sample+')']);playing=True
        time.sleep(a.wait);active();snapshot('first_unobserved')
        # Exactly one start per boot. Keep the service alive during Stop/replay;
        # capture-ready uses its managed shared-clock API and checks fresh IRQs.
        if not a.control_only:
            run(['sh',str(scripts/'e900-start-capture.sh')],timeout=35)
            started=True;report['vdin_start_count']=1;save()
        pair('first')
        if a.osd_cycle:
            blank.write_text('1\n');time.sleep(1);snapshot('osd_hidden_unobserved')
            blank.write_text('0\n');time.sleep(1);snapshot('osd_restored_unobserved')
        run(['python3',a.debug_tool,'arm','--budget','256'])
        run(['kodi-send','--action=Stop']);time.sleep(2)
        snapshot('stopped_unobserved')
        run(['kodi-send','--action=PlayMedia('+a.sample+')'])
        time.sleep(a.wait);active();snapshot('repeat_unobserved');pair('repeat')
        if a.gen3_experiment:
            gen3.write_text('Y\n')
            run(['python3',a.debug_tool,'arm','--budget','256'])
            run(['kodi-send','--action=Stop']);time.sleep(2)
            run(['kodi-send','--action=PlayMedia('+a.sample+')'])
            time.sleep(a.wait);active();snapshot('gen3_unobserved');pair('gen3')
        report['status']='collected_not_pixel_verified'
    except Exception as e:
        report['status']='failed';report['error']=str(e);report['traceback']=traceback.format_exc()
    finally:
        # Stop the DMA service before tearing down the decoder/DI clocks.
        if started:
            try:run(['sh','-c','printf "v4l2stop\\n" > /sys/class/vdin/vdin1/attr'])
            except Exception as e:report['cleanup_error']=str(e)
        if playing:
            try:run(['kodi-send','--action=Stop'])
            except Exception as e:report['player_cleanup_error']=str(e)
        if osd_original is not None:
            try:
                blank.write_text('0\n')
                osd.write_text(osd_original)
                report['osd_restored']=osd.read_text().strip()
            except Exception as e:report['osd_restore_error']=str(e)
        if gen3_original is not None:
            try:
                gen3.write_text(gen3_original)
                report['gen3_restored']=gen3.read_text().strip()
            except Exception as e:report['gen3_restore_error']=str(e)
        try:run(['python3',a.debug_tool,'disarm'])
        except Exception as e:report['disarm_error']=str(e)
        report['dmesg_saved']=False
        try:
            d=subprocess.run(['dmesg'],capture_output=True,text=True,timeout=5)
            (out/'dmesg.txt').write_text(d.stdout);report['dmesg_saved']=d.returncode==0
        except Exception as e:report['dmesg_error']=str(e)
        save()
    print(out,flush=True)
    print(json.dumps({k:report.get(k) for k in ['status','error','captures']},indent=2),flush=True)
    return 0 if report.get('status')=='collected_not_pixel_verified' else 1

if __name__=='__main__':
    sys.exit(main())
