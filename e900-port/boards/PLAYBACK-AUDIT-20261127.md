# 首播、Stop、重播的成对观测

## 2026-11-28 修订：连续转换执行器

Build292证明旧的“decoder出现后等120ms”会漏显示初始化，三段分别冻结会漏Stop异步清理。**下一轮使用`e900-playback-session.py`；下文旧命令仅保留为历史有界窗口接口，不再将其结果当完整转换。** 旧compare现在明确输出`INCOMPLETE_TRANSITION`。

需要新0043内核：只读`gxlx2_playback_live_api=1`，65536条有界append-only记录（约3MiB静态内存），同锁下导出8条前缀，活动期也可读取；用户态核对generation、行号、溢出。切换phase重置16组安全读预算，不重置generation/提交批次，Stop→replay不冻结、不重新arm。ring-only路径采完固定寄存器即返回，避免逐帧pr_info；原显式legacy快照仍保留。首帧事件改为每个软件生命周期session首次非fake toggle，不再依赖上游first_picture重配置策略；它是软件显示调用边界，不是硬件出图证明。没有改变显示策略、HDR处理、寄存器允许表或新增任意MMIO。

新工具先检查版本、容量、init完成、hold0/HDR实验N/RDMA1,0/global1及旧verbose探针关闭。旧固件缺接口会在媒体动作前失败，不尝试猜测兼容。

```sh
# TOOLS为本次部署的debug-tools目录，RUN必须是全新目录。
python3 "$TOOLS/e900-playback-session.py" first --run "$RUN"
# 等用户确认彩条正常后，单独采Stop前参考；这一步不播放、不停止。
python3 "$TOOLS/e900-playback-session.py" reference --run "$RUN" --confirmed-normal
# 只有上述两步完成且仍获准观察，才执行一次Stop→重播。
python3 "$TOOLS/e900-playback-session.py" transition --run "$RUN"
python3 "$TOOLS/e900-playback-session.py" compare --run "$RUN" > "$RUN/comparison.json"
```

首播/重播完成判据：同一最新provider会话中的首帧、配对DCU/PPS调用、VD1 HDR请求/提交及活动态固定读回，且disable=0，条件持续300ms；并非解码帧计数。缺hook、调用跳过、超时、错代或溢出均记`INCOMPLETE`，不自动补播、不自动重试、不宣布硬件损坏。该判据刻意保守：合法路径若没有这些事件，也需要审查原记录后修正覆盖模型，不绕过门槛。

正常参考另存原页，需用户明确确认、同boot/文件、活动层，至少两次非零FIFO与MIF/misc/HDR读回。FIFO非零本身不是画面证据；零值与用户画面冲突时停止，不继续制造故障。

Stop阶段等待provider UNREG（固定头文件值1）、disable请求1、No vdec、disable=1持续300ms；随后在**同一代**内标记phase3并重播。它不保证每个内核延迟工作都已完成，但延迟清理与重播之间没有记录器重置造成的空隙。RPC同时保存发送/返回boottime和响应。超时则只导出原记录，绝不执行重播。

容量扩大仍不保证任意时长完整，6秒默认timeout也不是覆盖保证。达到上限仍明确溢出冻结，不能用重新arm拼接。主机测试覆盖真实Build292反例、实时前缀、同代阶段切换、Stop超时禁止重播、静默ring路径及补丁应用；完整ARM构建、新hook实机可达性、观察开销与实际画面尚待验证。

本工具与新的0038观测补丁配套；旧Claude固件没有该接口。目标是保存同一boot三段原始时间线，区分生命周期、软件写意图、准备表、完成关联和受保护实际读回。它不会自动播放、Stop、重启、恢复时钟或改变显示策略。

## 采集顺序

先部署新构建、核对commit和boot，保持HDR恢复等隔离开关关闭、音量0、固定模式和同一长片。只在用户允许对应轮次后执行媒体动作；用户需要观察时先等回复。

