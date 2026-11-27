# Build293 Stop HDR事务隔离：重播画面正常

## 结论与范围

同一Build293镜像，正常参考→Stop/replay；默认A组用户确认黑屏，B组仅Stop清理期间禁止HDR家族flush、重播前恢复开关，用户确认正常。B组有效阻止预定事务，未记录到迟到HDR请求/写入。**支持Stop HDR家族事务为故障触发范围**，尚未区分VD1 HDR、OSD HDR及其它受该全局开关影响的update入口；不是永久修复验收。

|项目|A默认对照|B Stop-only隔离|
|---|---|---|
|boot|ecc141d4…|2dac9312…|
|首播物理画面|正常|正常|
|重播物理画面|黑屏|正常|
|Stop HDR调用|VD1/OSD请求提交|VD1/OSD被HDR_DISABLED拦截|
|Stop后HDR关键寄存器|CTRL=1c040；矩阵单位值|CTRL=d05f；所采矩阵保持0|
|重播VD1 HDR请求|未记录|未记录|
|稳定FIFO采样|均0|0与401effe交替|
|最终disable_flush_flag|0（默认）|0（已读回恢复）|

FIFO原值只作为配套观测，不单独证明像素；正常物理画面来自用户确认。两boot均软件重启，不称真正断电冷启动。不是严格同boot跨组对照，也未做ABA重复。

## B原始证据

Build293 /run46047603617/fb2ea8ae69，Python执行器含1274cf1713。boot `2dac9312-ae38-4a9d-a6a2-fbfaa0252f67`；init1、flush0、No vdec起步，网络READY后释放init并静音首播。用户确认正常后采独立参考。

- first/reference/transition/outcome分别6374/222/12329/280行，均无溢出；首播/重播选定调用、八项核心读回齐全。outcome同boot/文件配对及当前播放器身份通过。
- 参数写1 boottime123974166932ns；Stop123974192890ns；异步边界No vdec/disable1稳定300ms。恢复0 boottime124661025141ns，随后Open124662043016ns。
- Stop `HDR_DISABLED` index1077(handle1 VD1)、1078(handle3 OSD1)，均HDR_BYPASS=1。没有未拦截request/submitted；完整transition全部phase没有0x3800–38ff选定软件word。并非只检查Stop摘要，也检查了重播阶段迟到事务。
- reference/transition/outcome的HDR CTRL均d05f，3802/3804/3806/380e均0，GEN3=33；所采PPS/布局正常值保留。FIFO包含0/401effe，转换启动另有1effe；不能把瞬时0当坏。
- 用户确认重播正常后仅GetItem与只读采样，未Stop/Open/重启。最后再次读到disable_flush_flag=0，设备保持静音正常播放。

归档：[摘要](evidence/build293/stop-hdr-guard-01/summary.json)，目录包含四段原始页/行及RPC结果gzip。本地完整原包`../trial-build293/stop-hdr-guard-01`。默认A对照见[Build293结果](BUILD293-RESULT-20261128.md)。

## 下一项

优先拆分已命中的Stop事务：VD1 HDR_BYPASS与OSD1 HDR_BYPASS分别抑制，并保留默认0/两者均抑制的矩阵对照。既有disable_flush_flag只能做全家族屏蔽，无法在运行时区分调用；若增加源码实验入口，需一轮构建带齐选择、记录和实际命中证据，默认关闭，不改任意寄存器、不把全局禁flush作为最终方案。当前不启用候选0044 cache deferral：它不能解决相同SDR元数据下的硬件状态失效。

本轮不追加播放。后续物理实验仍先等用户可观察确认。若选择器实验不复现，先审查初态/实际生效/开销，不立即宣布修复。
