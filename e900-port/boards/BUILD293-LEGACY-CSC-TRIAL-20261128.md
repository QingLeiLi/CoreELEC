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
