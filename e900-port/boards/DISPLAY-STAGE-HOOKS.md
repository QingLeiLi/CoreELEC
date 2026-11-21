# 显示链路分阶段诊断

补丁0017增加观察点，不修显示路径，不改变初始化顺序，也不增加像素采集点。用于先判断已知的初始化丢写、帧交接、配置落地、混合使能是否存在明确异常。不能凭这些状态宣称某一级的像素正常。

| 阶段 | 新记录 | 如何使用 |
|---|---|---|
| 初始化 | video_hw_init前后VC/HHI/DMC回调就绪状态，以及缺失总线时累计丢弃的写入次数 | 对照初始化代码与播放时补写位置，找出一直没有初始化的配置；计数是总线累计值，不是逐条写入清单 |
| 输入交接 | 帧index/PTS、尺寸、type/bitdepth、来源与目标Canvas、是否更新MIF、是否借用VD2 | 确认显示驱动实际得到帧，检查布局和Canvas切换 |
| VD1/视频处理 | GEN/GEN2/GEN3、Canvas、格式、FIFO、取图范围、缩放相位、矩阵的实际回读 | 区分提交值与当前硬件状态；格式和混合相关寄存器按源码逐项解释 |
| 混合 | 本轮请求的VPP_MISC、实际回读、RDMA视图、视频输出窗口 | 判断视频输入和混合使能是否存在持续缺失，不据单次跨VSYNC差异认定失败 |

运行时回读默认关闭。`/sys/module/amvideo/parameters/gxlx2_stage_samples`只接受0..8；每个入口各有最多8次预算。仅在GXLX2、legacy VPP/MIF、活动的非压缩VD1帧、已发布VC总线、已知legacy寄存器表且未借用VD2时执行回读。其他状态写`output_skipped`，不得把跳过当成黑帧。没有地址输入接口、显示寄存器写入、帧缓冲映射或vframe所有权变化。

在VSYNC内观察同一轮仍持有的帧，不保留指针。RDMA可能尚未锁存本轮提交，因此`live`、`shadow`及本轮帧描述不是原子像素快照；需要连续样本及稳定播放对照，不能仅凭一个Canvas不一致宣布取图故障。输入/输出预算分别计数，使用epoch、PTS、index关联，不能按日志行号强行一一配对。

构建使用decoder / linux，source_trace=false；vdin_capture与当前USB内核保持一致（目前true），避免无关配置切换。保留原216内核及SYSTEM214；只制作独立诊断内核启动配置，不写eMMC。补丁修改linux，兼容工具链缓存继续复用；完整ARM构建及实机回读尚待执行。

构建部署后，播放已有H264样片，再运行：

```sh
sh /storage/e900-collect-display-stages.sh
```

脚本采四批间隔样本，保存启动命令行、VFM、解码前后计数、显示状态、中断和完整dmesg到`/storage/e900-display-stages/<boot-id>-<time>/`，不启动VDIN，不切换OSD、DI、MIF或播放器。若未播放H264或缺少新参数，直接退出。

判读顺序：先看初始化是否丢写及后续是否补齐；再看帧是否交接、Canvas/格式是否持续不匹配；最后看缩放和混合实际状态。如果这些均未出现明确异常，结论应为“状态探针未定位”，继续建立可信的视频专用像素回环，不能把故障强行归给解码器。

主机检查已验证完整补丁集可应用，编译并执行真实hook的预算/入口保护及丢写计数逻辑，确认没有新增显示写入。它不代替ARM驱动编译、硬件地址验证或图像取点验证。

## 构建44763949632实测（2026-11-21）

诊断内核240配SYSTEM214启动成功，216回退内核和三个加载脚本保留。video_hw_init前后VC/HHI/DMC回调均未就绪，VC丢写累计13→22。四批每批8组回读已完成；H264解码计数129→506，无丢帧或软硬错误。显示驱动接收1280×720/NV21帧，PTS推进；实际Canvas在5a5958与605f5e间切换，本轮shadow改变后下一VSYNC的live跟随，证明这些提交实际锁存，不是仅软件计数。

GEN实际38000043、GEN2=1、GEN3=33，格式20310c11；缩放相位aaaac0/aaaa80与软件状态一致。32组混合requested/live/shadow均为100054b0，输出窗口77f/437，VC丢写计数在播放期间稳定41，没有继续增加。原始数据在Mac trial-stage240/e900-display-stages/及盒子/storage/e900-display-stages/，汇总trial-stage240/summary.json。

