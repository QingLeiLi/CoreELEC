# 混合关闭/恢复白盒追踪（2026-11-25）

固定上游：linux-amlogic 50c8e8154c5aba3c7cd8438d04dd5fdd51733e41。本地媒体源码coreelec-audit/gen3-research-20261124/linux-amlogic；以下行号相对该检出，实际固件另叠加e900补丁。本文是代码审计，不是新增实机修复结论。

## GEN3：用途已知，差异位仍未知

VD1_IF0_GEN_REG3(legacy1aa7)属于VD1读内存/MIF控制，不是解码器状态寄存器。

- video_hw.c:993 legacy vd1_set_dcu对bit8:9设置bit_mode，对bit0按VIDEO_LINEAR设置；非legacy还设置bit1:2的burst_len。
- amvecm/bitdepth.c:241 vpp_vd1_if_bits_mode也写bit8:9；精确匹配G12A/B才用3216，其余用1aa7。
- deinterlace_hw.c:674的TXLX分支写bit4:6；2442的legacy路径写bit8:9。
- rdma.c/rdma_mgr.c最终RMW可能从硬件、当前队列、已提交表、冲突表取整字基值，携带未选中的高位。

没有找到可靠的GXLX2 bit12:13定义，也没有找到正常业务分支显式将这两位设为3。现有日志证明生成过33、随后又读回3033；不能据此断言另一模块主动改位。正常彩条期间也观测过3033，因此不能把这个值当充分故障标志。详细寄存器资料见GEN3-RESEARCH-20261124.md。

## 从最小复现出发的调用链

### 1. 软件输出控制

video.c:10178 video_global_output_store只更新global_output。没有直接设置property_changed/new_vpp_setting/force_config_cnt，没有调用完整显示硬件初始化。故“写回1”等同于请求恢复输出，不等同于执行完整状态重置。

### 2. 不只改变混合位

video_hw.c:513 get_video_enabled返回enabled && global_output。global_output写0后，任何调用者都可看到video off，甚至早于vpp_blend_update更新enabled。

video_hw.c:5027起，vpp_blend_update将enabled置0，清VD1_PREBLEND、VD1_POSTBLEND、VD2_PREBLEND、PREBLEND_EN；恢复时将enabled还原enabled_status_saved并重新加入VD1混合位。其后还有：

- 5046附近更新VIDEO_PROP_CHANGE_DISABLE/ENABLE；video.c:6691通过video_prop_change和amvideo_prop_change_wait发布事件，8950 amvideo_poll_poll消费事件。是否存在用户态消费者尚未核实，不应直接归因Kodi。
- video_hw.c:4808 post_blend_dummy_data_update根据enabled选择启用/关闭背景色，并在自动标志开启时提交VPP_DUMMY_DATA1。
- 本机活动非本地帧下，这条global_output路径不直接调用safe_switch_videolayer或安排VD1内存掉电；遇到local/无效帧时另有真实关层分支，不能一概而论。

### 3. 之前遗漏的PPS/SR重刷

video.c:4244 primary_render_frame：即使没有new_vpp_setting，get_video_enabled=false或ON_PENDING也会调用vd_scaler_setting(0,...)，注释说明为防止PPS系数丢失，在重新上电前重刷。

调用链：primary_render_frame → vd_scaler_setting(video_hw.c:4557) → vd1_scaler_setting(:2210) → vpp_set_super_scaler_regs(vpp.c:2229)，之后配置普通PPS控制、滤波系数、相位和窗口。

**静态可确认的能力保护缺口**：vpp_set_super_scaler_regs读出sr_support，但顶层SR0/SR1控制、core0控制及core0尺寸仍有无条件访问；core1内部配置/尺寸则检查SUPER_CORE1_SUPPORT。sr_support为0时，函数也可能访问SR0/SR1相关地址。0021只保护video_hw_init的SR0 sync入口，没有覆盖这个运行时函数。sr0_sr1_refresh默认1。

不能直接跳过整个函数：其后仍有共享VE输入尺寸、输出尺寸和路径处理。能力位为0也不能自动证明全部同名地址不可访问，应针对具体地址及有效路径核实。首播也调用此函数，故这不是已证明的唯一黑屏原因。

### 4. 之前遗漏的amvecm/HDR关闭恢复状态机

调用链：video.c的amvecm_on_vs → amvecm.c:1425 → amcsc.c:8259 amvecm_matrix_process。

- amcsc.c:6903 is_video_layer_on直接依赖get_video_enabled及wait_on。
- :7969 is_video_turn_on识别开/关边沿；重新打开会使cap_changed=true(:8344)。
- :8410起，关闭时可清last_vf、累计null_vf_cnt；:8517当video_process_status=ON而视频关闭时，将null计数/阈值设为1。
- :8539后可发送fake SDR frame、将HDR模块置OFF/BYPASS，再调用矩阵/HDR处理；恢复时需要真实/重复帧及force/cap_changed路径重新更新。
- :8048/:8101/:8144使用数值cpu_after_eq(G12A)选择G12策略/HDMI包路径和video_post_process，而非legacy video_process。GXLX2数值0x2a会满足这些条件。video_post_process在amcsc_pip.c:1506，HDR_OFF也会走hdr_proc(VD1_HDR/HDR_BYPASS)，可能涉及OSD HDR路径。

