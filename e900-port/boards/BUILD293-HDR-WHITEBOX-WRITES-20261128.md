# Stop HDR 白盒：79地址与CTRL的确定性来源

## 可复现与边界

本轮只读源码/已有A、B原包，无设备动作，无新增内核实验。运行：

```sh
E900_AUDIT_ROOT=../coreelec-audit python3 e900-port/tests/check-stop-hdr-whitebox.py
```

测试核对固定fixture哈希，抽取生产`set_hdr_matrix/set_eotf_lut/set_ootf_lut/set_oetf_lut/set_c_gain`的HDR CTRL RMW语句，以HDR_BYPASS所选参数MTX_OFF/MTX_ONLY、LUT_OFF执行，输出与A组一致。**不是完整hdr_func仿真，不证明GXLX2硅片位义、不证明某位致因。** 辅助寄存器头与amcsc_pip.c来自固定内核clone，其HEAD已确认50c8e8154c5aba3c7cd8438d04dd5fdd51733e41。

## 79地址分组

对两轮Stop phase2选定写者地址取差集（不是所有MMIO差集）：

|组|A独有地址数|源码写者|
|---|---:|---|
|VD1 HDR2|39，0x3800–383c内选定地址|hdr_func(VD1_HDR,HDR_BYPASS)→set_hdr_matrix等|
|OSD1 HDR2|39，0x38a0–38dc内选定地址|hdr_func(OSD1_HDR,HDR_BYPASS)→set_hdr_matrix等|
|OSD wrap|1，0x3d6d|hdr_func的OSD1/G12数值判定分支关闭VPP_WRAP_OSD1_MATRIX_EN_CTRL|

A组batch506的index1079–1117为39个VD1地址；index1118为wrap；index1119–1157为39个OSD地址。B组整段转换均无0x3800–38ff选定软件word，并有VD1/OSD HDR_DISABLED命中。这个分组说明为何全局禁flush不足以指认VD1：同时撤销了OSD与wrap副作用。

## 0xd05f→0x1c040：源码可精确重放

|生产阶段|CTRL累积值|
|---|---|
|正常参考初值|d05f|
|HDR_IN_MTX|1d04f|
|EOTF enable|1d047|
|GAMUT|1d047|
|OOTF enable|1d045|
|OETF enable|1d041|
|HDR_OUT_MTX|1d041|
|CGAIN mode/enable|1c040|

异或=0x1101f，仅bits0/1/2/3/4/12/16不同。按**此驱动的赋值用途**：0=cgain enable、1=OOTF LUT enable、2=OETF LUT enable、3=EOTF LUT enable、4=mtx_on、12=cgain mode；这些从1变0。16=mtx_only从0变1。bit13在两个值中均0，不能把本轮差异简单描述成“bit13全局关掉了”。上述名称是源码意图，不能不经硬件文档就当作GXLX2规范定义。

更完整副作用仍包括：VD1 clock gate写0（注释为auto gate）、MATRIXI_EN_CTRL写1、输入/输出矩阵及gamut/adaptive参数重写。**7个CTRL位不是整个事务的全部可疑项。** 不对真实设备回写某位试图恢复。

普通RDMA`rdma_write_reg_bits`会先找当前队列同地址，用准备值继续RMW，并原位更新同一item；因此batch506只出现一次最终CTRL word，不代表其它源码RMW没执行。离线逐步结果是CPU计算，不伪装为逐周期硬件状态。

## LUT、矩阵与平台路径

- GXLX2不命中always_full_func（该条件只针对G12A或G12B revA）。HDR_BYPASS于是选lut_on=0/cgain_en=0、mtx_only=MTX_ONLY、mtx_on=MTX_OFF；不是按原值跳过。
- 三个LUT upload函数以及cgain在写enable后均因OFF提前返回，不向LUT地址/数据口上传payload。本轮不支持“Stop上传了一份坏LUT内容”的方向；**LUT使能改变仍可能参与故障，不能排除整个LUT阶段。**
- mtx_only=1且mtx_on=0时，输入矩阵使能寄存器仍特意写1，并写单位矩阵（VD1）或RGB→YUV矩阵（OSD）。不能从MTX_OFF名字推断整块无作用。
- 本项目video早初始化已将GXLX2固定为legacy_vpp/MIF，而amcsc的`cpu_after_eq(G12A)`仍会选择video_post_process/HDR2路径。这是**软件能力分类不一致**；它支持优先核对GXLX2 HDR能力/寄存器布局，不单凭CPU大小证明HDR2不存在，也不建议把整个CSC无条件降级为GXL。

## 收敛后的下一步

优先白盒核对GXLX2与G12在上述时钟门控、mtx_only/输入矩阵及OSD wrap路径的硬件差异；若缺硬件资料，明确缺口。已有A/B仅确定Stop HDR家族事务的触发作用，不能凭软件重放选择某bit作为根因。

若还需实机，只做有依据的最小分拆：VD1事务、OSD事务（OSD包含wrap），同一新构建携带默认关闭的选择器；必要时同时保留VD1控制/门控/矩阵的后续分组，不为每次细分反复构建。参数范围及记录须先准备齐，待用户可观察再操作。当前没有新增内核补丁、没有部署或要求构建。