本轮未请求用户观察HDMI，不得记录新的物理黑屏/恢复结论。已证实初始化阶段异常，以及帧交接和部分寄存器锁存；没有证明MIF实际像素读取、矩阵输出或最终合成像素正确，也未证明9次初始化丢写就是黑屏原因。采集结束已关闭预算、停止播放器，没有启动VDIN或写eMMC。下一步核对初始化缺项是否在播放时补齐。

## FIFO单项诊断241（2026-11-21）

原厂Android反汇编video_init的ffffffc001e57f54..f60明确把CPU0x2a导向与TXL/TXLX相同的FIFO分支，写VD1/VD2 FIFO为0x180。当前源码只列TXL/TXLX，GXLX2未执行，因此此遗漏独立于先前9次已执行但丢弃的初始化写入。240实际回读FIFO为ff00c0。

独立内核241仅在vd_set_dcu普通VD1非压缩帧入口，通过既有VSYNC_WR_MPEG_REG提交VD1 FIFO0x180，保留VD2、空帧、压缩帧的原控制流；原核240及加载脚本保留回退。离线补丁位于一次分支和RET后40字节填充，参数已保存在callee-saved寄存器，LR已入栈，未引入现场物理内存映射或任意寄存器接口。细节和反汇编见Mac trial-fifo241/manifest.json、stub.asm。

241正常启动，32/32次回读变为ff0180（低位大小字段0x180，上位回读状态仍为ff）；解码130→430、错误0，无重启；GEN/格式/缩放/混合主要配置与240一致。播放已停止，等待用户准备后观察HDMI。尚不能声称修复黑屏；没有把这一诊断二进制当作通用源码修复。

## 像素截图243/244（2026-11-21）

用户确认FIFO241试验仍黑屏，单项FIFO修正未解决问题，不重复该试验。按用户要求转向像素证据。243通过标准amvideocap取得640×360完整彩带及白标；Kodi原生截图也有彩带和LIVE243-HARDWARE通知。两张均已实际查看；Kodi截图可能旁路重建视频，不能当作最终混合/HDMI图像。VDIN在截图前后均未取得完成帧，不能记录为黑帧。采集先停止VDIN再停播放器，未重启。

244通过标准/dev/fb0 ioctl/read读取当前页。注意该盒子是64位内核、32位用户态，fb_fix_screeninfo采用compat布局。菜单原始帧及LIVE244-MENU通知正确，alpha全部255；硬解时原始帧含当前LIVE244-HARDWARE通知，视频区域RGB0/alpha0（全图2073600像素，其中1996036个alpha0），已查看RGB及alpha预览。这里只是OSD支路，硬解分层时透明窗口属预期行为，不得解释为VD1像素已黑。最终视频混合前/后的有效取点仍未建立，禁止据此声称完成定位。音量已按用户要求设0并确认，后续测试保持0。数据及PNG位于Mac trial-pixels243/与trial-pixels244/e900-pixels244/；盒子对应/storage/e900-capture/和/storage/e900-pixels244/。

## 采集完成标志顺序245（2026-11-21）

原厂3.14 vdin_write_done_check在ffffffc0017820e4读取COM_STATUS0 bit2，只有检测到1才进入ffffffc001782110的清除流程；当前4.9则先清除再读取。诊断245基于240，只把该helper换为原厂读/ACK顺序，没有沿用无效FIFO241变更，没有绕过完成标志或队列/DMA所有权。源补丁0018只对GXLX2使用此顺序，其余CPU保持原序列；真实C逻辑的锁存标志模型及全部CPU/状态对照通过，完整补丁可应用检查通过。源码尚未ARM重编译；实机使用独立离线诊断内核。

245得到菜单对照及8张连续硬解回环图，IRQ2471、wr_done_abnormal_cnt0、frame_cnt1651、puted_frame_cnt829。实际查看M245/H245_0/H245_2/H245_7，图像均为菜单底图，硬解LIVE245通知没有出现；首帧有播放标记且后续少量变化，但不能确认为当前硬解输出。原生GUI245截图仍是正常彩带。不得把完成计数或这些菜单图当作已定位黑屏的证据。数据在Mac trial-capture245/pixels/。

