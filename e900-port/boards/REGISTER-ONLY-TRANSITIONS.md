# 无像素选择器的连续寄存器对照（0036）

## 这次补的缺口

已有0029/0031持续记录能采global_output关闭期间，但同时编程像素选择器。普通stage快照又在enabled=0时跳过，导致“不开像素探针”的目视轮只有黑屏后快照。0036把持续记录新增为mode2：复用相同VSync钩子和安全守卫，完全不读取/写入像素选择器、坐标和颜色寄存器；mode1旧实验保留。

本补丁只增加观测，不修改显示策略，不新增PPS/CSC隔离开关。默认不采集。**主机检查不代表ARM构建或实机验证，当前290内核还不支持mode2。**

## 同步记录的内容

两个钩子仍位于vpp_blend_update的现有VPP_MISC读取之后、计算混合设置之前（phase0），以及正常提交之后（phase1）。它们不是整个VSync处理的最前/最后位置；PPS/CSC业务处理可先于phase0。每条带boot外部标识、代次、jiffies、tick和phase；一条内多次硬件读取也不是总线原子快照。

基础52列兼容原导出：MIF GEN/GEN3/格式器、FIFO配置与VPP FIFO读数、VPP_MISC live/requested/shadow、背景/裁剪/路由、既有门控、软件开关、RDMA进度、PPS/CSC业务计数。mode2的flags只有0（未读硬件）或1（通过守卫后读取）；像素相关ctrl/pos/raw字段均0，含义是未采集，不能解释为黑色。

新增独立扩展页，按同一index/generation/stamp/tick/phase/flags关联16个固定字段：

|字段|固定地址|用途|
|---|---|---|
|canvas / gen2|1a51 / 1a6d|MIF Canvas索引及GEN2|
|luma_x / luma_y|1a53 / 1a54|亮度窗口|
|chroma_x / chroma_y|1a55 / 1a56|色度窗口|
|fmt_width / fmt_height|1a69 / 1a6a|格式器尺寸|
|sc_misc|1d19|PPS控制|
|line_in / pic_in|1d01 / 1d02|PPS输入尺寸|
|h_phase / v_phase|1d13 / 1d08|水平/垂直相位步长|
|h_ctrl / v_ctrl|1d18 / 1d0d|水平/垂直相位控制|
|out_size|1da5|已有共用输出尺寸寄存器|

只针对已选择的GXLX2 legacy VD1银行、有效驱动所有帧、无真实disable/OFF_REQ、总线就绪、VD1内存电源ON和既有尺寸限制。global_output临时关闭是窄例外；真实Stop、帧释放、压缩/MVC、借用VD2、掉电/总线失效则终止或保留软件失败行，不继续读取数据寄存器。内存电源检查复用原有固定HHI控制器查询，不对掉电VD1盲读。

mode2不占用硬件像素选择器、不执行恢复写；仍持有软件诊断互斥租约，避免同时启动另一像素扫描。结束/取消释放租约；安全条件失效时无需等待硬件恢复来撤销像素设置，因为没有做该设置。

## 设备用法

随构建debug-tools导出，无自动播放/重启/停止。例中目录可换成实际部署目录。

只观察，不切换输出：

```sh
python3 /storage/debug-tools/e900-register-transition.py \
  --with-submissions --out /storage/register-observe.json
```

未观察到关闭边界时，只能得到collected_without_transition，不是故障定位结果。记录最多256个VSync/512行；不要先启动后等待用户很久。

受控复现：准备好长片、脚本和回退，收到用户确认当前画面正常的明确回复后，立即执行：

```sh
python3 /storage/debug-tools/e900-register-transition.py \
  --with-submissions --exercise-global-output --baseline-confirmed \
  --out /storage/register-transition.json
```

--baseline-confirmed只是操作者声明，不是工具验证画面、也不是授权来源。命令不启动片段；检查已知H264活动及真实disable=0，等待初始寄存器记录后，global_output=0保持1秒，再恢复1，记录后16个VSync。它不改变hold、GEN3或其他显示策略。实验结束后仍需用户反馈画面，反馈应另记入同一boot/会话，不能由寄存器自动推断。

建议先默认hold=0复现；若按已记录计划做hold=3对照，应由外层显式设置并在finally恢复，原始数据会记录关闭期间actual VPP_MISC，不能只信参数已写。

## 导出与差分

- gxlx2_edge_scan写2启动mode2，写0取消；状态增加mode=2。写1仍为旧像素实验。
- gxlx2_edge_data保留基础分页，gxlx2_edge_regs导出扩展页；扩展只允许冻结后读取。两者共用gxlx2_edge_page，每页8行。getters只读内存。
- 工具检查冻结前后完整状态、行索引、代次、元数据逐行对齐及sysfs追加空行；不会将mode1数据误当mode2。
- 输出含同次运行的关闭前/中/恢复后phase0窗口、各字段最后四个样本的值集合、恢复后仍不同的字段。差异包括动态状态和计数，不排序为“根因”；GEN bit17的源码名称BUSY，不当配置漏位写回。
- --with-submissions同时启用0035，并在结束冻结与导出。0036扩展了MIF/GEN2/GEN3和路由软件表范围。两个记录器共享boot与内核jiffies，保留各自代次；不是硬件逐字完成证明。
- 提交表溢出/空表/导出错代时submission_evidence_complete=false，CLI退出2；寄存器或目视结果仍可保存，但不称完整提交对照。外来代次不会被自动取消。
- 失败时恢复工具自己改变的global_output，取消自己创建的诊断代次，保留能安全导出的部分记录。像素寄存器从始至终未访问。

