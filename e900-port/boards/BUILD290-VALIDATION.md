# Build290 实机记录（2026-11-25）

构建 run45456482461，源码4ce91f4585，内核/SYSTEM均为该次构建。设备从USB启动；保留288回退，未写eMMC。网络初始化日志确认complete，状态2。采集器另应用1e3cd4cbef，修复sysfs额外空行导致52列记录被误拒绝；不需要重编内核。

**无人观察屏幕。本页描述采样和源码证据，不能代替实机画面确认。**

## 已获得的边界

首播Canvas截图和输出恢复后Canvas截图均可见彩条；白色移动标记位置不同，故哈希不相同，不能声称逐字节一致。独立扫描port1首播16点有8种值，恢复后全零。全零的硬件有效性仍未知。

同一次首播中，仅执行global_output 1→0→1，完整记录54行，选择器已恢复，无安全守卫失败：

|记录|状态|固定点raw0/raw1|PPS次数|CSC状态/post/fake|RDMA IRQ/config|
|---|---|---|---|---|---|
|12|关闭前，enabled=1|ac200200/80000003|0|ON/0/0|4392/4397|
|14|global=0，混合更新前enabled=1|ac200200/80000003|1|BYPASS/1/1|4394/4398|
|18|关闭期间|40200200/80000000|3|BYPASS/1/1|4396/4400|
|23|global=1，混合更新后enabled=1|40200200/80000000|5|BYPASS/1/1|4398/4402|
|24|后续VSync，软件CSC已恢复ON|40200200/80000000|5|ON/1/1|4398/4403|
|53|结束|40200200/80000000|5|ON/1/1|4412/4417|

采样最先在关闭期间变成与既有黑电平样本一致的值，恢复后未返回彩条参考。VPP_FIFO_STATUS随之出现0；它是相关状态读数，不能单凭0精确定位某个FIFO或推断复位方法。GEN3由33变3033，但此前正常场景也见过3033，仍不是充分故障标志。

RDMA在整个边界持续推进，因此此次故障不等于视频RDMA完全停止。看门狗累计4次重提请求，计数本身不代表每次重提的硬件效果。

## 白盒核对与反证

1. amvecm处理发生在vpp_blend_update更新enabled之前。恢复时一帧滞后已由记录23/24验证，无法解释持续异常。
2. 关闭期间确实执行fake SDR + G12 HDR处理；恢复后CSC状态ON，但本记录中post计数仍1。源码cap_changed让重复帧进入vpp_matrix_update，并不自动添加CSC_FLAG_FORCE_SIGNAL；后者仍受signal_change_flag/cur_csc_type筛选。
3. 不能立即把第2点判为漏恢复缺陷：首播与关闭时的HDR调用参数相同——VD1请求模块1/策略1，OSD模块3/请求1、有效策略20000001，LUT和matrix均0。相同输入可能合法跳过重复配置。尚未对比全部实际提交寄存器序列。
4. 通过global_offset原值重写0 0，触发正常property_changed→DCU/PPS重配，日志确认dcu_config执行；前后port1仍全零。没有更改坐标，不能用“只补普通DCU/PPS重配”解释或解决本次失败。
5. SR保护改动已随完整ARM构建启动，但未消除重播/输出恢复采样异常，不能宣称修复黑屏。

## 后续检查的边界

应继续对比关闭副作用的实际配置提交，优先检查PPS普通系数/时序与HDR矩阵提交是否相同，并定位数据流在关闭后无法恢复的条件。不要仅因CSC恢复未重跑就强制更换CPU族，也不要重试GEN3掩码。RDMA冲突表的独立软件疑点尚无实机触发证据，本镜像未包含其草稿。

完整边界：[build290-global-output-edge.json](evidence/build290-global-output-edge.json)。摘要及HDR日志：[build290-summary.json](evidence/build290-summary.json)。Canvas：[首播](evidence/build290-first-canvas.png)、[恢复后](evidence/build290-restored-canvas.png)。本地完整记录位于trial-build290，设备侧/storage/e900-build290。
