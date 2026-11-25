# E900 显示链路基础调试

> 287实测发现跨Stop回采的场景响应疑点；旧黑图暂不能作为当前输出的充分证明，见[最新验证记录](BUILD287-VALIDATION.md)。
这套功能提供可复用的源码日志、活动视频配置快照、Canvas 像素取证和成对差异报告。补丁0022随 decoder profile 安装；默认所有新增生命周期日志关闭，不改变显示策略、初始化、RDMA模式、时钟状态、帧所有权或视频输出。

**状态：构建45341511160完整ARM编译通过，Image287/SYSTEM287已配对部署；新hook、SR0能力保护和成对回采已实机执行。重播黑屏仍在。没有新增独立VD1/PPS像素回采点。**

## 观察面与边界

| 观察点 | 证据 | 输出 |
|---|---|---|
| 视频 provider 注册/注销、视频层开关、DCU配置 | 操作次序、调用者、黑屏策略、层使能及状态机 | `e900-debug channel=video` |
| DI注册时 bypass/开CLKB、注销时清理 | 实际分支及操作次序 | `channel=di` |
| VPU时钟门控/内存操作 | 模块ID、请求和已应用的门控表项数；调用者 | `channel=vpu` |
| RDMA软件模式、配置、完成 | 请求/当前/前次模式，handle，first/done/force，中断和配置计数 | `channel=rdma`，只读`gxlx2_debug_state` |
| RDMA管理器 | IRQ分发、队列溢出直接写回、watchdog复位；各队列长度/容量/状态 | `channel=rdma_mgr`，只读`gxlx2_debug_state` |
| 固定可疑CPU寄存器写入口 | VD1 GEN(1a50)、GEN3(1aa7)、VIU_MISC0(1a06)、VPP_MISC(1d26)的写值与调用者 | `channel=registers`；不代表RDMA硬件执行日志 |
| 显示驱动收到的活动帧 | index/PTS/type/flag/bitdepth/planes，来源和目标Canvas | 原`e900-stage input`与`e900-snapshot kind=frame` |
| VD1读图配置 | 原GEN/GEN2/GEN3、FIFO、格式、Canvas live/shadow，新增第二图地址/范围、色度范围、repeat、格式宽度 | 固定表配置回读，受原stage hook的活动帧/legacy银行/总线检查保护 |
| 显示路由/混合 | VIU_MISC0/1、HOLD_LINES、OFIFO，混合请求/live/shadow | 配置证据，不是像素证据 |
| 当前显示Canvas描述 | 三平面的地址、尺寸、wrap、blockmode | **软件缓存**，不是硬件LUT读回 |
| Canvas像素 | `/dev/amvideocap0`同步GE2D采集320×180 BGR24，PNG、原始文件、hash、布局和完成状态 | **位于VD1/VPP之前**，不可称为HDMI截图 |
| 旧式ENCP输出回环 | 285已校准，首播运动彩条、重播实际全黑 | 是输出侧支，不能代替物理HDMI接收端观察 |
| VD1、缩放、混合之间的独立像素 | 尚无校准成功的独立取点 | 不能通过配置相同判定这些内部阶段正常 |

每条生命周期事件包含channel、单调递增seq、event、a/b/c/d及符号化调用者；内核时间来自dmesg。每个子系统独立限额0..512条，root才能设置；默认0。额度用完停止输出，不能把“未记录”解释为“未执行”。`arm`会重置额度，不能在测试中途无记录地重新arm。

快照复用`amvideo.gxlx2_stage_samples`的0..8保护；脚本每次只申请4份，结束/异常退出归零。固定硬件回读仅在活动、非压缩、legacy VD1、总线就绪且寄存器表已识别时执行。不增加任意地址接口，不访问`/dev/mem`、kcore、trace_reg或停止态VDIN。不启动VDIN，不改变OSD、DI、RDMA或时钟模式。

## 构建与安装

沿用decoder、linux构建；source_trace保持false，vdin_capture沿用当前选项以复用兼容工具链。0022本身不要求打开VDIN。仍须部署同一构建的匹配内核和模块；不能把新内核配旧SYSTEM强行测试。

构建产物新增`export/decoder/debug-tools/`，包含本工具与此文档。工具不自动开机启用，复制到可写`/storage`即可：

```sh
scp e900-port/scripts/e900-debug.py root@192.168.31.11:/storage/e900-debug.py
```

旧内核可使用采集器的现有状态和Canvas截图功能；缺失新参数明确记为unavailable，不能声称新日志已生效。参数所在模块名由该构建Kbuild决定；工具检测`amvideo/di/vpu/rdma/rdma_mgr/register_ops`，若实际不同，先核对`/sys/module`与日志channel，更新映射，不创建新的寄存器接口。

## 正常/异常成对取证

同一冷启动、同一片段、同一显示模式、同一播放时间点，只改变一次Stop/replay。初次观察前不要测试暂停、OSD、缩放或驱动参数。快照是一个时间区间，不是跨所有模块的原子快照。

1. 播放前开启有限生命周期日志：