## 测试与未覆盖

主机执行实际mode1/mode2内核钩子，验证正常→global关闭→恢复、14类保护条件、真实Stop、取消、512行上限、扩展页及旧模式兼容。mode2测试统计像素选择器/颜色寄存器读取与全部寄存器写入均为0；其他固定寄存器只在守卫通过时读。真实rdma_config对照仍核对原MMIO/返回值不变。Python测试覆盖同代关联、坏页、超时、用户基准声明、恢复失败重试、外来代次保护和联合提交导出。

这仍是配置/状态观测，不是逐级像素截图。中间像素新鲜度尚未校准，不据此宣布任何一级像素正常；画面主判据仍是用户目视，或经当前版本正控、具有完成/帧号证据的图像回采。新增模式须完成ARM构建和实机对照，且保留不开记录器的目视基线，以检查读取开销影响。


## 同一会话的输出图像对照

当前寄存器工具增加 --with-loopback，使用已经启动的legacy ENCP VDIN会话，不自动启动/停止服务，不重播片段，不更改捕获格式。初始化和当前版本路由/字节序校准属于单独步骤；同一会话一直保持到本轮结束。

先做不切输出的观测正控：服务准备好、长片正常播放后运行：

```sh
python3 /storage/debug-tools/e900-register-transition.py \
  --with-submissions --with-loopback --out /storage/observe-control.json
```

默认只观察，无global_output写入。工具取前后各两帧，保存原始e9cap、解码PNG和头/完成/时间/GUI元数据。前两帧必须通过已知彩条顺序及移动标记导致图像变化的正控；没有正控不继续后续输出切换。格式固定为历史已校准的BT.601 limited YUV444/reverse64，格式不符拒绝，不从任意颜色猜格式。应检查此版本正控图像与实际画面的一致性；不把ENCP回环当电视端HDMI截图。

正控确认后，同一会话可自动获取新正常参考再触发：

```sh
python3 /storage/debug-tools/e900-register-transition.py \
  --with-submissions --with-loopback --loopback-calibrated \
  --exercise-global-output --out /storage/transition-images.json
```

此模式由本轮新鲜、会变化的彩条图像提供基准，不要求每轮用户代报。--loopback-calibrated只是操作者对当前会话校准的声明，每轮仍重新验证真实前置图像；声明不能代替数据。

顺序固定：前两帧正控 → 启动寄存器/提交表记录 → 一次关闭/恢复 → 冻结/导出寄存器与提交表 → 后两帧。后两帧允许新鲜黑图，不能因黑而拒收。新鲜性检查不仅看内容，还检查脚本的新IRQ以及包的完成计数/帧时间递增；不一致或没有新帧则保存失败原因，不能拿旧帧当恢复后结果。

联合回采明确传E900_CAPTURE_NO_GATE=1：仍要求新IRQ，但不执行原脚本的共享时钟开启。原脚本的默认兼容路径保留；联合对照不使用其时钟恢复功能。无新帧时不自动开钟/重启服务/修改显示后再拍。图像缺失时image_evidence_complete=false、退出2，已取得的寄存器证据保留；不能将缺图解释成黑图。

VDIN初始化及持续会话自身也可能影响共享资源或时序。正控必须有不开回采的目视基线；若打开回采后默认故障不再复现，记录观察效应，不宣称修复。前后回采与寄存器窗属于同一boot/会话的时序关联，并非同一VSync的原子像素快照。像素选择器从始至终不参与。


### 首播初始化表的范围

联合脉冲记录从正常图像参考之后开始，不能回填此前已经写过的初始化或首播系数。如果需要逐项对比首次PPS系数，使用现有e900-submit-trace.py在首次播放前start，正常配置完成后stop保存initial-submit.json；随后同一boot再作联合脉冲记录。必须按各自代次和jiffies关联，不把恢复阶段没有再写某项直接当漏恢复。此步骤使用已有接口，不需新增内核补丁。

当前主机检查28项通过；ARM构建、当前版本回环正控与真实故障采集仍待执行。构建需要保留vdin_capture=true（工作流默认false）；source_trace不因本功能而需要开启。

### 缩短关闭窗口以保留恢复期提交

Build291默认1秒关闭每VSync重刷约87—89字PPS表，4096行缓冲在恢复前溢出。
采集器新增`--off-seconds 0.2`（默认仍为1，合法范围`0 < x <= 2`）；结果记录`requested_off_seconds`。
这是改变复现刺激长度，不改变内核策略，不能假定与1秒刺激等效。

本次约定：软件重启（非冷启动），原Build291及20分钟同源H264、静音、hold=0、GEN3实验=N，
每boot只启动一次VDIN会话；先用新鲜双帧彩条作正常参考，再执行0.2秒global_output关闭恢复。
只有guard=0、前/中/后窗口完整、提交无溢出、前后回采新鲜时才作完整对照。
若短脉冲不触发黑屏，不宣布修复；若参考无效则不切换输出，若仍溢出则停止并保留缺口。
不在黑态追加试验、不重启VDIN恢复时钟，完整表/IRQ关联仍不是逐字硬件执行证明。

```sh
python3 e900-register-transition.py --off-seconds 0.2 \
  --with-submissions --with-loopback --loopback-calibrated \
  --exercise-global-output --out /storage/e900-build291-short/transition.json
```
