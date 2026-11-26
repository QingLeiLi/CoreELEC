# Claude 黑屏补丁审查（2026-11-27）

审查HEAD：b20918484f。范围：当前decoder profile默认安装的0037/0038及修复方案说明；未部署、未操作设备。本次为源码审查，不把patch dry-run或编译当实机验证。

## 结论

不建议把这两个补丁作为已确认修复部署。0037的触发条件与文档所举正常/异常值相反；0038没有实现硬件重启，而且不覆盖普通global_output恢复路径。建议先从默认profile移出，修正为默认关闭、可计数的单项实验，再验证。审查本身未修改这些补丁或profile。

## P1：0037以正常态触发，不能检测文档中的异常态

`patches/linux/0037-gxlx2-force-hdr2-reconfig-on-global-output-recovery.patch:9`检查`READ_VPP_REG(VD1_HDR2_CTRL) & 0x1000`。文档正常值0x0000d05f与0x1000相与为0x1000，异常值0x0001c040相与却为0。故按它自身证据，条件在正常态成立，在目标异常态不成立。不能简单翻转判断：固定源码`set_hdr2_v0.c:2015–2018`把bit12称为cgain mode，不能无依据命名为整块HDR bypass。

新增的`cur_csc_type != 0xffff`只说明软件CSC类型曾设置过，不是global_output的0→1边沿检测，也不是每次Stop重新置位的会话标记。正常首播中软件状态更新后仍可触发，连续调用亦可能反复强制重配。补丁没有GXLX2、VD1_PATH、活动帧或输出恢复窗口保护，VD2也读VD1寄存器；这会改变其他SoC/图层和正常播放路径，且部分旧SoC未证明有此HDR2寄存器。

## P1：0038没有重启VPP，也未覆盖普通global恢复

`patches/linux/0038-gxlx2-restart-vpp-on-global-output-recovery.patch:17`仅把`new_vframe_count`从0改为1并打印“VPP processing restarted”。固定源码该字段只在disable时清零，在`layer_swap_frame()`换帧时递增并判断是否第一帧；它不是硬件GO/复位接口。补丁未新增硬件重启、重新初始化或握手操作，不能凭这条日志宣称硬件已重启。

该改动位于`VIDEO_ENABLE_STATE_ON_PENDING`，普通global_output sysfs store只改global_output整数（video.c:10178），混合更新约5027行按global_output修改enabled/混合位；它不因global恢复而自动设置ON_PENDING。因此普通0→1脉冲通常不会经过新增分支；活跃播放时计数也早已非0。真正Stop/replay路径若命中，则需验证计数改写是否影响第一帧识别。改动同样未限定GXLX2。

所谓Stop清理补丁实际只添加`pr_debug`，原有清零保持不变，不构成新增状态清理。

## P2：方案把状态观测升级成了已确认根因

`BLACK-SCREEN-FIX-PLAN.md`称0x1d25为“VPP处理单元停止”的证据。固定头文件明确它是`VPP_POSTBLEND_CURRENT_XY`，0x1d28才是`VPP_FIFO_STATUS`；状态坐标/瞬时FIFO归零不足以证明缺少某个重启触发。手动恢复单个HDR2_CTRL失败也不能推出这个机制（整套HDR事务还包含矩阵/LUT和时序）。

方案还称global_output=0触发disable_vd1_blend；源码调用该函数受`video1_off_req`控制，不能把真实关层请求与global隐藏混为一条路径。

## 建议的最小修订

1. 从默认profile移出0037/0038，保留当前实机基线及回滚产物；本报告没有代替用户执行该修改。
2. HDR候选按实际软件输出恢复边沿建一次性、有界、仅GXLX2/VD1的实验，记录命中次数和具体提交；不以未经证实的bit12判断。
3. 删除“new_vframe_count赋1即重启VPP”的结论。若要恢复硬件状态，先指出具体硬件控制与触发条件，再设计单变量试验。
4. 首播、global脉冲、Stop/replay分开验证；每轮同时保留用户电视反馈与动态像素证据，静态回采不得通过。

依据：本地固定linux-amlogic@50c8e8154c5a及现有E900补丁；未重新做ARM编译或硬件测试。缓存/下载/遥控器等同期改动未纳入这次黑屏补丁审查。

## 对后续“源码可证根因链”的快速复核

收到补充主张：global_output=0→video_property_notify→disable_vd1_blend→new_vframe_count=0→停止提交。固定源码与已有实机记录不支持这条链：

- `video.c:10178`的global_output store只写整数并打印，未调用video_property_notify。`:526`的video_property_notify只设置property_changed；`video_hw.c:5513`处理它时设force_config_cnt/force_toggle，并不调用关层。
- `video_hw.c`中new_vframe_count全部引用只有两处关层清零、换新vf时递增、判断等于1以识别first_picture。不存在`==0`就停止向VPP提交vframe的判断；vpp_blend_update本身也没有该字段引用（新0038除外）。
- 真正首播/重播恢复路径：layer_swap_frame检测新vf→计数递增/first_picture→符合disable/type条件时enable_video_layer→VD1_MEM_POWER_ON+VIDEO_LAYER_ON→ON_PENDING→vpp_blend_update恢复blend并回IDLE。普通global恢复按enabled_status_saved恢复enabled，不必重新走ON_PENDING。
- 复用真实`build291-short-transition.json.gz`（boot b8356d5d）和`build291-a1-repeat-transition.json.gz`（boot e8a5f96c）：两轮全部记录`off=0`、guard=0。记录的off字段直接来自video1_off_req；guard位8同时检查onoff_state!=IDLE/off_req等。故在这些采样边界内没有真实关层请求，状态机保持IDLE，不能称该黑屏必经disable_vd1_blend。VSync采样不证明任意采样间的绝对无事件，但源码也没有所宣称的必然调用链。

HDR寄存器方面，`arch/vpp_hdr_regs.h:39`只定义VD1_HDR2_CTRL地址0x3800，未给出整块bypass位定义；实现中bit12明确按cgain mode使用。正常/异常两值的差分已足够否定0037当前条件，不需为同一结论再触发实机黑屏。若新代码或新固件不同，应先给出对应commit/函数与新增调用证据。

本次没有重复实机脉冲。计数与状态机根因主张应撤回；HDR完整恢复仍是待验证候选，不因上述主张错误而被排除。