每个run用全新绝对目录。准备首播前执行：

```sh
python3 e900-playback-audit.py arm --run "$RUN" --phase first
# 保存实际Player.Open的RPC请求/回执，只调用一次；确认解码帧数推进
python3 e900-playback-audit.py freeze --run "$RUN" --phase first
```

确认首播正常后，以相同命令对`stop`阶段arm，再执行一次实际Player.Stop，直到decoder退出/真实清理已完成后freeze。最后对`replay`阶段arm，再执行一次Player.Open，解码推进后及时freeze。三个阶段使用同boot，播放provider代次可以改变，代次本身是证据而非要求完全相等。每段从媒体动作前开始，动作完成后立即冻结，不能等看完长片才导出。容量耗尽时明确失效，不靠截掉记录“修好报告”。

各次RPC原文、首播/重播电视反馈与时间、前后dmesg、构建来源另存run。不要删除失败尝试的owner文件然后重跑；新run也不能把异常播放态当首播。用户确认黑屏后先归档并停止操作。

主机收齐run再运行：

```sh
python3 e900-playback-audit.py compare --run "$RUN" > "$RUN/comparison.json"
```

输出包括first_only、replay_only、changed_ordered_values、三段完整timeline及按来源/类型统计。重复写值完整保留，寄存器交集/并集同时给出；缺失基准不是0，更不是未初始化。分析时按生命周期对齐（provider注册、首帧、PPS、HDR事务、blend提交），不要按绝对毫秒或第N条硬对齐。完整cross-address顺序在timeline中，逐地址数组仅为差异索引。

## 接口与有效性

内核rdma_mgr的独立`gxlx2_playback_*`接口，原0035九列接口保持不变。先设置phase再arm；arm保留phase并生成marker。state六字段generation/status/count/capacity/overflow/phase，data每页8行，每行12列：index generation stamp source kind session phase batch handle reg value aux；前两列十进制，余下十六进制。stamp为统一kernel jiffies，boot_id由用户态保存。

source：1生命周期，2普通RDMA，3 OSD独立RDMA，4关键地址直接写，5受保护实际读回。kind：1 marker，2 state，3 prepare，4 word，5 irq，6 cancel，7 read。具体事件code与固定地址允许表见0038头文件；没有hook的路径不在覆盖范围。

比较器拒绝溢出、错boot、错代、缺行、原页与派生行不符、缺阶段marker及混合phase。每段只允许一次arm；freeze只操作自己的generation。输出永远是REVIEW_REQUIRED，不能仅凭相同最终写值宣布链路正常。阶段间存在人工观看间隔，**不声称连续记录了整个视频播放时段**；三个窗口内的实际媒体动作覆盖完整性还需RPC与生命周期边界验证。

真实Stop只记录软件状态；硬件读回仅沿已有active/bus/legacy VD1保护。准备表或IRQ关联不等于每个写值落地，实际配置有值也不等于像素有效。OSD和直接写覆盖固定地址，不追全机MMIO。VDIN硬件完成槽到payload的关联缺口仍需后续核实；静态回采不能证明视频正常。

## 验证状态

用户态测试`check-playback-audit.py`覆盖错boot、错代、溢出、原页篡改、缺阶段、重复写值及缺基准处理。新内核观测补丁另有生产代码host测试；ARM编译、部署和三段实机配对尚待完成。一次构建同时携带默认关闭HDR恢复实验和本观测，但先做默认关闭的首播/重播，避免多变量。

## 明确覆盖表与限制

固定写地址允许范围：0x1a00–0x1aff、0x1d00–0x1dff、0x3800–0x38ff、0x3d60–0x3d6f。覆盖来自普通manager表、OSD私有表和codec_reg_write(VC bus)分派；绕过这些函数的其他总线/底层裸写仍不覆盖。实际读回仅活动态MIF GEN/Canvas/FMT（1a50/1a51/1a68）与VPP_MISC/VPP_FIFO_STATUS（1d26/1d28），最多16次通过既有guard的样本；不新增HDR_CTRL实际读取，不在真正Stop中读掉电bank。其它布局/路由的旧stage日志可另外归档，但不能伪称已全部进入新ring。

