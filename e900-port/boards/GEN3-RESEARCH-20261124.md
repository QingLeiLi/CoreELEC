# VD1 GEN3 网络资料与同版源码调查（2026-11-24）

## 本轮取得的源码

已自行clone CoreELEC/linux-amlogic的amlogic-4.9-20分支，HEAD核对为50c8e8154c5aba3c7cd8438d04dd5fdd51733e41，与构建固定内核一致。位置：工作区coreelec-audit/gen3-research-20261124/linux-amlogic。仓库使用depth1、blob过滤和稀疏检出，已完整检出drivers/amlogic/media和include/linux/amlogic/media；约47MiB。不是完整历史，也没有声称已经取得整个Linux所有文件。无需用户另行clone。

原有本地sources只有3.7MiB选定fixture，不能称为完整媒体源码；新增检出解决了该搜索覆盖缺口。上游树不带e900补丁，分析实际行为须结合项目patches/linux。

## 寄存器用途与证据强度

legacy VD1_IF0_GEN_REG3地址1aa7，为VD1图像内存读接口控制的一部分；不是H264解码器控制寄存器。G12同名寄存器地址3216，不可混用。

| 位 | 已知用途 | 证据与限制 |
|---|---|---|
| 0 | 64bit反转/布局相关控制 | 晶晨U-Boot生成头命名cntl_64bit_rev；CE还按VFRAME_FLAG_VIDEO_LINEAR配置该位，实际布局需结合其他MIF位 |
| 2:1 | burst长度 | CE非legacy路径按burst_len更新；新SoC手册也有该字段 |
| 6:4 | block长度/请求节奏 | 同版DI pre_hold_block_mode_config明确注释并修改；TXLX条件，不可直接施加给GXLX2 |
| 9:8 | 内存位深/打包模式 | CE video、DI、amvecm一致使用；8bit模式为0，其他模式结合帧类型选择 |
| 11:10 | 调试模式 | S922X/A311D2同名IP手册列出，尚无GXLX2专用确认 |
| 13:12 | **未知** | 本轮没找到GXLX2可靠位定义；不能命名为复位、门控、FIFO错误或只读状态 |

