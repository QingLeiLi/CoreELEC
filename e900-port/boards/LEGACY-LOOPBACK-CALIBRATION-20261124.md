# GXLX2 旧式输出回环校准（2026-11-24）

## 确认的路由依据

本机保留原厂Android3.14内核的离线反汇编：`coreelec-audit/android-video190/viuin_open-stage205.txt`。`viuin_open`读取0x271a当前编码器，ENCP使用选择值2；其特殊端口值0xa000走0x1a07 bit28和选择值4。函数对CPU0x2a有明确旧系列处理，不出现G12新增的VPP_WRBAK_CTRL(0x1df9)取点选择。旧内核端口数字不能直接套当前枚举名称。

固定CE4.9基线的独立WB0_VD1/VPP/POST等选择位于G12分支；本机0012对GXLX2排除该分支。这里只验证已经存在的legacy ENCP输出回环，没有开放未知WB银行，没有新增任意寄存器访问。原厂函数没使用G12 WB不等于证明硬件绝对没有该功能。

## 首播校准281：实际像素成功

内核仍是既有Image280，SYS279；boot-id `a18985b6-9692-4ea6-b54c-b3ff0a4e054c`，默认RDMA1,0，完成受控初始化后首次播放`Test-H264-720p-60s.mp4`。未让用户观察电视；校准判据直接来自实际回采像素。

首播约18秒先通过标准amvideocap接口取Canvas，再启动一次既有VDIN1 legacy viuin/ENCP输出回环，获得两份受完成、所有权、DMA同步和新IRQ检查的E9VDIN1包：

| 文件 | 完成计数 | 帧timestamp | sample_jiffies | 白块x范围 |
|---|---:|---:|---:|---:|
| FIRST281_1795498570_A.e9cap |13|4294919329|4294919341|328..343|
| FIRST281_1795498573_B.e9cap |116|4294919958|4294919978|476..491|

两份均为640×360、8bit、format_convert2、active/stride1920、flags3。解包后完整白/黄/青/绿/品红/红/蓝/黑彩条，与样片一致；移动白块位于y151..208。完成计数、时间及白块位置均变化，因此不是仅凭计数，也不是旧菜单截图。

本次验证了**输出回环能取得当前运动视频像素**，不等于已有VD1/PPS内部独立取点，更不代表物理HDMI接收端必然正常。它至少建立了一个可在正常首播重复校准的下游像素观察点。

工作区完整包、JSON、原始dmesg和预览在`trial-calibration281/`；首播Canvas快照路径由`e900-calibration281/result.json`记录。

## 字节布局与颜色解码

原始三字节输出不能直接按RGB显示。按当前采集格式，对每个完整64-bit字反转字节，再按BT.601 limited YUV444解码，恢复标准彩条和白块。源码`vdin_set_wr_mif`在非PARAM_STATE_WR_MEM_ORDER_STD分支明确使用big-endian与word-swap设置。具体预览变换由本次已知图像实测校准，不能泛化给其他采集格式。

工具新增显式选项，不自动猜测：

```sh
python3 inspect-vdin-snapshot.py FIRST281_1795498570_A.e9cap \
  --out decoded-first --yuv444-bt601 --reverse64
```

保留原始包与原始payload。预览要求format_convert2，并拒绝活动行不含完整64-bit字的情况。新主机测试使用已知红/白/黑像素跨64-bit字及三字节像素边界，核验解包、颜色值和PNG原始行/CRC。

## 对照282：采集器启动被保护拒绝，不是链路结论

早期脚本在完成首播校准后停止VDIN，再试图在同一boot重启采集服务。现有0014明确只允许一次start/boot；因e900_capture_pinned返回EBUSY。没有取得重播回环包。该失败不能解释为重播视频像素丢失。

改为`e900-calibrate-loopback.py`：一个采集会话跨首次采样、Stop/replay及再次采样，最后统一停止。保持原完成/ownership/每启动一次保护；不绕过保护或释放正在使用的DMA。两阶段都保存Canvas和软件快照、两份回环包、解码状态、完整日志与逐步骤checkpoint。没有现场观察时标签为first_unobserved/repeat_unobserved。

## 伴随发现：GEN3的原厂全写与CE局部写

原厂`vsync_isr_in.isra.21`离线反汇编：地址ffffffc00171ee40先置0x33，ee44合入bit_mode<<8，ee4c/ee50向1aa7执行VSYNC_WR_MPEG_REG全写。当前CE legacy vd1_set_dcu仅改GEN3的bit8..9和bit0，未明确恢复其余位。既有成对正常样本GEN3=33，重播=3033。它是具备原厂对照的具体配置差异，仍未证明其位语义或导致黑屏。先完成像素对照，再决定是否进行单项原厂配置恢复试验；不能把该差异直接当作根因。