```sh
python3 /storage/e900-debug.py arm --budget 256
```

2. 默认设置首播。确认正常，在约15秒采集，保存命令打印的目录：

```sh
python3 /storage/e900-debug.py snapshot --label normal --pixels
```

3. 在一次受控Stop/replay前重新arm，避免CPU寄存器写额度在首播耗尽。两次快照分别保留完整dmesg，因此第一段生命周期不会丢失；后一次`lifecycle_since_arm`只展示最近一次arm以后的事件：

```sh
python3 /storage/e900-debug.py arm --budget 256
# 执行既定的Stop/replay，约15秒后：
python3 /storage/e900-debug.py snapshot --label abnormal --pixels
python3 /storage/e900-debug.py disarm
```

标签来自操作者的观察，工具不自动把某次播放认定为正常或黑屏。无人观察时使用`repeat_unobserved`等标签。没有活动H264则拒绝像素采集；超时、布局错误、非完成状态均标记失败，不写成有效黑图。

4. 两个目录可复制到Mac/Linux后离线对比，标准库即可：

```sh
python3 e900-debug.py compare /path/to/normal-directory /path/to/abnormal-directory > comparison.json
```

每个目录包含`snapshot.json`、完整`dmesg.txt`；像素成功时另含`canvas.bgr`和`canvas.png`。snapshot记录boot-id、cmdline/kernel版本、采集前后解码状态、VFM、显示几何、选定模块参数、内存/中断、Kodi JSON-RPC播放状态、时间区间、有限probe日志及最近arm以来的生命周期。图片带尺寸/完成状态/来源/hash；移动视频截图不同是预期现象，不能用hash差异认定故障。

对比报告列出配置字段的取值集合差异、缺失观测、显示状态/VFM差异、两侧软件参数及像素结果。保留完整原始日志，不仅保留差异。index/PTS/seq/epoch/物理地址等动态字段仍在原始快照，不作为配置差异噪声；地址需结合平面布局和帧时间人工分析。

## 事件字段字典

| channel / event | a / b / c / d |
|---|---|
| video / provider_unreg、provider_reg | blackout / force_blackout / enabled / onoff_state |
| video / provider_unreg_end | layer1_used / layer2_used / enabled / onoff_state |
| video / layer_switch | layer_id / requested_on / async / prior_onoff_state |
| video / dcu_config | layer_id / frame_type / bitdepth / frame_flag |
| di / register_bypass、register_clkb_on | frame_type / width / height / prior_bypass_flag |
| di / unregister_mirror_disabled | mirror_disable / bypass_flag / mcpre_en / 0 |
| vpu / gate_applied | vmod / requested_on / matched_table_entries / 0 |
| vpu / memory_request | vmod / power_flag / 0 / 0 |
| rdma / configure | channel / current_mode / previous_mode / force |
| rdma / completion | channel / mode / configure_return / completion_count |
| rdma_mgr / irq_dispatch | handle / already-read_irq_status / queued_items / write_count |
| rdma_mgr / overflow_fallback | handle / queued_items / table_bytes / triggering_register |
| rdma_mgr / watchdog_reset | watchdog_count / threshold / forced_reset / 0 |
| registers / write_vc | fixed_register / requested_value / prior_bus_write_count / 0 |

门控日志证明调用和匹配表项，不直接证明物理时钟运行；RDMA state和队列state是READ_ONCE的软件区间读，不保证多字段原子。寄存器日志只看CPU写入口，不能把没有write_vc记录理解为硬件没有写入。

## 收敛规则

先看每个观察点是否有效，再看正常/异常差异。先定位最后一个有正确像素的点和第一个有错误像素的点，才讨论二分；未校准回采点保持unknown，超时保持failed。若只有Canvas像素正确，就只能把剩余范围记为VD1/VPP至输出，不能根据配置回读宣称某一级像素正常。

后续新增VD1/VPP回采必须同时给出正常首播的彩条图、完成/新鲜度证据、尺寸格式和明确的硬件取点。沿用这套快照结构存入新point，完成正常/异常成对采集后再进入修复。不再凭单个配置差异提交行为修补。

## 本轮验证记录（2026-11-24）

主机通过：check-local、check-video-init-order、check-display-stage-hooks、check-debug-foundation、check-build-cache、check-usb-image。新增测试编译执行实际C日志宏、固定快照片段和两个软件状态getter，并验证限额、其他CPU、无效参数、缺失证据及失败截图的对比语义。检查不是完整ARM内核编译。

采集器已在当前旧内核执行一次`terminal_only --pixels`：JSON与完整dmesg落盘、BEGIN/END边界有效、无活动H264明确记为skipped、stage预算恢复0。没有播放/重启/变更RDMA或时钟策略。旧内核不具备0022的新hook，不能把这次执行当作新源码实机验证。证据保存在工作区`trial-sr280/debug-foundation-terminal/`。

已核对固定基线Kbuild：video.c/video_hw.c链接在amvideo，deinterlace.c链接在di；vpu、rdma、rdma_mgr、register_ops各自拥有新增参数，不会在同一复合对象重复定义本日志通道。

