# Legacy 路由覆盖审查（2026-11-28）

审查基准：项目 `4364abbb4f`，Linux `50c8e8154c5aba3c7cd8438d04dd5fdd51733e41`，默认 Linux 补丁栈至0044。`amcsc.c`、`set_hdr2_v0.c`、`osd_rdma.c`按完整补丁应用后的源码审查；未被默认补丁修改的`amvecm.c`、`amcsc_pip.c`读固定版本克隆。下文行号指这一版本。范围是色彩处理及相邻提交路径，不是整个内核CPU判断的适用性认证。

**结论：默认源码尚未全走legacy。293H也只比默认多切换HDR10/HLG两个helper，不能称为全HDR修复。** 本轮只读源码、复用既有证据，没有设备动作，没有新增内核修改或ARM构建。

## 已覆盖入口与未覆盖helper

默认0044覆盖五处：`hdr_support_process`调用条件、source/policy选择、HDMI metadata回调选择、`video_process`分派、`bypass_hdr_process`内层选择。其它函数不会自动继承这个选择。

|amcsc.c函数/行|GXLX2当前实际分支|293H是否额外覆盖|证据/边界|
|---|---|---|---|
|hdr_process:5081|G12 HDR_SDR，经gamut/clip及OSD HDR_BYPASS|是|293H HDR10未实测；仅源码可达|
|hdr10p_process:5317|G12 hdr10p_func，不进入else中的hdr_process|否|所以即使HDR10 helper修好，HDR10+仍会绕过它；未实测|
|hlg_process:5382|G12 HLG_SDR及OSD HDR_BYPASS|是|293L mode2轮实际命中并黑；293H可见但偏灰，记录溢出|
|hlg_hdr_process:6305|G12 HLG_HDR及OSD SDR_HDR，随后return|否|需要HDR输出策略；当前无HDR sink，未实测|
|sdr_hdr_process:6553|sdr_mode条件内选G12 SDR_HDR|否|SDR→HDR策略，未实测|

这五处是不同方向的格式转换，不能因为0x2a>=G12A就批量改掉；必须同时核对调用策略与对应legacy实现。当前默认仅SDR首播/Stop重播有293L实验支持；源构建验收另计。HDR10+/HLG→HDR/SDR→HDR不应宣称支持。

## 外层切legacy之后仍能进入的旁路

|位置|条件与副作用|本次判定|
|---|---|---|
|vpp_matrix_update:8263–8270|toggle/force帧且CSC为BT2020/HDR10+/CUVA，数值CPU判断后调用get_hist|**独立于video_process选择**；HLG同样可能满足BT2020条件。无独立实机hit证明|
|set_hdr2_v0.c get_hist:2094起|GXLX2通过CPU门槛；尺寸非零后可能set_hist；正常读取循环也写HDR2 histogram索引|不是纯只读helper。入口可达不代表越过尺寸guard，更不代表已致黑|
|vpp_matrix_update:8363–8372|PROC_HDR_TO_SDR或PROC_HDRP_TO_SDR，加格式/metadata条件|调用hdr10_tm_update/hdr10p_ebzcurve_update，仍属HDR2更新路径|
|vpp_matrix_update:8374–8377|CUVA及PROC_CUVA_TO_SDR|调用cuva_hdr_process_update；还要求算法指针有效，未实测|
|video_process:7830；vpp_matrix_update:8379|G12 POST2尾部；LCD还直接写VADJ/3DLUT控制|现有mtx_setting/mtx_init对GXLX2 POST2已有guard。当前HDMI非LCD路径只到被guard的POST2调用；不能重报为未保护POST2写入。LCD分支不在当前验收范围|
|amvecm_matrix_process:8700–8743|空闲SDR策略：跳过旧GXL force_fake修正，进入G12 sdr_mode变化判定|策略恢复覆盖遗漏；仅sink有HDR能力时相关。当前SDR sink测试不能证明它正确或错误|
|vpp_matrix_update:8205–8208|Dolby Vision提前返回仍按数值判断老CPU|VD1不受该比较影响；VD2行为不同。无DV/VD2验收，不扩展支持结论|

