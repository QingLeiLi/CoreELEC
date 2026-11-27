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
