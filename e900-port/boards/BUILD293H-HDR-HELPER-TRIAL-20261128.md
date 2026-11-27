# 293H：HDR10/HLG内部G12分支最小实验

用户在确认HLG自动转换命中G12后要求继续。由固定原Build293 Image生成293H：保留293L五个选择，只多改两个4字节指令槽，其余每字节相同。

- HDR10 `hdr_process.isra.0` Image offset9c9ad4：原b.gt→NOP，继续原legacy路径。
- HLG `hlg_process.constprop.0` offset9c958c：原b.gt→NOP，继续原legacy路径。

原CPU比较指令、BL目标、函数地址和边界已用Build293符号表/ARM64反汇编核对。未伪造全局CPU ID、不改运行内核、不改LUT内容。源码对应`candidates/0046-gxlx2-legacy-hdr10-hlg-helpers.patch`，未加入默认构建。生成器固定源hash/opcode，重复调用结果相同、不会累加修改；错误源在输出前拒绝。此为特定盒子临时二进制，无跨SoC保护。

## 预定实验

先部署独立Image293H，原Image293/293L保留；`/storage/e900-hdr293/kernel/previous`和rollback.sh回退当前293L。SYSTEM/initrd/DTB复用293。USB only，不写eMMC。

HLG先从新软件启动（非断电冷启动）开始：init等待、网络READY后释放；播放前hdr_mode设2、flush0、其它隔离关闭、音量0，Open已有实际HLG Main10片一次。保留完整时间线、参数、HDR请求/实际写者和视觉结果。首播是否能出图、颜色是否改善、是否仍执行G12 HDR请求分别判断；缺受保护读回仍标partial，不伪造完整。

用户反馈后先只读outcome；黑屏不追加参数/重播，正常也不自动切换HDR10，下一步先等用户允许观察。后续HDR10需独立初态，不能把HLG转换后状态当作独立首播。

本次仍有未修改的其它格式helper、histogram、HDR更新分支；HDR10/HLG入口切换不证明全部写者已legacy或转换正确。失败时按实际写者定位，不从结果直接宣布硅片缺HDR能力。

## 当前执行

已上传独立28MiB内核与脚本，部署后将检查BOOT_IMAGE、new boot_id、余量、init和开关。首播与物理结果待记录。本地原包`../trial-hdr293/legacy-hdr-kernel`。

新boot `d6929b25-28a5-4768-91b1-0edcdac3dcf5`，BOOT_IMAGE=e900-Image293H，init1、hdr_mode0、flush0起步。旧接收进程已退出，重新启动UDP6667接收至本地trial-hdr293/293H-netconsole.log并确认唯一READY后释放初始化。播放前仅设置hdr_mode2，Open HLG一次，运行目录/storage/e900-hdr293/293H-hlg-auto2-01。实读cur_signal_type=0x35091209、hlg_process_mode=5、HEVC帧数推进/错误0。首播原包导出及物理画面反馈尚待完成；此处不因参数或解码正常判转换通过。FAT余44.7MiB，293与293L保留，未写eMMC。

首播采集结束：65536条后overflow=1，缺受保护显示读回，结果INCOMPLETE；解码1243帧、错误0、disable0。不能用溢出窗口证明全部写者缺失或全链路通过。没有重试、没有重播，等待本次HLG画面/颜色反馈。后续分析需优先留存已记录前缀并解决高频legacy写入的观测量问题，不自动补播。


## 视觉与原始前缀结果

用户确认HLG彩条仍偏灰，主观比上次有所改善。**归类为能出图，颜色仍未通过**，不能把轻微改善当作正确HDR→SDR。黑屏的293L mode2组与可见293H组为不同boot，保持此限制。

只读归档实读hdr_mode2、hdr/hlg_process_mode5,0、csc_en7、HLG信号、flush0、解码推进无错误、HDMI SDR。65536条溢出前缀没有HDR请求/提交，也没有0x3800–38ff软件word；出现legacy矩阵/LUT写入，支持两处helper路径已改变，不能扩大为未记录后续全程无写者。

前三个高频地址1add=18673次、1ade=18673次、1adb=15100次，合计52446条，占缓冲主体。后续采集需先解决高频LUT写入的有界记录方式或更短的固定窗口，而不是加大后仍等待缺失MIF读回。溢出不能用来排除剩余写者，也不能从重复word直接判软件每帧重刷所有LUT（需区分单次大量payload与多事务）。

下一步离线核对legacy EOTF/OETF enable、矩阵路由、调用重复来源，保留原LUT内容作为参考；不直接用range/saturation调整替代适配。HDR10在293H尚未实测，不能继承HLG结果。

原始前缀、参数、decoder/HDMI状态和镜像provenance见[evidence/build293/hdr-formats/293H-hlg-auto2-01/summary.json](evidence/build293/hdr-formats/293H-hlg-auto2-01/summary.json)。视觉反馈后只有只读操作，未重播/重启/改参数。