下一取点246按原厂VIDEO配置组合：VIUIN特殊VIDEO分支两个编译副本均覆盖，mux4/VIU_MISC_CTRL1 bit28、输入AFIFO e4、信号YUV444。保留base端口入口限制和严格完成/所有权检查，以独立内核测试；不改变显示修复参数。


## VIDEO取点246/247（2026-11-21）

246采用原厂VIDEO组合配置，当前硬解窗口12005，解码159→744且硬件错误0；137次IRQ、136次缺少完成标志、完成帧0。247同一内核正常重启后，采集输入改1280×720@30匹配测试视频，保持HDMI1080p60不变；解码159→446，IRQ138、缺少完成标志137、完成帧0。两轮都正常停止采集后停止播放器。不得将无完成帧解释成黑帧或VD1已黑。246 amvideocap实际像素已下载并查看，完整彩带及白标正常；取点至最终合成尚未建立。

接下来248回到245能够采帧的普通编码器回环，但改为先进入硬解再启动采集，并连续采硬解/软件渲染/菜单三组，检查245菜单残像是否与启动时机或取点支路有关。音量继续0，不要求用户观察HDMI。


## 有效动态图对照248（2026-11-21）

245内核，先启动硬解且确认Fullscreen video，再启动普通编码器回环。H248_0未获得完成帧；本轮amvdec_h264解码196帧、错误/丢帧0。切换软件渲染后，同一采集会话连续取得S248_0..2，实际查看0/2：完整彩带、不同位置的白标，0含LIVE248-SW通知。进入home后M248_0..2均成功，实际查看0含菜单/视频底图及LIVE248-MENU通知。说明回环能够跟随当前软件/菜单动态图；不再仅凭完成计数验证。报告IRQ1447、frame_cnt867、puted436、wr_done_abnormal151；最后先停止VDIN再停止播放，原amcodec设置恢复，音量0。

硬解输入像素彩带正常，软件渲染进入输出回环正常；硬解的视频层到编码器回环这一段仍异常。不能将硬解的无完成帧直接称为黑图，也不能据此在VD1 MIF、缩放/混合、回环同步之间作唯一归因。下一诊断应围绕这些未证实阶段，不重复OSD alpha、解码计数和已经否定的FIFO241。证据位于Mac trial-pixels248/；软件帧PNG已实际查看。当前USB恢复245内核，未写eMMC。


## VD1开关对照249（2026-11-21）

同一次H264硬解159→721帧、错误0，采集开始后：VD1开启时无完成帧（171次缺标志）；关闭VD1取得D249_0，实际查看为黑底及D249_0通知。重新开启后H249_1计数增长但像素与D249_0完全相同；再切home且确认窗口10000，M249_0依旧相同。三张原始payload SHA256均1f1aa296eab0d3811859d344665770fb066978aec8db3d999d6eb9873f84e7e7，完成计数却为51/186/473，frame_index2/1/1。这证明计数无法保证当前像素；H249_1/M249_0是被冻结的旧图，不得表述为已抓到当前VD1黑图。

VD1重新开启时GEN38000043、FMT20310c11、FIFO ff00c0、blend100054b0，32位shadow与硬件锁存一致；只证明配置。下一250保持home覆盖不变，以开/关/开/关及每阶段独立通知检验冻结是否跟随VD1，排除切换GUI窗口的混杂。249采集已先停止，再停播放器，参数复原，当前245内核。证据Mac trial-pixels249/，三张PNG均实际查看。


## 固定home、重复VD1开关250（2026-11-21）

保持同一次H264及home窗口10000，167→744解码帧无错误，只切换disable_video=0/1/0/1。首次开启无完成帧；关闭后D250_0得到带当前D250_0通知的菜单；重新开启H250_1完全冻结为同一画面，原始payload SHA256均b2fa37d3370c24885ee1cdec0320e8b03f6636b552170129c5f03451f9e92c66，而完成计数51→195；第二次关闭D250_1更新为新D250_1通知，payload SHA256变5d0de48c7a081b2e92f597d4d8399273465770099430a257d7019e41d22d21e4。三张实际查看，冻结随VD1开/关出现/解除，不是单纯GUI窗口切换影响。仍不能凭VDIN回环唯一归因HDMI物理画面或某个寄存器，但排查主线可集中VD1接入VPP后的像素流停滞。采集先停止，播放器/参数恢复。

