# A1 离线准备与就绪交接

日期：2026-11-25。执行准备：sol；astra审计修正后离线通过。**本页只记录离线准备；未连接设备、未重启、未首播、未触发A1。**基线分支`fix/gxlx2-late-video-init`，计划提交`6c16cdda9d`，证据检查器提交`12de65e5fc`；执行时工具commit用实际部署源码的`git rev-parse HEAD`，设备固件仍以现场核对为准。

## 已备材料

- 一次性分阶段脚本：`e900-port/scripts/e900-a1-run.py`。四个显式阶段`prepare`、`baseline`、`pulse`、`final`；同一run的baseline/pulse拒绝重复调用。首播只用TCP JSON-RPC，逐条保存request及原始reply到`rpc.jsonl`。打开前查Kodi与`No vdec.`，设置并读回音量0；打开后核实H264帧数推进、保存初始提交表及代次。pulse前核对同片、播放速度、剩余≥180秒、解码帧数推进、同boot VDIN会话、1080p60hz、RDMA与本run预检一致、global1、hold0、GEN3 N、disable0。
- pulse复用归档的`e900-register-transition.py`之`collect()`，参数等价于`--off-seconds 0.2 --with-submissions --with-loopback --loopback-calibrated --exercise-global-output`。采集器自身先取得新鲜彩条双帧，不合格则不切换。包装先取得现有四把锁，核对edge/submit空闲，再改hold并在同进程调用collect；由collector `finally`负责代次、global恢复，不强杀进程。保存`collector.stdout/stderr`、`exit-code.txt`、`transition.json`（若产生）、前后dmesg/decoder及清理状态。包装仅在global为1、hold仍为3且两个记录器均不活动时恢复hold0；否则保留现场并标记。
- 离线证据门槛：`e900-port/scripts/check-a1-transition.py`，审计与负对照见`A1-GATE-AUDIT-20261125.md`。历史`../trial-build291/short/transition.json`的真实混合位关闭、after仅一张，明确被拒绝；不代表已做A1。

## 授权后人工分段流程（现在不要执行）

1. 先由astra审脚本及工具版本。用户允许新软件boot及本轮首播/一次脉冲后，按执行计划手动记录旧状态、reboot一次、核对新boot、必要时按READY流程释放video init。任何异常停止，不把脚本当重启/初始化工具。
2. 将同一提交的8个工具及`e900-a1-run.py`放入设备独立工具目录；运行采集器`--help`确认`--off-seconds`。用UTC命名新run，例如`/storage/e900-experiments/A1-YYYYMMDDTHHMMSSZ`，先创建其父目录。`prepare`会用独占新建，旧目录存在即失败；要求/storage≥128MiB，/flash仅检查不写。主机创建对应独立目录，不覆盖旧证据。
3. 显式执行：`python3 e900-a1-run.py prepare --run "$E900_RUN" --tools "$E900_TOOLS" --tools-commit "$TOOLS_COMMIT"`。人工补齐manifest里的OS构建来源/内核版本、设备身份、初始状态、授权原话、用户反馈时间和未知项；核对工具hash及参数。脚本记录boot、display/RDMA、edge/submit、空间、工具小文件SHA256；关键固定条件不符时停止。RDMA值从现场读取写入manifest，pulse要求完全一致；没有从历史猜固定值。
4. 经审核后显式执行：`python3 e900-a1-run.py baseline --run "$E900_RUN"`。该阶段只允许一次`Player.Open`；失败后先审RPC及播放器/解码状态，不再次调用。保存首播提交，不声称覆盖更早HDR初始化。
5. 人工检查/只启动一次本boot VDIN，按计划完成当前路由校准，并将证据文字写入`$E900_RUN/CURRENT-CALIBRATION-CONFIRMED.txt`。回采前后均由collector使用`NO_GATE=1`，不补开钟。确认视频还有至少3分钟、固定条件和正常参考；如需要电视目视，先等用户明确回复。按批准的A1轮显式执行一次`python3 e900-a1-run.py pulse --run "$E900_RUN"`。不要在同一run或黑态重试。
6. 即使pulse退出非零，也保存全run和主机日志，显式执行`python3 e900-a1-run.py final --run "$E900_RUN"`；SSH断开时先只读核对，勿自动重启。将设备run原样复制到本地新目录，再运行`python3 e900-port/scripts/check-a1-transition.py "$RUN/transition.json" --manifest "$RUN/manifest.json" --image-dir "$RUN/transition-images" --out "$RUN/verdict.json"`。检查器退出1/2属预期审计信号，不能让归档链被`&&`截断。人工打开原包和PNG，核对实际hold每个phase、提交覆盖、图像新鲜度和现场反馈，填写`AUDIT.md`交astra；审计前不进入下一分支。

`prepare`不自动reboot/释放init/启动VDIN；`baseline`不因等待失败二次Open；`pulse`不自动重拍或第二次脉冲；`final`只读快照。建议每阶段用独立SSH命令并保存主机命令、SSH退出码及输出；若SSH断开，设备端可能已完成动作，必须先读run标记和RPC日志再决定后续。可将获准的单阶段用`nohup`启动并轮询结果，不能因此自动连跑后续阶段。baseline/pulse处理HUP/TERM/INT并进入清理；SIGKILL、掉电、内核阻塞不能保证完成归档，需按部分证据处理。

本实现的`baseline.json`对应计划的`baseline-start.json`，`final.json`对应`final-state.json`；每阶段保留`.started`防重复标记。脉冲的`exit-code.txt`和CLI返回码一致，非零仍保存`pulse.json`及已取得证据。

## 离线检查与限制

已通过：`python3 e900-port/tests/check-a1-run.py`（非零/异常保留、退出码传递、锁冲突发生在修改前、替换代次不恢复hold、拒绝重复脉冲、TCP通知与分段回复）；`python3 e900-port/tests/check-register-transition-client.py`；`python3 e900-port/tests/check-a1-evidence-gate.py`；采集器`--help`含`--off-seconds`。未做ARM构建、部署或实机验证；本轮不改内核，无须为A1重新构建。

astra离线审计结论：**执行准备通过，可在用户允许该轮且现场前提核对后运行一次A1。**审计修正了错误sysfs路径、强杀超时、先修改后加锁、未知RDMA常数、RPC分包、退出码及代次清理问题。没有新的硬件因果结论。设备版本/身份、真实工具部署、VDIN会话、原包及物理HDMI结果仍待现场核对。`manifest`的OS commit初始写unknown，必须由现场构建来源填实；工具commit由调用者提供且需与归档hash核对。逐VSync读回不能排除采样间短暂关位；软件提交/IRQ不证明逐字硬件执行。采集器若未写出`transition.json`，只保留部分日志和状态，不伪造完整判定。
