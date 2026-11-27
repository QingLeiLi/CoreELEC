# Build293L：低成本 legacy SDR 路径实验

用户明确要求最小成本实测。没有全量构建、没有改运行中的内核；从固定Build293 Image生成独立USB启动内核`e900-Image293L`，五个4字节指令槽改变，其余所有字节保持。原Image293/SYSTEM293保留。

## 修改与限制

生成器`scripts/make-build293-legacy-csc-trial.py`要求源sha256 `8c87b17cead380b6cb23d1a334ec8d5372a3c8d1824d6a259666d2200f01fac8`，逐项核对原opcode及前置CPU比较。主机ARM64反汇编确认四个条件跳转改为相同目标的无条件B，一个G12分支改NOP走原legacy落空路径；无调用ABI/栈/函数边界修改。

|Image偏移|目的|
|---|---|
|9ca1a4|调用legacy hdr_support_process|
|9ca2e0|legacy source/policy选择|
|9ca3bc|legacy HDMI metadata callback|
|9ca420|走已编译内联的video_process，避开video_post_process|
|9c8d40|bypass_hdr_process内部也走legacy矩阵/LUT路径|

源码等价选择记录于`candidates/0045-gxlx2-legacy-sdr-csc-route.patch`，**不进入默认构建**。二进制无跨SoC通用保护，只允许此固定盒子临时实验。格式特定HDR/HLG/CUVA helper未全部转换，本轮只判断当前SDR彩条首播/Stop/replay，不宣称完整HDR支持或最终修复。

## 部署与回退

USB FAT余72.4MiB。`/storage/e900-legacy293/previous/`保存旧启动脚本，`rollback.sh`恢复它们后软件重启即回Image293。SYSTEM/initrd/DTB完全复用293；未写eMMC。完整生成材料、反汇编与provenance在本地`../trial-legacy293`，符号来自原Build293当前/proc/kallsyms与匹配Image。

新boot `6df8d570-94f0-4635-afdc-814a9180628d`，BOOT_IMAGE=e900-Image293L；init等待1，disable_flush_flag=0；收到netconsole READY后释放初始化。只首播一次，目录`/storage/e900-legacy293/paired-01`；后续等待用户确认正常，正常才按默认参数reference→transition，不使用Stop HDR guard。若首播黑或采集不全就停，不自动重复。

本轮在写本文时尚未得到首播画面反馈。实际legacy写者/避免HDR2应从新时间线验证，不能仅凭静态分支修改就说已在硬件生效。


## 实测结果：首播、默认重播均正常

用户分别确认首播正常和默认Stop/replay正常。first/reference/transition/outcome为3067/280/14778/168行，无溢出，首播与重播观测齐全，outcome配对/播放器身份核验通过。disable_flush_flag最后实读0，未使用Stop guard，HDR恢复/hold/GEN3/OSD实验均关闭。

完整transition无HDR请求/提交/disabled事件，无0x3800–38ff选定软件写入；Stop实际出现legacy的1a90–1a99、1a9d–1a9f、1d91/1d92/1da5以及1d5f控制写入，不能把成功解释成Stop未执行清理。CTRL参考/转换/正常稳态均d05f，所采HDR输入矩阵保持0，FIFO有0/401effe及启动1effe；正常目视来自用户反馈，不以FIFO自动归类。

此结果支持**所测SDR场景下legacy CSC路由有效**，与默认A黑屏、全局Stop HDR抑制B正常构成三组方向一致的证据。不等于已经定位单一控制位，也未完成反复重播、输出关闭/恢复、其他码流、HDR/HLG、菜单颜色及真正冷启动验收。当前源候选0045仍不进入默认构建；下一步可将五处选择转成受GXLX2限制的正式源码修复候选，补其它格式能力审查，避免宣称全HDR支持。

证据：[摘要与二进制provenance](evidence/build293/legacy-csc-01/summary.json)，相同目录含四段原始时间线与RPC结果。设备保持静音正常重播，未追加Stop/Open/重启。