下一251隔离当前vd_set_dcu非VD1/VD2复用路径的VPP_INPUT_CTRL(1dab)=440写入：仅将ffffff80098f4a1c对VSYNC_WR_MPEG_REG的调用改NOP，不添加硬件写入，保持245其余全部内容。原厂已提取播放路径未找到该固定/基址偏移写入，但并未证明它是不支持寄存器或黑屏原因；必须通过250同款像素对照验证，阴性则放弃。


## 输入路由隔离251阴性（2026-11-21）

251正常启动，8bb34234-8d1e-46b0-b697-4f61965ad36d；重复250四阶段：H251_0仍无完成帧。D251_0/H251_1原始payload完全相同10d0ab4c04c1329fd27598a60b069c62b4e6aec0d6743d3b5238db2bfcd740d6，完成计数51→134；D251_1变为新通知ad8f48e118f5e979493d96ce36244720d70b2af5c91cd459d8e3b8b8b90eaba7。H251_1和D251_1 PNG实际查看。跳过VPP_INPUT_CTRL=440这单项没有解除冻结，应排除此单项作为修复，不合入正式源码。

本轮稳定证据是同一次解码持续运行，VD1开时回环像素冻结、关时更新。这里只证明回环所见，仍需区分VD1取数/格式/缩放导致VPP输入等待，和回环支路自身受VD1影响；不得越过证据声称已找到唯一寄存器或整个HDMI输出冻结。后续不重复OSD alpha、硬解计数、FIFO241或路由251，而应围绕MIF→formatter→VPP的实际有效数据/握手取点。已恢复245 USB启动配置并请求正常重启；未修改eMMC，音量维持0，实验脚本已先停VDIN再停播放并复原参数。


## 原厂MIF等待行数252/253（2026-11-21）

原厂普通多平面NV21路径由ffffffc00171f764的0x18880041、separate位1及reset位29构成GEN0x38880043，等待行数为17；当前GEN0x38000043对应0。252仅修改模块参数并不能触发DCU重配置，实际GEN始终未变，所以不能计为有效17行阴性实验。253在每阶段通过global_offset写回相同0/0，使用已有API触发property_changed，硬件GEN按0x38000043/0x38880043/0x38000043/0x38880043交替，和RDMA视图一致；四阶段均没有完成帧，解码持续至687帧无错误，说明单独匹配原厂17行不足以解除回环停滞。实验结束先停VDIN再停播放，恢复hold0、disable原值，基线245未改。原始日志Mac trial-hold253/，包含252无效对照和253有效对照。


## 已配置供电与原厂映射254（2026-11-21）

通过驱动/sys/class/vpu/mem的r命令，仅读取已配置的HHI电源寄存器，在H264播放123帧且disable_video0时得到REG0(0x41)=0x000c00c0，REG1(0x42)=0，REG2(0x4d)=ffffffff。从原厂3.14 switch_vpu_mem_pd_vmod的实际跳转表提取模块2/4/5/6，证实VD1/CHROMA/OFIFO/SCALER仍是REG0的4/8/10/12起两位，与当前GXL表一致，均为0即供电开启。VD2/VDIN1此时关电（未采集）属于本次状态；REG2不据此判故障。原厂完整离线反汇编及映射脚本结果存audit/android-video190/。这排除上述已配置SRAM关电，不代表已测所有时钟或MIF发起/返回握手。停止播放，音量0。

下一255通过现有video_global_output=1/0/1/0，只改变global_output混合条件，不调用safe_switch_videolayer/关闭内存流程，并始终确认disable_video0、记录电源状态。用于对比整体关层与仅撤去VPP混合输入，不先假设此接口一定能隔离全部MIF配置；需结合源码与后续硬件读回界定。


## 仅撤去混合输出255（2026-11-21）

245内核，同一次H264196→791帧，无错误；始终disable_video0，home窗口10000，global_output1/0/1/0。H255_0无完成帧；G255_0得到新菜单/通知；H255_1再次冻结，payload与G255_0完全相同5f6dcac2c320f2b4b2d224ff40f482a209606bf4883221be319fdba587f85701，而完成计数51→194；G255_1恢复为新通知，payload982c0d591eba025cbfc22bb9669bdd96f06d5326daad237f1264b570d675d972。三张实际查看。四阶段电源状态完全相同REG0c0/REG1=0/REG2ffffffff；源代码该分支只更改混合使能/逻辑enabled，没有调用safe_switch或内存关断。