重要限定：`PROC_MATCH=5`与`PROC_HDR_TO_SDR=1`不是同一个枚举值。293H HLG实验mode5不能拿来证明上表HDR10动态更新分支实际执行；需要分别记录mode、格式、入口和最终写者。

## Legacy底层也有独立的家族判断

`set_vpp_matrix`(2295/2487)、`set_vpp_lut`(3125/3191/3249)没有简单的G12分派，但仍区分TXLX/GXLX/TXHD等精确家族。GXLX2不会自动等于GXLX。

- OSD matrix/EOTF走`hdr_osd_reg`缓存；OSD OETF仅TXLX走直接写，其余也走缓存。修改缓存不是硬件已更新。
- 实际消费者在`osd_rdma.c:1100`的`osd_reset_rdma_func`：要求reset未禁用、reset_bit非零、`osd_ver<=OSD_NORMAL`，随后`hdr_restore_osd_csc()`；还受shadow_mode/rdma_hdr_delay影响。应对照缓存→shadow→准备表→IRQ及真实值，不能只查amcsc的调用。
- VIDEO EOTF仍按精确家族决定latch bit26、额外系数寄存器；OSD OETF的TXLX还有乘4位深缩放。GXLX2当前选哪条可由源码确定，但是否符合硅片不能由CPU编号证明。尤其不能为修偏灰擅自乘4。
- VIDEO通过`vpp_set_mtx_en_read/write`维护mux与矩阵/LUT配置；必须把使能、系数、输入/输出范围作为同一事务对照。293H出现大量legacy LUT软件写入，不等于所有硬件使能/颜色都正确。

## 新增相邻PQ审查

默认补丁没有修改`amvecm.c`。以下仍选择G12寄存器/数据格式：

|函数/位置|当前GXLX2选择|边界|
|---|---|---|
|amvecm_vadj_latch_process:383|VPP_VADJ1/2_MISC，而非旧VPP_VADJ_CTRL|要求FLAG_VADJ_EN；未证明本次发生|
|brightness/contrast show/store及setter:431–608|VADJ*_Y_2与MISC，亮度字段宽度也不同|参数接口，不可见到分支就称每帧执行|
|amvecm_set_saturation_hue/post:1641–1721；vpp_vd_adj1_saturation_hue:3509|VADJ*_MA_MB_2/MC_MD_2及MISC|输入格式/策略可能影响饱和度；尚无偏灰因果证据|
|cm_init_config:6392|cm_default而非cm_default_legacy|调用是否到达另算；init_pq_setting的G12初始化入口使用精确G12A/G12B/SM1，**本身不包含GXLX2**，不能把整段初始化说成执行过|
|amvecm_post_matrix_data_show:4456|按G12 3x10bit解包探针|仅调试输出；未校准前不据此判断像素颜色正确|

`amcsc_pip.c`也被Makefile编入，但本次未找到G12A/G12B选择；这不等于已验证VD2/PIP硬件。`video_sink`已有legacy_vpp分派，与CSC/PQ数值判断并不是一个统一能力开关。不能全局伪造CPU ID来掩盖这些区别。

## 下一步固定顺序

1. 保留SDR五处正式修复；HDR/HLG两helper仍是293H候选，不因为本轮清单而扩大默认修改。
2. 偏灰先沿293H已实际执行的legacy VIDEO事务白盒核对：POST YUV2020→RGB、EOTF曲线与使能、2020→709矩阵、OETF gamma22、XVYCC限幅输出以及mux；OSD独立看缓存消费者。先给出预期写序/范围，再与同源SDR参考和HLG实际提交对照，不调饱和度掩盖问题。
3. 采集需要分离LUT payload与控制/生命周期，避免52446条payload挤掉入口/使能/退出事件；旧溢出原包只证明保留前缀，不能排除后续HDR2写者。get_hist需独立命中/写者证据，不能靠hdr_func计数覆盖。
4. 若再推广HDR10/HLG源码修复，先明确禁止或隔离剩余HDR2旁路的范围，并为其它CPU保持原行为；HDR10+等方向另立试验，不顺手放开。

相关：[五处正式修复](LEGACY-CSC-FIX-20261128.md)、[HLG G12实机命中](HDR-G12-HELPER-AUDIT-20261128.md)、[293H结果](BUILD293H-HDR-HELPER-TRIAL-20261128.md)。