## 对照283：完成帧后的全盘sync造成工具假超时

boot8c396e72-8cc5-41ca-8b4a-c701b17e50f3，单会话首张回环包成功。第二张采集命令超过客户端8秒超时，但事后检查最终`.e9cap`文件已经存在且大小完整691280字节。辅助脚本先mv发布完成文件，再执行全盘sync，所以该超时发生在发布之后，不能当作取图失败。此次自动清理已结束会话，未执行重播。完整失败结果保存在`trial-calibration281/pair283/`。

连续采样模式改为显式`E900_CAPTURE_SKIP_SYNC=1`，保留原完成/ownership/新IRQ/文件发布检查，再逐包读回、验证头和长度、计算hash并复制。单次采样默认仍执行原sync。主机测试覆盖跳过sync和默认保留sync；不更改驱动完成规则。

## 成对回环284：首播彩条，停止重播后为实际黑图

bootb43a9963-c630-4556-9248-890d4dcc7aa5，同一VDIN会话跨Stop/replay。四份完整包均通过文件头/长度检查并实际解码查看。首播两帧完整彩条，完成计数12、78，payload hash不同；重播两帧为黑图，完成计数1063、1334，payload hash均516c1d70d40e...。故已经在输出回环观察到重播异常，不依赖电视或仅凭中断计数。物理HDMI无人观察，不能说已经在本轮实测排除了HDMI所有附加故障。

该轮软件快照对比的配置差异为GEN3:33→3033（live与shadow一致）及Canvas轮换值；其余既有字段取值集合相同。原始成对数据和comparison.json在`trial-calibration281/pair284/`。

这轮Canvas采集器错误地把完成枚举的十进制300当成0x300，虽然读满172800字节却错误拒绝且未保存像素，因此不能用这轮元数据声称Canvas实际图像正确。错误已按固定公共头amvideocap.h修正，并新增实际ioctl调用消费者的测试：完成300接受、进行中200拒绝。再次采集同轮两端像素以补齐证据。

## 成对两端285：Canvas有效，输出回环重播全黑

修正Canvas完成枚举后，bootfebca84a-d622-439b-a92d-6070fb2be5c6，沿用同一Image280及默认设置。首播与重播两阶段Canvas均成功保存实际彩条与白块图；同一VDIN会话首播两帧为正确彩条（完成计数12、78），重播两帧解码RGB的最小值、最大值、均值均为0（完成计数1079、1323）。两份重播黑图payload hash与284相同516c1d70d40e...。因此重复取得Canvas有有效图像、旧式输出回环全黑的两端证据。不是同一VSYNC原子截取，但同一启动/片段/固定播放阶段、持续活动解码、采集会话无切换。

原始两端图片、e9cap、元数据及日志均在`trial-calibration281/pair285/`。该结果把异常区间限制在Canvas经VD1/VPP到legacy ENCP输出回环之间，不能再把问题仅归因于物理HDMI线或电视；尚不能声称已区分MIF、缩放和混合具体一级。

### 285图像证据

首播输出回环：

![首播回环彩条](evidence/loopback285-first.png)

重播Canvas：

![重播Canvas仍有彩条和白块](evidence/loopback285-repeat-canvas.png)

重播输出回环：

![重播回环全黑](evidence/loopback285-repeat.png)

[完整包元数据与payload hash](evidence/loopback285-metadata.json)。

## GEN3二进制诊断286：未达到目标状态，不能作为因果结论

仅将Image280的ffffff80098f4550指令从movw3,#2改为#6，尝试拓宽VD1 GEN3位深字段的清除掩码；镜像其他字节不变、其他启动文件沿用279。独立Image286和三阶段脚本的完整原始记录在`trial-gen3-286/`。

默认首播回环有彩条；默认重播回环黑；附加RDMA0,0重播阶段回环取得Kodi Home而非恢复的全屏彩条。关键验收项未通过：两次重播探针live/shadow GEN3仍3033，没有达到预期33。故不能判定清高位无效，也不能称为修复；可能未命中实际路径或被后续覆盖，需要源码日志区分。试验后RDMA恢复1,0，原Image280引导脚本恢复，并重新启动回到Image280；未写eMMC。

0023改为源码真实legacy VD1调用点内的默认关闭实验，明确记录软件提交计数和调用事件，0022固定写入口日志协助查后续覆盖。完整ARM构建与该源级实验实测仍待进行，不继续猜改其他指令位点。
