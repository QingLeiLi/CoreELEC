from pathlib import Path
import subprocess,json,hashlib
p=Path(__file__).resolve().parent
ff='/Users/lql/Downloads/ffmpeg'
base='zscale=pin=bt709:tin=bt709:min=bt709:rin=limited:p=bt709:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le,'
settings=[('HDR10','smpte2084',16,'master-display=G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L(10000000,50):max-cll=100,100:hdr10=1'),('HLG','arib-std-b67',18,'')]
report=[]
for label,transfer,tr,extra in settings:
 short=p/(label+'-5s.mp4');out=p/('Test-'+label+'-HEVC-720p-20min.mp4')
 vf=base+'zscale=pin=bt709:tin=linear:min=gbr:rin=full:p=bt2020:t='+transfer+':m=bt2020nc:r=limited:npl=100,format=yuv420p10le'
 params='log-level=error:pools=2:frame-threads=2:bframes=0:repeat-headers=1:keyint=30:min-keyint=30:scenecut=0:colorprim=9:transfer='+str(tr)+':colormatrix=9'+(':'+extra if extra else '')
 cmd=[ff,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i',"smptehdbars=size=1280x720:rate=30,drawbox=x=0:y=640:w=1280:h=20:color=white:t=fill:enable='lt(mod(t,2),1)'",'-t','5','-vf',vf,'-c:v','libx265','-preset','ultrafast','-crf','22','-x265-params',params,'-color_primaries','bt2020','-color_trc',transfer,'-colorspace','bt2020nc','-color_range','tv','-tag:v','hvc1','-an',str(short)]
 subprocess.run(cmd,check=True)
 subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-stream_loop','-1','-i',str(short),'-t','1200','-c','copy','-tag:v','hvc1','-movflags','+faststart',str(out)],check=True)
 verify=subprocess.run([ff,'-hide_banner','-i',str(out),'-map','0:v:0','-frames:v','1','-vf','showinfo','-f','null','-'],capture_output=True,text=True,check=True).stderr
 (p/(label+'-verify.txt')).write_text(verify)
 assert 'yuv420p10le' in verify and 'bt2020' in verify and transfer in verify
 if label=='HDR10':assert 'Mastering display' in verify and 'Content light level' in verify
 report.append(dict(format=label,file=out.name,sha256=hashlib.sha256(out.read_bytes()).hexdigest(),bytes=out.stat().st_size,command=cmd,scope='Synthetic diagnostic scene converted from BT709 into actual BT2020/PQ or HLG pixels; not a calibrated HDR grading reference'))
 print(label,'ready',out.stat().st_size,flush=True)
(p/'samples.json').write_text(json.dumps(report,indent=2)+'\n')