说明无需整体关闭VD1，撤去其VPP混合输出便可让回环像素更新，主线进一步集中VPP接入VD1输入后的等待。仍保留MIF实际持续取数未直接读回的边界，不能据此声称MIF像素已正确或HDMI物理端已定位。采集后先停VDIN再停播放，global_output恢复1、其他参数恢复、音量0。Mac trial-pixels255/。

下一256以独立诊断内核在legacy VPP_MISC的既有VSYNC_WR调用前，按video_global_output2仅清VD1 PRE(bit14)、3仅清VD1 POST(bit10)，1不改、0保留原驱动撤去输出行为。使用已验证未被引用的40字节NOP区作tailcall helper，保留x0/LR/SP，用caller-scratch x16读取固定已知global_output字段，不加新寄存器访问或DMA修改。以四阶段原样/断前/断后/全断取图并回读实际blend/GEN；该复用selector仅用于此USB诊断内核，不是正式用户API。


## 混合掩码256未落地，不计阴性

256正常启动，de38af83-326d-4744-89eb-dea1672bc500。mode2/3读回仍为live/shadow100054b0，说明只挂接ffffff80098f7830那条提交路径不足，不能用本轮的无完成帧排除PRE或POST入口。mode0仍能获得当前菜单对照。完整记录Mac trial-pixels256/。

257在256基础上仅补挂同一函数内另一条VPP_MISC提交路径ffffff80098f73ac，仍使用同一个40字节尾调用helper和两个固定掩码。必须看到mode2/3实际bit14/bit10变化再判断效果。清除USB上已否定的Image251释放空间，其原文件在storage/Mac均有副本；保留基线245及当前256用于回退。


## 条件提交触发257/258

257初轮同样未改变实际混合位，不能计阴性。进一步发现仅将global_output改2/3不会改变原驱动的vpp_misc_set，所以其条件`vpp_misc_save != vpp_misc_set`跳过了最后提交，固定掩码helper没有执行机会。已在257同一内核做无VDIN的短验证：先global_output0停留200ms，再设2/3，确保原始值变化；实际mode2 live/shadow100014b0、mode3 live/shadow100050b0，GEN均38000043，读回选择器分别2/3，Canvas继续切换。已验证固定PRE/POST位隔离可以落地，其他MIF配置保持。短验证先停播放后恢复global_output1。

258保留Image257不再换内核，只补齐上述触发并记录snapshot后的global_output，重启重置一次性VDIN采集，再按原样/断PRE/断POST/全断取实际帧。不能用256/257初轮的计数或超时判定这两个入口，只有258有效。


## 有效PRE/POST分界258（2026-11-21）

Image257，2030682c-a6ac-4b0d-b39b-4740ddd5b192；同一次H264175→599帧、无错误，home窗口10000、disable_video0，global_output前后读回分别1/2/3/0。四阶段结果：

* 原样：100054b0，无完成帧。
* 仅断PRE(bit14)：实际live/shadow100014b0，GEN38000043/GEN2=1/GEN3=33/Canvas切换，得到PRE258_0，但实际查看仍显示先前H258_0通知，属于旧图，未证明当前像素更新。
* 仅断POST(bit10)：实际live/shadow100050b0，MIF同上，POST258_0实际查看显示当前POST258_0通知，菜单更新。
* 两者均断：NONE258_0实际查看显示当前NONE258_0通知。

四阶段电源寄存器均REG0c0/REG1=0/REG2ffffffff，GEN在两个独立入口模式保持开启。故后混合接入VD1输出是触发回环停滞的必要条件之一；只断前混合未解除，断后混合可解除。不能据此断言后混合器坏，也可能是其等待MIF/格式/缩放链路提供有效数据，下一主线应放在VD1/PPS输出至POST入口的供数/握手。没有新增物理HDMI观察。Mac trial-pixels258/三张均实际查看，脚本保存trial-blend257/e900-pixels258.py。探针退出后先停VDIN再停播放，global_output恢复1，音量0；当前USB仍为257诊断内核，模式1对原路径不做掩码，245回退文件保留。

另核对amvideocap源码：ext_get_cur_video_frame在video.c1436读取实际layer->vd_mif_reg.vd_if0_canvas0作为cur_index；amvideocap.c随后用其拆分Y/U/V索引，canvas_read并设置GE2D src_para.canvas_index=cur_index。此前正常彩带A点使用的是显示端Canvas索引，而非直接绕过这些描述符读取vf->canvas0_config。它加强了当前显示Canvas可解释性证据，但GE2D正常仍不等于VD1 MIF实际出数或PPS输出正常。


