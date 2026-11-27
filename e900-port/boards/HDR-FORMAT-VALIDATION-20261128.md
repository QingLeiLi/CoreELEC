# 293L HDR10 / HLG 格式验证

测试运行在已通过SDR重播的五分支二进制293L上，不是尚未ARM编译的315320c628源码产物。仅测试HEVC Main10输入；格式识别、解码推进、画面存在、颜色/色调映射、HDR直通必须分开判断。

## 接收端与素材

实读HDMI hdr_cap：PQ=0、HLG=0，静态元数据能力0；HDMI输出BT709/SDR。因此本轮只能判断HDR内容解码及HDR→SDR显示，不能宣称HDR10/HLG直通通过。

素材由本地ffmpeg/zscale真实转换BT709彩条像素到BT2020/PQ或HLG，再编码HEVC Main10/yuv420p10le，带底部闪动白条。不是只改SDR标签。HDR10有mastering-display和CLL，HLG的transfer=18；单次Open长20分钟不靠重启decoder循环。合成信号100nit参考，不是标定过的HDR色彩验收片。

命令、SHA256与本地解码showinfo在[evidence/build293/hdr-formats](evidence/build293/hdr-formats/samples.json)。源短片循环remux，实际长片各约8MiB。采集器支持同一活动层保护下HEVC名amvdec_h265/ammvdec_h265；codec名不是HDR已识别或tone-map正确的证明。

## HDR10 默认组

- boot e5d0b080-a277-42d2-b277-58e4d964a6fe，新软件启动，READY后释放init，flush=0、HDR恢复N、静音，Open一次。
- 用户确认彩条和闪动都有，整体偏灰。归类：**解码/出图存在，色调映射或颜色显示未通过**。
- cur_signal_type=889786377=0x35091009：primaries9/transfer16/matrix9，对应BT2020/PQ；HEVC硬解amvdec_h265帧数推进、错误0；HDMI仍SDR/BT709。
- 软件实读hdr_mode=0、hdr_policy=1、hdr_process_mode=0,0、hlg_process_mode=0,0、cur_hdr_support=0；没有改动这些策略。
- 白盒hdr_support_process中legacy自动匹配是hdr_mode2；值0走bypass，而非对无HDR显示端自动HDR→SDR。这是偏灰的具体候选配置原因，**尚未实测改2后的效果**。
- 首播9441行无溢出，provider/首帧/DCU/PPS/CSC返回有记录，但八项受保护显示读回缺失，结果INCOMPLETE。没有因出图就把采集判完整，没有重试播放。该窗口未记录HDR请求或HDR bank软件写入。不能宣称HDR2转换已执行。
- 视觉反馈后只读保存了策略/HDMI/decoder/Kodi尾日志，完整本地../trial-hdr293/hdr10-01。

## HLG 默认组（进行中）

新boot e247a573-2c9d-40ae-834c-35872d5f3aab，仍相同293L与默认hdr_mode0，不混用HDR10状态；确认READY后Open HLG一次。等待窗口及用户画面反馈。目录/storage/e900-hdr293/hlg-01。

下一步根据两格式默认结果再决定是否单独改变已定义的hdr_mode自动匹配参数。参数组不能混成默认结果，也不能以改开关后画面出现便宣称所有HDR转换正确；黑屏后先停，不能自动再播。


## HLG默认与自动匹配结果

用户确认默认HLG与HDR10同样偏灰，且更明显。cur_signal_type889786889=0x35091209，对应BT2020/HLG；HEVC帧数推进、解码错误0。默认hdr_mode0、hdr/hlg_process_mode0,0；原始8762行无溢出，但首次窗口缺显示调用/受保护读回，不能判完整通过。没有自动重播。

用户随后明确同意观察**当前播放中只改hdr_mode0→2**。新arm独立窗口、记录uptime、写2一次、等2秒、freeze，4499条无溢出；没有Stop/Open。hdr_process_mode与hlg_process_mode变成5,0。用户确认变黑；之后仅下载原包和只读解码状态，未恢复、未重播、未重启。最终hdr_mode2/flush0，解码5951帧且错误0、AVMUTE0。

白盒头文件`PROC_MATCH=5`、`PROC_OFF=4`：不能将5解释为错误状态或关模块。实际HDR_REQUEST/SUBMITTED index137/138是VD1 HLG_SDR=0x10，index139/140是OSD HDR_BYPASS（提交值含RGB_OSD）。HDR2区域矩阵、LUT地址/数据口等写者被记录；这次不同于SDR bypass仅改enable，不能把SDR的“不上传LUT payload”结论推广到HLG_SDR。

与源码`hlg_process`的数值>=G12分支一致：外层五处legacy切换后，未转换的格式helper仍调用G12 hdr_func。这是已确认的调用路径；尚不能断言其硬件适用性，也不能从黑屏断言GXLX2没有HDR/HLG硬件。

## 当前结论

- HEVC Main10解码与PQ/HLG元数据识别已观察到，不等于10bit精度端到端显示或正确色调映射。
- 当前接收端不声明HDR能力，无法用本电视验收HDR直通。
- 默认两格式偏灰，HLG自动匹配后黑屏：**HDR→SDR色彩验收未通过**。
- 下一步若继续，先完整白盒核对/处理格式helper的能力分类与寄存器路径，不能仅更改hdr_mode默认值掩盖问题，不能承诺芯片具备或不具备未证实硬件能力。

所有原始窗口、视觉后软件/HDMI/解码/Kodi状态已压缩归档至[evidence/build293/hdr-formats](evidence/build293/hdr-formats/results.json)。素材生成和输入解码证明同目录，未将8MB测试视频放入git。当前保持HLG黑态；恢复需用户另行明确允许。