OSD source3 prepare的trigger/value=0表示**可变表窗口**，aux=RDMA_TABLE_INTERNAL_COUNT(512)表示容量，不是最终提交字数；窗口中保留初始表和随后追加/覆盖的选定word（aux为item索引）。IRQ aux为当时最终item_count，仅与软件pending窗口关联，无硬件cookie。普通RDMA source2 prepare aux仍为实际item_count，word顺序严格检查。末尾pending批次是冻结边界，必须在审计中注明；取消、溢出、未完成不能省略。

生命周期code：1 provider、2 disable、3 first_frame、4 layer_switch、5 blend_state、6 PPS、7 CSC post、8 HDR request、9 HDR submitted、10 HDR disabled。blend_state value按enabled bit0/global bit1/onoff bits2..4/disable bits5..6打包，aux为new_vframe_count。新观测不会把new_vframe_count改成1。

代次隔离：批次号跨arm不归零，每代记录floor，迟到旧word/IRQ不进入新代；软件IRQ关联仍保留无硬件cookie限制。独立ring容量4096，满即冻结并置overflow，比较器拒绝。没有自动覆盖旧记录，也不会自动重试媒体操作。

本轮完成检查：新内核ring/用户态比较器/HDR恢复状态测试、原HDR策略与写序、video-init-order，以及post2、video-pipeline、display-stage-hooks、gen3-rmw-osd、blend-boundary、blend-transition、submit-tables、runtime-sr均通过。USB产物导出检查通过，工具/doc已加入构建产物。新增OSD源文件固定基线hash已列入source-fixtures；旧合成测试仅补观测stub，保留原策略断言。display-stage增加连续无帧guard拒绝回归，确认新ring路径零MMIO、零日志、不消耗有效样本预算。缓存检查仍有本地reference文件缺失的既有限制；没有因此宣布全套CI或ARM编译通过。

## 0039/0040扩展（本轮源码，尚未部署）

0040在同一活动态保护与采样预算内追加HDR2_CTRL原值和既有mode2固定布局/PPS地址：1a69/1a6a、1a53..1a56、1d19/1d01/1d02/1d13/1d08/1d18/1d0d。上文“仅5项读回”是0038的原覆盖，最新读回以本段及FULL-CHAIN-OBSERVABILITY-20261127.md为准。没有新增LUT/selector写。

首播与重播冻结可显式加`--hdmi-status`保存现有TX config/avmute状态，Stop阶段会跳过。`config`含硬件和软件字段，`hpd_state`是软件HPD，AVMUTE getter读现有硬件状态，不构成线上的有效像素证明。

0039回采新包使用明确v2头格式并关联preACK完成槽；必须配套新inspect和loopback工具。像素候选报告/回环报告补充boot_id，避免跨启动拼接证据。旧v1可离线复核，但不满足新的槽关联要求。

0041新增生命周期code11/12=DCU进入/返回，13/14=PPS进入/返回，15=PPS不支持而提前返回。compare的localization将事件与实际寄存器差异映射到函数/寄存器名，保留原始行和缺覆盖标记；readback_provenance仅给先前写入候选，不把异步提交与当前读回不相等直接当作故障。详见全链路文档的逐项判据。

0042新增code16 DCU空帧、17 PPS缺参数、18 CSC/HDR返回原因。比较器lifecycle逐项解码return_reason，含正常函数尾部与提前返回；完整含义见全链路文档。首播源Canvas的已验证正常证据保留，本轮不新增Canvas读取，也不把VDIN目标槽核验混作源Canvas故障。