## 原尺寸PPS旁路与后混合对照259（2026-11-21）

Image257，83595bea-28fd-4801-8ca2-bf8e5beb046f，同一次H264199→635帧、无错误。全屏缩放H259_0无完成帧；原尺寸轴0/0/1279/719、bypass_pps=Y，实际SC从78404变68404（bit16 TOP_EN确实清除）、后混合窗口4ff/2cf，PPSOFF259_0仍无完成帧；然后切断POST，取得POSTOFF259_0当前菜单和本轮通知，PNG已查看。PPS关闭时硬件旧相位aaaac0/aaaa80未被重写，不能按这些旧读回声称unity相位，但TOP确已关闭。第三“RESTORE”阶段轴仍1279/719（saved_axis是在播放前取到的旧轴），故不能算恢复全屏的A/B/A对照；不据此作额外结论。四阶段供电不变。

说明单独运行PPS缩放算法不是该回环停滞的必要条件；仍不能完全排除旁路供数或其输出握手。采集先停再停播放，参数复原。Mac trial-pixels259/。

下一260在Image257现有预算/活动legacy帧/总线就绪guard下，只替换三个固定读回参数：日志luma_x改读VPP_IN_H_V_SIZE(1da6)，luma_y改读VPP_OUT_H_V_SIZE(1da5)，matrix改读VPP_OFIFO_SIZE(1d27)。标签只是为复用既有日志槽，不能仍按原标签解释。其他GEN/Canvas/格式/SC及混合日志保留，无新增寄存器写入/地址输入。该轮只读几何，不启动VDIN，取scaled/native/restored/postblend-off四种状态，以运行时寄存器核对源代码尺寸及原厂OFIFO默认值。原厂GXLX2video_init明确对1d27读-改-写低13位fff；先读后决定是否需要单项恢复，禁止直接开启导致重启的全局late-init。


## 实际尺寸与OFIFO读回260（2026-11-21）

260正常启动073077ba-f18c-4690-8c24-a262ae17db73，只读几何，不启动VDIN；scaled/native/scaled_restored/postblend_off四状态。替换后的日志槽实际读到IN_H_V_SIZE050002d0(1280×720)、OUT_H_V_SIZE07800438(1920×1080全局显示)、OFIFO_SIZEfff00fff，低13位fff与原厂初始化相同。缩放SC78404→68404→78404，原尺寸状态软件相位为unity、顶层位16关闭，硬件旧相位保留而不运行；第三轮本次正确恢复轴1919/1079及窗口77f/437。POST切断时live/shadow100050b0。

说明VPP输入/全局输出尺寸与样片/HDMI配置一致，OFIFO默认值已在运行时存在，不要再用全量late-init重放或盲目修FIFO；9次早期丢写本身仍不构成黑屏因果。当前260保留前后混合选择器和所有原取点guard，仅日志luma_x/luma_y/matrix的含义分别为输入尺寸/输出尺寸/OFIFO。Mac trial-size260/含完整视频状态/日志/映射及复现脚本。

下一261使用现有bypass_cm开关，对VPP_MISC bit28开启的色彩管理级做原样/旁路/恢复/断POST对照。仍在260本次未启动过VDIN的会话中，无需再重启；取数/尺寸/POST在前三阶段保持。不能将CM_ENABLE控制位成功切换当作图像恢复，必须实际查看当前通知/彩带。


## 色彩管理旁路261阴性（2026-11-21）

260本次启动中尚未启用VDIN，直接运行261。全屏12005，H264159→550帧、无错误。bypass_cm=N/Y/N，使实际blend100054b0→000054b0→100054b0，GEN/尺寸/供电/后混合使能保持。三段均无完成帧；最后断POST得POSTOFF261_0黑底+当前通知，PNG已查看。因此单独CM旁路未解除停滞，不是把控制位变化当图像恢复。Mac trial-pixels261/。参数恢复CM=N/global_output1/音量0。

## 手动GO_FIELD产生完整像素262（2026-11-21）

