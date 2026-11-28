# 全输出 legacy CSC/PQ 对照基准

## 切换前基准与回退

- 源码基准：`e5cefe4d9b`；独立基准记录提交：`51e67ef98e`。默认最后补丁0044，仅五处SDR选择改变。
- 固定Linux：`50c8e8154c5aba3c7cd8438d04dd5fdd51733e41`，CoreELEC/media版本不变。完整Linux补丁SHA256清单：[baseline.json](evidence/legacy-all-baseline-20261128/baseline.json)。
- 最后实机是293H二进制实验，不是默认源码构建：boot `d6929b25-28a5-4768-91b1-0edcdac3dcf5`，在293L五处外再切HDR10/HLG两个helper。HLG自动匹配mode5能见彩条但偏灰，65536行记录溢出；颜色未验收。用户已关机，本次未访问设备。
- 已有成功范围：293L的H264 SDR首播与一次默认Stop/replay。没有全格式、LCD、HDR直通或多轮稳定性承诺。
- 源码回退至上述基准提交即可恢复原补丁选择；重新构建时继续使用受检查的增量缓存。设备原293/293L/293H文件的历史保留位置见各部署记录，本次没有重查或覆盖它们。不要把源码回退与设备已回退混写。

## 本轮改动

用户明确要求全部切legacy，不局限HDMI。新增默认decoder补丁`0045-gxlx2-all-output-legacy-csc-pq.patch`，覆盖**色彩处理及相邻PQ的pre-G12/legacy选择**；不伪造CPU ID，不改解码器、网络、存储或整个SoC的世代定义。

|范围|行为|
|---|---|
|HDR10/HDR10+/HLG→SDR、HLG→HDR、SDR→HDR|五个helper均采用已有legacy实现；HDR10+的旧实现退到静态HDR10处理，不宣称保留动态metadata tone-map能力|
|CSC旁路及恢复策略|关闭G12 histogram、动态HDR更新旁路；空闲SDR策略使用legacy判定；VD2的DV提前返回条件与legacy一致|
|LCD、dummy ENCP、HDMI等|生成家族判断不依赖输出类型。LCD也不再进入G12 POST2/VADJ/3DLUT尾部；走原legacy分支的输出模式处理|
|PQ/VADJ/白平衡/CM|amvecm.c、amve.c、amcm.c对应的G12寄存器选择回落旧实现，包括亮度/对比度/饱和度、CM使能位、默认表选择和调试像素解包|
|HDR2公共写者|hdr_func/hdr10p_func、LUT/矩阵/clip、histogram及动态更新等14个入口，对GXLX2在副作用前返回；另阻止amvecm的直接histogram初始化。防止DV/PIP/off或导出接口绕过上层选择|
|OSD legacy|保留已有matrix/LUT缓存→shadow→OSD RDMA消费者；不将GXLX2冒充TXLX/GXLX，不擅加位深缩放。已有POST2底层guard仍保留|

新增49处生成选择，连同原五处入口覆盖；HDR2入口guard没有输出类型条件。其余CPU保留原谓词和写序。旧GXL/TXL/TXLX等细分规则仍按实际CPU身份运行，不能把“legacy”解释为全局将CPU变为S905/GXL。诊断的既有安全寄存器读回保留；禁用HDR2处理不等于删除所有观测读数。

这是用户指定的整体路由对照，**不是49个独立硬件缺陷已被证实**。它能验证完整旧路径的行为，不能用单次结果拆分49处各自的因果。先保存整体结果，再从可比基准选择必要的局部对照。

## 构建与验证

默认decoder已安装0045，无需新增checkbox。需要可启动USB系统时选`profile=decoder`、`target=image`；source_trace保持关闭，VDIN沿用原设置。只构建linux不会生成完整新USB系统。该Linux补丁变化沿现有增量策略重建Linux及相关安装状态，兼容工具链继续复用。

新增固定版本fixture：amvecm.c/amve.c/amcm.c，均从指定Git对象提取并记录Git blob SHA1和SHA256；云端按现有fixture下载器取得。新增`check-all-output-legacy.py`已加入Actions主机检查：

- 执行49处实际新谓词，在CPU ID 0..127及多输出/状态组合下核对：只有GXLX2回落legacy，其余CPU与原表达式相同。
- 执行14个实际HDR2早退guard与直接histogram初始化guard；核对它们在硬件访问前，GXLX2无模拟副作用；没有其它条件或写体被悄悄改动。
- 逆向移除明确新增的谓词/guard/include后，与0044基准逐字相等。原五选择测试单独固定在0044阶段，HDR观测测试单独核对观测逻辑；不能把新路由策略变化误报成诊断修改。

主机测试不替代完整ARM编译。尚未部署；SDR首播/重播/输出关闭恢复、HDR10/HLG正确颜色、VDIN回采，以及LCD/其它物理输出均待验证。没有LCD实机时只能验证源码路由，不宣称其硬件可用。

本轮最终默认补丁栈的38项Actions主机检查全部通过，另通过历史HLG证据对照检查。完整补丁应用、安装器保护和增量缓存检查均包含在内；没有触发云构建或部署。

HDR策略参数默认值未被顺手修改：全走legacy不等于自动将`hdr_mode=0`变为auto，也不代表HDR→SDR已正确tone-map。后续格式实验记录实际mode及sink能力；先取得SDR正常参考，再按预定流程检查，黑态不叠加试验。

参考：[切换前覆盖审查](LEGACY-ROUTING-COVERAGE-20261128.md)、[293H实机结果](BUILD293H-HDR-HELPER-TRIAL-20261128.md)。