[晶晨U-Boot AXG生成寄存器头](https://android.googlesource.com/platform/external/u-boot/+/refs/heads/android-tv-s-beta3/arch/arm/include/asm/arch-axg/regs.h)在同地址仅注释bit0，其余写作reversed，显然不足以覆盖后续各代扩展。[A311D2厂商手册表10-688](https://dl.khadas.com/products/vim4/datasheet/a311d2-datasheet-rev-c-0.2.pdf)列出上述常见字段，但没有解释bit12/13，且地址/IP代际不同。**这些只能帮助理解，不能替代GXLX2硬件手册。**

## 同版源码写入入口

以下均相对新增上游源码树，行号对应固定提交。

| 文件/函数 | 行为 |
|---|---|
| video_sink/video_hw.c: vd1_set_dcu，约993行 | legacy只对GEN3 bit8:9和bit0做RMW；非legacy另改burst位；通过layer选择寄存器表 |
| video_sink/video_reg.c:43/96/149 | legacy/G12/SC2地址表；查表访问不能只搜字面1aa7 |
| deinterlace/deinterlace_hw.c:674 pre_hold_block_mode_config | TXLX条件修改bit4:6 |
| 同文件:2442 post_bit_mode_config | legacy修改bit8:9，G12路径改DI_IF0而非VD1 |
| di_multi/deinterlace_hw.c:462/2646 | 类似的另一套DI实现；目录存在不代表本构建在用 |
| **enhancement/amvecm/bitdepth.c:241 vpp_vd1_if_bits_mode** | 新增发现的共享写者，改bit8:9；CPU精确匹配G12A/G12B才选择3216，否则选择1aa7 |
| common/rdma/rdma.c:291 VSYNC_WR_MPEG_REG_BITS | mode0先Rd硬件，再合并mask，整字Wr；其他模式进入rdma_write_reg_bits |
| common/rdma/rdma_mgr.c:859 rdma_write_reg_bits | 基值可能来自硬件、冲突表、当前队列或已提交写表；合成整字再排队 |
| common/rdma/rdma_mgr.c:642 rdma_read_reg | 返回软件表优先的逻辑值，**不是硬件影子寄存器** |

本轮对媒体与寄存器头完整检出范围搜索VD1_IF0_GEN_REG3、vd_if0_gen_reg3、1aa7，找到上述命名/查表入口；没有找到明确把12:13设成3的命名业务操作。动态地址、寄存器表批量加载、固件/安全世界及硬件副作用不能由静态搜索排除。

## 纠正“另一个写者覆盖”推断

0023插在普通bit8:9配置之后、普通bit0配置之前。现有mode0日志为3033→33→3033，最后一次紧跟清位事件，符合正常bit0 RMW再次读取3033并整字带回的次序。

所以该日志**不能单独证明有另一个模块专门设置12:13**。若清位后硬件读值立刻回到3033，同一函数下一条RMW就足以复写高位；也可能存在并发写或其他路径。现有codec_reg_write包装层caller区分不了，需要在实际RMW层记录caller、模式、handle、start/len、基值来源、基值和合成值，而非只追加通用写入日志。

原日志中的shadow应理解为VSYNC_RD_MPEG_REG的逻辑读值（可能软件缓存）；后续报告用queued/logical与hardware_live区分，避免误称硬件shadow。

## 主线流程与类似案例

已查看主线v6.18 meson_overlay.c、meson_viu.c，以及[meson_crtc.c](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/meson/meson_crtc.c)。其路径是DRM plane检查/生成配置→atomic提交→VSync写硬件，并不经过CE的amvideo+DI+RDMA生命周期。所查这三份文件未见显式GEN3写入；不能说主线已有可直接抄来的GEN3重置修复。

找到[2019年G12A primary plane disabling修复](https://lists.openwall.net/linux-kernel/2019/06/05/606)：关OSD配置寄存器会使blender停滞，修复改为在blender端关闭/重新打开输入。它证明关闭与恢复的顺序/位置确实可能让视频混合卡住；但本机是legacy GXLX2，没有证据可直接套用G12寄存器修复。

按寄存器名、3033、重播/黑屏等检索，本轮未找到能对应本机GEN3 33→3033且给出确认修复的公开案例。没有把常见“有声黑屏”帖子当同根因证据，也没有采用无来源刷机聚合页的寄存器说明。

## 后续可验证工作

1. 在现有默认关闭、限定GXLX2与固定1aa7的诊断基础上，给直接/队列RMW记录业务caller、原值、修改mask、合成值和基值来源，避免新增任意地址接口。
2. 在正常DCU调用内记录GEN3修改前、位深配置后、清位后、bit0配置后，关联provider epoch和帧。硬件读回继续受总线就绪/活动legacy VD1保护；禁止在停止态盲读。
3. 若硬件原值直接回到3033，先追状态/复位/供电时序；若原值33却逻辑基值3033，优先追RDMA软件表；若明确业务caller生成高位，再修该分支。
4. 同时保留回采响应矛盾，不能靠未经场景响应验证的黑图验收任何GEN3修补。

本轮只做网络/源码调查与文档记录，没有向盒子写寄存器、重启或修改内核行为。

后续0024已实现直接/队列/通用codec RMW来源日志与legacy OSD单项开关，见[实现与验证流程](GEN3-OSD-EXPERIMENT.md)。尚未在当前287内核上运行，不声称已实机验证。

2026-11-25更新：0024的RMW来源日志已经随288实机运行；清位生成33后仍有硬件读回3033，而且正常彩条也出现过3033。bit12:13仍无可靠定义。新增[关闭/恢复白盒调用链审计](BLEND-SOURCE-AUDIT-20261125.md)，补出PPS/SR重刷和amvecm状态机，不能将global_output理解成只改两个混合位。