## 下游回环校准进展

既有Image280上已在新启动首播取得真实运动彩条输出回环；[原始依据、格式校准和证据](LEGACY-LOOPBACK-CALIBRATION-20261124.md)。这是legacy输出观察点，不是新增独立VD1/VPP WB取点。`inspect-vdin-snapshot.py --yuv444-bt601 --reverse64`提供已校准的显式预览。

`e900-calibrate-loopback.py`须在新启动、初始化已完成且未播放时运行，将旧式采集会话保持到Stop/replay之后，避免每启动一次保护。工具会操作播放器并启动VDIN，与只读状态采集器的作用不同；保持静音，结束先停VDIN后停播放器。每张回采前后另记Kodi GUI状态及单调时间区间，防止将菜单覆盖或窗口切换归为视频黑图。无需现场看屏幕，标签仍注明无人观察。

## 源码GEN3单变量试验（0023）

默认关闭的`/sys/module/amvideo/parameters/gxlx2_gen3_clear_high`只在GXLX2、legacy VD1、未借用VD2且GEN3确为1aa7时，紧随正常位深配置，通过同一个VSYNC RDMA API请求清bit12..13。仅恢复成对正常/异常差异，不修改其他CPU、位深或低位配置。它是诊断候选，不是已验证修复。

`gxlx2_gen3_clear_high_submits`记录软件提交次数，`gen3_clear_high`生命周期事件记录reg/mode/start/length；这两者都不证明实际落地，仍须对照live/shadow及像素。

新内核上可执行：

```sh
python3 /storage/debug-tools/e900-calibrate-loopback.py --gen3-experiment
```

保持同一VDIN会话先取默认首播、默认重播，再显式开启候选、停止重播取第三组。结束恢复原开关并关闭有限日志。该选项已在287构建并实机执行；未恢复输出，详见[287验证记录](BUILD287-VALIDATION.md)。

若需要捕获驱动探测/复位早期事件，可在新内核诊断启动参数中加入各通道的有限预算：`rdma.gxlx2_debug_events=256 rdma_mgr.gxlx2_debug_events=256 vpu.gxlx2_debug_events=128 register_ops.gxlx2_debug_events=256 amvideo.gxlx2_debug_events=128 di.gxlx2_debug_events=128`。管理器reset_request记录VC/HHI软件就绪状态；固定可疑VC写丢失记录为drop_vc。不改变总线初始化顺序，不重新播放丢写。

逐函数职责、控制流与数据流、观测边界和后续分析分支：[显示链路分析导航](DISPLAY-CHAIN-ANALYSIS.md)。

## GEN3来源与OSD单项实验（0024）

独立固定寄存器RMW预算、软件基值来源、默认关闭的legacy OSD blender-only实验及A/B流程见[实验说明](GEN3-OSD-EXPERIMENT.md)。新增功能主机检查通过，完整ARM/实机仍待新构建。

## 中间像素候选探针（0027）

现已实现8个源码命名的VPP候选selector、128点固定扫描及原始值导出，待实机逐点校准；详见[中间像素观测](INTERMEDIATE-PIXEL-PROBES.md)。上文“尚无独立取点”描述的是既有实测证据，不能把新源码等同于已验证观测。

新增0029[混合过渡记录器](BLEND-TRANSITION-RECORDER.md)补足软件enabled=0但帧仍被持有、内存供电的关闭窗口。同一固定点的前/后提交时间线留存在有界内存，不逐帧打印。配套e900-transition.py区分提交与硬件读回，缺失/全零不自动标黑；新增根因观察仍需ARM构建和实机校准。


### HDR 请求与提交事件

0033 将 `am_vecm` 加入标准 `arm` / `disarm` / 快照模块列表。`channel=hdr` 的 `hdr_request`、`hdr_osd_wrap_off`、`hdr_submitted`、`hdr_flush_disabled` 用于将普通 HDR 配置与输出关闭/恢复边界对齐；`a` 为模块，`b` 为策略，submitted 的 `c/d` 为 LUT/矩阵开关。submitted 仅指配置函数返回，不等同硬件提交完成。默认关闭，受已有 0..512 预算限制，无新增 MMIO。详细覆盖及限制见 BLEND-SOURCE-AUDIT-20261125.md。


### PPS/HDR 软件准备表

0035增加独立、默认关闭的实际RDMA准备表记录器，保留重复系数及IRQ/取消关联。现有HDR入口日志无法替代逐字表项证据；用法与严格覆盖限制见[SUBMISSION-TABLES.md](SUBMISSION-TABLES.md)。尚需ARM构建和实机验证。


### 固定点非零值的限制（2026-11-25）

双混合位保留对照中，固定点持续非零，但下一次同点采样全零；控制组因没有稳定参考而未切换输出。因此非零值不能证明持续有效数据，可能存在旧值保持或探针重配置依赖。后续需先以无像素探针的目视对照校准，不能据此宣布某显示阶段正常。详见[VD1-VPP-CONVERGENCE.md](VD1-VPP-CONVERGENCE.md)。