260内核7afab585-85f1-402d-a1f6-7c9c54b9b899；驱动已有debug_flag0x100000=DEBUG_FLAG_GOFIELD_MANUL，仅影响VD1/VD2 DCU配置GEN bit7。通过相同global_offset重配置触发。正常段无帧；一次手动触发后KICK262_0得到完整彩带/白标，但仍带NORMAL262_0旧通知，且图像存在横向错位，不能声称连续恢复。随后3秒低频交替flag0/0x100000并重配置，PUMP262_0实际图含当前PUMP262_0通知和不同位置白标，彩带完整，仍有起始错位。该时PRE/POST均开启、live/shadow blend100054b0保持，MIF shadow380000c3，实际GEN bit7自动清除，且出现38020043(bit17 BUSY)；表明手动启动确实让VD1取数并将彩带送到正常后混合/回环。不是仅完成计数或旁路重建截图。三张包含POST断开的对照图均实际查看。

这把主要触发点定位到VD1自动帧启动/GO_FIELD链路；尚不能断言根因是某个同步mux、启动态或寄存器位，也不能把异步低频手动触发作为正式修复。Mac trial-pixels262/。先停VDIN再停播放，flag恢复0/位置原值/global_output1，音量0。

下一263以245为基线（不带257混合掩码及260日志别名），在vpp_blend_update每次VSYNC的原VPP_MISC读回调用处加条件wrapper。global_output bit1且VD1.enabled时，在原帧配置之后，通过既有VSYNC_WR_MPEG_REG_BITS队列提交GEN bit7；保存原读回返回值及ABI。默认mode1不增加硬件写。目的为同步触发、排除用户态起始错位，不是正式源码修复；只用于本次已知非压缩H264/legacy MIF板。first guard/callback占memset既有40-byte NOP区，后续44-byte为245 done-helper RET后原NOP；普通VDIN函数正文不变。263对照normal/sync/sync+原厂hold17/automatic恢复。


## VSYNC位修改提交263未出帧

263正常启动ce91e10a-8cb7-41f0-a3ec-b4ce2a4e6d64，normal/sync/sync+hold17/restore四阶段H264159→817帧无错误，但都无VDIN完成帧。同步触发确实提交：shadow380000c3，live38020043(BUSY位17持续1)；hold17阶段shadow388800c3/live388a0043，恢复后回38000043。不能把这轮记为“探针未执行”，也不能否定低频手动触发262的真实彩带；说明触发时序/命令方式仍未解决。脚本退出已停VDIN再停播放，global_output1/debug0/hold0。

源码rdma_write_reg_bits在当前item表匹配相同地址时会直接修改原条目并返回；rdma_write_reg则追加完整条目。因此264保留同一开关/软件活动guard/ABI，将尾部改为VSYNC_RD取得待提交GEN配置、清读回BUSY位17、置手动start位7，再VSYNC_WR追加完整命令，避免在队列前部合并及回写BUSY；其他功能不变。这是根据262低频完整GEN写的行为继续隔离提交方式，尚未证明某个机制是唯一根因。hold17前短暂关闭诊断触发再重新配置，避免旧GEN覆盖本次新hold配置。未开启全局late-init，未写eMMC。


## 追加式同步触发264仍未出帧

264正常启动2bc7feff-6577-450b-907f-7e258f115be9，H264104→590帧无错误。normal/sync/sync+hold17/restore四阶段均无VDIN完成帧。完整GEN尾追加方式尚不能恢复，不能宣称RDMA位合并就是唯一根因，亦未取得稳定同步触发修复。退出已恢复global_output1、hold0并停止VDIN/播放。

下一265保留同一264内核，但一直mode1（同步helper不写硬件），用完全相同10Hz的global_offset重配置节奏，比对debug_flag0（重配置但不置手动位）→0x100000（重配置并置手动位）→0。此前262将手动位与重配置同时改变，必须用此消融对照区分“GO_FIELD必要”还是其他DCU/格式更新产生恢复；在结果明确前，262的GO_FIELD归因应作为定位线索而非最终根因。每段最多6秒，最多2张，包含当前通知用于判旧图；原始GEN和帧计数一并保存。


## 同频重配置/常置手动位265未复现彩带

264内核f885c08f-d6ad-42f8-8a8a-961e36d873d4，global_output始终1，同步helper不写硬件；H264160→803帧无错误。正常段、10Hz重配置debug0、同频重配置debug0x100000（持续常高）、再回debug0均无完成帧。不能据此抹去262已实际看到的彩带，但常置手动位并不足以稳定重现，尚不能把“手动GO_FIELD已修复”作为结论。263/264/265完整日志和JSON已下载Mac trial-ablation265/。