本次仅只读确认本机am_vecm模块参数：csc_en=7、hdr_policy=1、sdr_mode=0、空闲video_process_status=2,2；因此不能说CSC被配置关闭。上述函数是否在故障边界执行到具体分支，尚需证据。数值选到G12路径也不能单凭这一点断言硬件绝不兼容，不能将整个amcsc一刀切改成GXL。

## 当前诊断的真实边界

0029已覆盖混合入口/提交出口的固定点、配置、背景色/裁剪/路由、VPP时钟门控和RDMA进度。但尚未记录PPS系数的提交内容/次数，也没有amvecm内部video_on、null_vf_cnt、video_process_status、flags及fake/真实帧处理决策。仅拿0029的VPP寄存器时间线，不能声称已跟踪全部关闭副作用。

因此此前“不必再加”的判断过早。下一步应针对上述已知调用链补业务决策/提交证据，不继续盲试GEN3高位、保留混合位或重置整个模块。已确定的代码保护缺口与已证明的硬件根因必须分开表述。

## 后续落实

0030已修运行时SR专属访问的能力保护，保留共享尺寸与其他CPU行为；0031已将上述PPS重刷和amvecm业务状态/分支计数接入边界记录。本文前述“未记录”描述审计时的af48dae4f4状态，新增实现见[RUNTIME-SR-FIX.md](RUNTIME-SR-FIX.md)。尚未ARM编译/实机验证改动效果。


## 独立视频 RDMA 看门狗（0032，待实机）

rdma_mgr 的看门狗由多个通道共享。健康 OSD 的完成处理可以不断清零共享计数，掩盖视频通道长期没有完成中断的问题。0032 在 GXLX2 的 VSYNC 视频通道单独累计未完成帧，默认 20 帧后请求现有 force_rdma_config 提交流程重试；不复位共享硬件、不改工作模式、不直接写寄存器。其他 CPU、LINE 通道与正常完成路径保留原行为。

`rdma.gxlx2_stall_frames` 可设为 0 禁用；只读 `gxlx2_stall_rearms` 记录重试次数，两者纳入 e900-debug 快照。事件预算开启时输出 stall_resubmit。这里的恢复计数仅表示发起重提，不代表硬件已经恢复，仍需对照 irq_count/vsync_cfg_count。

主机测试执行实际修改前后 _vsync_rdma_config 和管理器看门狗函数，模拟健康 OSD 持续清共享计数：原版视频停滞，修改版每到独立阈值重新提交；同时验证其他 CPU、模式及通道行为。尚未 ARM 编译和实机验证。

这修复的是已独立观察到的 RDMA 饥饿问题。此前 IRQ 健康的冷启动仍能复现重播黑屏，因此不能宣称它解决重播问题。

## HDR 旁路的源码含义

set_hdr2_v0.c 的 hdr_func 并非在 HDR_BYPASS 时直接返回。它准备旁路矩阵和 LUT 后，仍依次调用 set_hdr_matrix(HDR_IN_MTX)、set_eotf_lut、set_hdr_matrix(HDR_GAMUT_MTX)、set_ootf_lut、set_oetf_lut、set_hdr_matrix(HDR_OUT_MTX)、set_c_gain、hdr_hist_config。OSD1_HDR 且 cpu_after_eq(G12A) 时还会写 VPP_WRAP_OSD1_MATRIX_EN_CTRL；GXLX2 的数值 ID 满足这个判断。因而“策略为 SDR/旁路”不能排除寄存器配置副作用。

VD1_HDR2_CTRL 为 0x3800、OSD1_HDR2_CTRL 为 0x38a0（源码 arch/vpp_hdr_regs.h）。这些常量不证明 GXLX2 具有对应硬件。当前只记录此调用风险和分支证据，不盲目读取未知硬件地址，也不把整个 G12 HDR 路径强制换成 GXL。

普通 PPS 系数通过 VPP_SCALE_COEF_IDX 后连续写 VPP_SCALE_COEF。rdma_write_reg 保留这些同地址的顺序写入；尚未发现软件队列将系数去重的证据。队列语义检查不能替代硬件系数验证。


## HDR 提交边界观测（0033，待实机）

0031 的 CSC 分支计数不能证明具体执行了哪个 HDR 模块或策略。0033 因此在实际 hdr_func 中增加四类事件：hdr_flush_disabled（软件禁止刷新，提前返回）、hdr_request（请求模块/策略）、hdr_osd_wrap_off（即将关闭 OSD wrap 矩阵）、hdr_submitted（矩阵/LUT/直方图配置函数均已返回，含有效策略及 LUT/矩阵开关）。最后一项仅证明软件提交路径走完，不证明 RDMA 完成或输出有效像素。

使用既有 E900_DEBUG_CHANNEL 机制，默认关闭、GXLX2 限定、root 权限、每次最多 512 条预算，不读新增寄存器、不改 HDR 策略。参数位于 am_vecm.gxlx2_debug_events，e900-debug 的 arm/disarm/快照已纳入该模块。事件具有已有内核时间戳，可与边界记录对齐。预算耗尽后事件缺失不能解释为没有执行。范围是普通 hdr_func；HDR10+ 的 hdr10p_func 不在此钩子范围，当前 SDR 彩条复现不走该专用入口。

主机检查：去掉显式诊断语句后源码与前版逐字一致；执行实际刷新保护、OSD 分支和提交尾部代码，覆盖五种 CPU、三个模块及刷新开启/关闭，并校验提交事件在八步配置调用之后。复用现有通道预算测试。ARM 编译及实机故障边界日志仍待完成。
