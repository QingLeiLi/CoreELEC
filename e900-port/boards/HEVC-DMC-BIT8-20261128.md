# HEVC停止误关VPU读通道：源码与故障态对照

当前boot仍`b6444de0-97a3-4293-a642-1339c2be896a`、旧293H。用户要求继续查，本轮只有软件/固定寄存器读取，没有追加硬件写入、复位或播放。此前CTRL单次恢复失败结果保留，不重新跑。

## 从RDMA完成链收敛到DDR取表

原包：[axi-status-clock.txt](evidence/293H-menu-black-20261128/axi-status-clock.txt)、[axi-memory-context.txt](evidence/293H-menu-black-20261128/axi-memory-context.txt)。读取前后reset_count17953、VSync439710均相同。

- RDMA_STATUS=9b0a，STATUS2=2020，STATUS3=0。
- 以[S905X厂商文档](https://www.scs.stanford.edu/~zyedidia/docs/amlogic/s905x.pdf)339–340页作为相近GXL参考：STATUS读地址状态=2（请求），current/pipe ID=3，pending=0x0a（通道1、3），完成位0；STATUS2读写FIFO数量0、room32，STATUS3写pending0。不是已证明完成却漏调用callback，也不是已发现FIFO错误。
- VPU_CLK_GATE=ffff，GXL gate表中RDMA bit15=1；仅证明采样时控制位已开。vpu/info为gxl profile、实际664MHz，不能据此证明所有内部时钟工作。
- CH1/CH3表地址34e00000/34e10000位于运行System RAM区间10200000–3fffffff；fb的table_paddr=34e10000相符。范围有效不等于DMA已经读到描述项。

上述状态位是**借用相近GXL文档的解读**，不是GXLX2独立寄存器版图认证。结合现有表准备、触发和中断证据，重点转到DMC准入/DDR读握手；不继续盲改VPP颜色矩阵。

## 新发现：VLD例外没有覆盖HEVC

固定media源码`60561618f2bf154c1438d3c790b625ff01f215c3`的`drivers/frame_provider/decoder/utils/vdec.c`：

1. `vdec_init`将HEVC/AVS2/VP9/AV1分配到HEVC输入target。
2. 最后一个decoder的`vdec_release`调用`vdec_disable_DMC`。这不是仅single decoder才执行的分支；enable入口另外有single/debug条件，不混同。
3. HEVC target的基础mask为bit4；CPU数值>=G12A还加bit8。GXLX2=0x2a，实际会选mask0x110。
4. disable实际执行`DMC_REQ_CTRL & ~mask`；enable执行OR mask。已有media0003只修VLD bit13/21，未覆盖这两处HEVCB选择。

S905X厂商端口表将bit4定义为HEVC，bit8定义为VPU读接口0。于是按当前GXL VPU/DMC布局，这两处会把VPU读准入当HEVCB控制。它与本次最后HLG EOF、GUI内存有菜单而RDMA取表请求不完成的组合一致；没有实时停止边沿日志，暂不写成已证实的唯一根因。

## 实机DMC掩码吻合

通过运行DT `codec_io/io_dmc_base/reg`确认基址c8838000、长度400，再用已有devmem仅只读DMC_REQ_CTRL(offset0)及DMC_CHAN_STS(offset32 words)。没有从安全控制区或Canvas地址猜基址。

读值：REQ_CTRL=**deef**，CHAN_STS=fffff。bit4、bit8、bit13均0。相较保留VPU读通道的dfef，正好多清bit8。它证明故障态该位关闭，不单凭它证明GXLX2的位义/最终像素结果。原包：[dmc-request-mask.txt](evidence/293H-menu-black-20261128/dmc-request-mask.txt)。

## 源码修正与验证边界

默认decoder新增media补丁`0004-gxlx2-hevc-dmc-vpu-port-isolation.patch`：仅在两个HEVCB选择中排除GXLX2，使其只控制bit4；VLD和其它CPU行为不改。不修改全局CPU身份、循环等待、DMC其它通道或RDMA时序。

新增Actions测试`check-hevc-dmc-isolation.py`执行真实enable/disable函数：CPU0..127、两个合法target、开关、5种原始掩码、dev有无和TM2B分支；GXLX2 HEVC只改变bit4并保持bit8，其余CPU/target的结果及read/write/stop/pipeline-reset次数与基准相同。gnu89/gnu99通过。完整补丁应用/安装器、原VLD bus检查、增量缓存、media安装检查也通过；本轮不是重跑全部主机套件。

此补丁属于media_modules-aml，已有缓存策略只失效media包，保留兼容Linux/工具链；如果同一次还包含待构建Linux0045/0046，Linux也需按已有规则重建。ARM模块/image和硬件结束/Stop/replay验收仍待完成。新源码不会自动恢复旧293H已经清掉的bit8。

## 下一步单变量恢复，尚未授权执行

目标：验证恢复DMC bit8是否解除本故障态的RDMA读请求阻塞；不是触发新的故障，不冒充具有正常参考的独立A/B。

- 先确认同boot/293H，无活动player，运行DT基址不变；新读REQ仍deef、bit8仍0，保存IRQ/VSync/STATUS/REQ。
- 只将REQ设置为`old | 0x100`，当前对应deef→dfef。保留HEVC bit4、VLD bit13和其它所有位，不复位、不播放、不同时唤醒屏保。
- 验证REQ读回及其它位保持，短窗看共享/OSD/普通IRQ、STATUS/FIFO和watchdog是否恢复。IRQ恢复后才请用户确认图像；屏保另作独立操作。
- 未恢复则停止并还原原REQ，保留证据，不叠加reset/时钟位；恢复则保留现场，不自动再次关闭该位或重播。
- 恢复成功只支持准入位与本整屏黑的因果联系；源码修正还需新构建、正常首播、HEVC结束/Stop/replay及菜单回归，不能据此替代之前SDR重播黑的独立结论。

需用户明确允许这一次DMC写入后才执行。目前CTRL已回原值0、REQ仍只读观测的deef，未操作恢复。

## 用户允许后的单bit恢复：中断及菜单恢复

原包：[dmc-bit8-trial.json](evidence/293H-menu-black-20261128/dmc-bit8-trial.json)、[稳定性读回](evidence/293H-menu-black-20261128/dmc-bit8-stable.txt)、[结果摘要](evidence/293H-menu-black-20261128/dmc-bit8-result.json)。同boot、旧293H，Player.GetActivePlayers=[]，运行DT映射再次核对，REQ仍deef。

只写REQ=`old|0x100`，读回dfef，XOR差值严格100，其它位保持。没有重启、播放、唤醒屏保、CTRL或复位写入。驱动本来运行的watchdog仍存在，恢复初期又自然复位一次；这是恢复过程的背景，不描述为完全无复位的独立环境。

- 短窗OSD IRQ80643→80675，共享IRQ+63；普通完成也恢复增长。首个50ms采样仍未恢复，后续自然watchdog复位后完成链开始推进，不写成置位立即同周期恢复。
- 最后原包OSD IRQ80780、普通IRQ80762，done=1；reset_count停在19927。后续只读OSD82895、普通82877仍推进，REQ保持dfef，reset_count仍19927，日志未再出现新复位。
- 完成恢复后的STATUS=1b00，对比之前稳定9b0a，读地址状态从Req回Idle、pending清零；仍是相近GXL文档解释，不能替代像素证据。
- 用户明确回复“恢复了”，提供菜单恢复的物理端验收。没有再重复关闭bit8制造故障。

由此确认：**本次整屏黑与VPU/DMC bit8关闭具有直接恢复因果证据**，共享RDMA取表停滞的现场已恢复。源码HEVCB数值判断会清同一位，修正方向得到支持；由于此前未录到EOF写入边沿，仍区分“现场准入位因果已证”与“原始关闭瞬间的写者未录制”。这也不替代旧SDR/CSC黑屏的独立结论。

当前旧293H仍含该HEVC停止路径，下次HEVC/相关target释放可能再次清bit8；本轮不继续播放。新增media0004只防止错误清位，不会主动修复已经清位的旧运行内核。下一步构建最新decoder/image，部署后先核对首播前REQ bit8，再验HEVC正常播放、自然结束、Stop/replay及菜单，多轮通过才完成永久修复验收。