262有效PUMP采用每50ms交替debug0/0x100000并重配置，与265常高并非相同脉冲协议。下一266在同一264内核按baseline/常高/交替0→1脉冲/常高恢复比较，频率和控制写入均有记录，用本轮通知及白标判定当前像素。仍是GO_FIELD/配置时序定位，不是正式修复；全部试验保持音量0，结束先停VDIN再停播放并恢复模式/参数。


## 交替脉冲266与原内核复跑267均未复现

266在264内核交替0/0x100000和global_offset重配置仍无完成帧。267回到262首次出图时相同Image260，并复用262脚本（仅改输出编号），启动c8939baa-d8cc-4141-8d36-9dccd3dd58c2；正常、单次手动、交替脉冲均无完成帧；仅断POST获得POSTOFF267_0当前通知（实际查看PNG），解码159→560帧、错误0。因此不能将262偶次成功归因为稳定GO_FIELD修复，也不能将263/264失败简单归因为新增二进制探针。262彩带证据真实但尚未复现；自动帧同步仅为假说。267完整JSON/dmesg/PNG保存Mac trial-pixels267/。

268改用已有rdma.enable驱动开关，对显示配置排队/直接提交作normal→direct→direct+manual→restore→POSToff对照，不再添加同步触发二进制。原始模式和debug/位置在finally恢复，先停止VDIN再停播放；本轮目的只隔离配置提交时序，仍以当前像素而非计数判定。


## 显示RDMA旁路268未解除停滞

Image260，d3064a80-da49-42f7-99e2-ffc5c8096b6c，H264154→696帧、错误0。现有/sys/module/rdma/parameters/enable从1,0切换0,0并等500ms、强制global_offset重配置；直接提交normal和manual两段均无完成帧；恢复1,0仍无帧。最后断POST获得当前POSTOFF268_0通知，PNG已实际查看。源码cur_enable在每轮vsync_rdma_config末更新，0选择现有VSYNC_WR直接写入路径，未新增原始地址写接口。该对照说明仅绕过显示配置队列不足以解除停滞，不能据此排除所有硬件帧同步问题。完整脚本/JSON/dmesg/PNG在Mac trial-pixels268/。

结束读取确认rdma.enable=1,0，debug_flag=0，video_global_output=1，Kodi volume=0；已先停VDIN后停播放。当前USB为Image260，无新增正式修复，eMMC未改。下一步应比较原厂GXLX2的VD1读请求/帧同步配置与现有路径，不继续把配置读回或回环超时当作某一级真实黑像素。


## 只读VPP时钟探针269

269以260为基线，仅替换原活动legacy帧、预算限制、总线就绪保护内三个固定读取参数：日志luma_x→VPP_GCLK_CTRL0(1d72)，luma_y→VPP_GCLK_CTRL1(1d73)，matrix→VPP_SC_GCLK_CTRL(1d74)。其他采样及混合选择器不变，无新增写操作/运行时地址选择。前254只核对内存供电，不能替代这些时钟配置读回；未调用vpu/gate的全表读取（会访问未启用VDIN0）。本轮先读取，再判断是否需要使用既有VPP门控模块API做单项对照；不能将门控配置等同于实际时钟波形。


## VPP强制时钟门控对照270阴性

269启动5f798f66-e3c1-43bf-a315-1106c7f3756d，只读scaled/native/restore/POSToff四状态的1d72/1d73/1d74均为0。270同一启动首次开启VDIN，以现有vpu/gate的w 79 1启用VPP模块门控：读回确实变为fffffffc/fff/3fc0ffc；w 79 0后均回0。模块号79通过内核离线vpu_mod_table的RELA加数还原验证为vpp；表保存Mac trial-clock269/module-table.json，未使用全表gate r或运行时原始寄存器接口。

正常、强制开启、恢复三段均无VDIN完成帧；最后仅断POST取得POSTOFF270_0当前通知，PNG已实际查看。H264160→493帧、错误0。说明单独通过该VPP模块门控API强制开启不足以解除停滞，不能据此断言所有时钟/握手波形正确。当前原厂GEN/GEN3/格式差异复核中，hold17与formatter bit29均已有有效阴性，不再重复。270完整脚本/JSON/dmesg/截图在Mac trial-pixels270/。退出恢复VPP门控0并先停VDIN再停播放，随后恢复Image260启动脚本并正常重启，避免留用269的日志别名。
