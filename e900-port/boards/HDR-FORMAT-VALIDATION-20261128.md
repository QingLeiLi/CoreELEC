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
