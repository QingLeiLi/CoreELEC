# Build293 黑屏对照后的 CSC 白盒审查

## 范围与依据

基线、实际boot、原始行号见[实测记录](BUILD293-RESULT-20261128.md)。本轮只读本地源码和已导出记录，没有连接盒子，没有重播/重启/改寄存器。

在固定sources fixture上应用完整0001–0043，核对amcsc.c、set_hdr2_v0.c；amcsc_pip.c辅助阅读来自/Volumes/linux-amlogic/linux-amlogic。只有前两者属于本轮完整补丁验证树，不把辅助文件当新硬件证据。

## 证据链

1. 首播返回顺序：disable0(index2450)→CSC return2(index2477)→first_frame(index2478)→CSC return7(index2479)。该窗口没有CSC_POST、没有VD1 HDR写；正常画面依赖先前配置，不能宣称首播正确运行完整HDR事务。
2. Stop：fake frame路径的FORCE_SIGNAL使CSC_POST触发（index1071，signal_change_flag=0x8000），进入video_post_process；hdr_func(VD1_HDR,HDR_BYPASS)提交batch506，CTRL=1c040与单位矩阵。HDR_BYPASS枚举不是“恢复boot配置”，是执行驱动定义的一整套bypass事务。
3. 重播同样先return2(index7916)，随后首帧及return7，但没有CSC_POST/HDR重配。不能把return7解释为HDR编程完成：函数尾部可以完全不执行被条件包围的video_post_process。
4. vpp_matrix_update在HDR_MODULE_BYPASS hold判断前，调用signal_type_changed并更新cur_signal_type、source等缓存。hold return2不保存普通CS/source变化；signal_change_latch仅特殊保存SIG_PRI_INFO。这提供了真实的“检查阶段消费变化、提交阶段不再看到”的窗口。
5. **反例**：若Stop假SDR与真视频同为HD BT.709 limited，规范化后可以相同；即使延后缓存，后续也没有信号变化。因而cache deferral不足以独立解释/修复本机黑屏，不能直接进入默认构建。

## 可复现测试与候选范围

`check-csc-signal-hold.py`编译生产vpp_matrix_update的hold前缀和生产普通signal cache变更块。原逻辑负对照证实hold消费变化；候选证实GXLX2 VD1 hold不消费，正常on/wait/force、VD2和其它CPU路径保留；**相同metadata反例仍返回0变化**。为隔离问题，signal normalization、完整hdr_policy与硬件不在该测试覆盖内。

候选保存在`candidates/0044-gxlx2-defer-signal-cache-while-layer-held.patch`，**未放入patches/linux，未加入install-patches.py，默认构建不会携带**。CI只验证该候选的逻辑及限制，没有部署它。现有HDR恢复状态机、HDR写序和return理由测试通过。

## 下一项：隔离已捕获的Stop HDR写者，无需重编

待验证问题：Stop期间HDR家族事务是否是使正常首播进入黑屏的必要副作用？不是试写0x3800旧值，不扩大到任意寄存器。

已有对照A为Build293、boot ecc141d4，默认开关、用户确认正常→Stop/replay黑屏。下一轮B需先得到用户允许并软件重启（不称断电冷启动），同一镜像/视频/静音/模式，先取得用户确认的正常参考。然后仅Stop清理窗口将既有`am_vecm.disable_flush_flag`从0置1；同代记录器覆盖Stop之前至重播之后。等待UNREG、disable请求、No vdec及disable1稳定300ms后，恢复原值0，再Open同文件一次；所有失败出口恢复原值并保留证据，不自动重试。

有效性门槛：

- 确认实际模块参数路径/初值为0；不自动覆盖用户其它值。
- Stop里出现VD1/OSD `HDR_DISABLED`，没有对应HDR_REQUEST/submitted；关键HDR实际软件写入被抑制。若迟到Stop事务在恢复开关后仍发生，标记隔离不完整，不能作负结果排除。
- 正常参考完整、Stop与重播连续同代、无溢出；最后再次核对开关恢复0。
- 目视正常：把候选缩小到**Stop HDR家族事务**；不能马上归因某位、VD1独占、HDR硬件坏。此开关同时覆盖OSD和若干HDR update入口，必须报告这个范围。
- 仍黑：只否定本轮确实抑制的Stop写入足以解释故障；若有漏写、迟到或参考失效，结果partial。
- 画面反馈后仅只读outcome；不在黑态叠加恢复试验。

该测试开关是驱动现有的提前返回，不变更软件CSC状态转换，因此能区分“Stop的软件清理”与“Stop向HDR硬件发出的事务”。**本文件仅准备方案，未执行B、没有新根因结论。** 若B支持，再拆VD1与OSD、核对GXLX2具体寄存器定义；若不支持，回到完整转换的其它写者，不重复猜测性PPS/GEN3开关。
