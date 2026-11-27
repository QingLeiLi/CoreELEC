# HDR转换仍进入G12：函数与实际写入对照

## 本轮结论

**确认HLG自动转换再次进入G12 HDR2分支。** 不是把不完整的五选择SDR修复说成失败，也不是证实SoC没有HDR硬件。新host审计在完整默认补丁栈（含0044）上执行真实剩余谓词，并核对本次HLG实际原始记录。

本轮仅本地读码、分析既有原包；没有操作设备，设备最后仍是HLG黑态、hdr_mode2、flush0。

## HLG黑屏的确定路径

1. 当前输入cur_signal_type=0x35091209，primaries9、transfer18。`get_hdr_type()`对transfer18设置HLG_FLAG。
2. 用户授权hdr_mode0→2，`hdr_support_process`因sink无HDR能力，令hdr_process_mode与hlg_process_mode=PROC_MATCH(5)。这是正常策略枚举，不是错误码。
3. 外层`vpp_matrix_update`五选择修改后走legacy `video_process`。其中csc_type=BT2020、HDR/HLG两个mode均PROC_MATCH，且get_hdr_type含HLG_FLAG，调用`hlg_process`。
4. **hlg_process内部没有继承legacy选择**，仍`if (get_cpu_type() >= G12A)`，0x2a>=0x28成立。直接调用`hdr_func(VD1_HDR,HLG_SDR)`和`hdr_func(OSD1_HDR,HDR_BYPASS)`，随后return，不执行下面legacy矩阵/LUT代码。
5. 真实窗口index137/138记录VD1 request/submitted=0x10（HLG_SDR）；139/140记录OSD1 HDR_BYPASS，submitted含RGB_OSD=0x20000001。index146的普通RDMA CTRL word=0xe05f，另有HLG转换的LUT/矩阵写入。无溢出；与源码分支一一对应。

注意本次CTRL=e05f，与先前Stop bypass黑屏的1c040不同。不能把两次故障都描述成相同bit被关闭；共同点是执行G12 HDR2事务。两次是否同一个底层硬件原因仍需独立验证。

## 其它剩余路径

|函数/位置|现有选择|本轮证据等级|
|---|---|---|
|hlg_process|>=G12A→HLG_SDR HDR2|本轮实际调用和写入命中|
|hdr_process|>=G12A→HDR_SDR HDR2|源码可达；HDR10默认bypass轮未执行，不能伪称实测命中|
|hdr10p_process|>=G12A→hdr10p_func HDR2|源码可达，未实测|
|hlg_hdr_process|>=G12A→HLG_HDR HDR2|源码可达，未实测|
|sdr_hdr_process|>=G12A→SDR_HDR HDR2|源码可达，未实测|
|vpp_matrix_update histogram|get_hist走TM2/G12条件|元数据路径可达；本轮无独立hook证明实际硬件读取|
|vpp_matrix_update HDR10/HDR10+/CUVA updates|另有G12条件|HLG当前分支不能证明命中，需格式及mode核对|
|video_process及matrix_update POST2尾部|仍按CPU数值选择|旧POST2 guard已存在，不能把该地址访问重新当新猜测根因|

## 可复现与下一步

`E900_AUDIT_ROOT=../coreelec-audit python3 e900-port/tests/check-hdr-helper-routing.py`：完整补丁应用；五个真实helper判定在GXL/G12A/GXLX2的取值；HLG source branch与真实调用/CTRL核对均通过。该文件刻意标注是**剩余路径审计**，不是认为这些选择正确，后续修改时应同步更新审计判据。

若用户继续允许最小成本试验，优先仅将`hlg_process`与`hdr_process`的各一处分支改走已有legacy实现（连同现有293L五处选择保留），再分别测试自动HDR→SDR。不能把global CPU ID伪造为GXL，也不要顺手改所有函数；矩阵/LUT写序、自动mode设置和默认/格式回归必须单列。当前尚未准备或部署这两个额外指令修改，也未证明legacy tone-map适用于此硅片。
