# 启动速度优化：当前试验未通过

基准build294/d94c005b，用户确认菜单正常。用户随后要求优化启动速度，并确认方便观察重启。

基准systemd数据：kernel6.812s + userspace11.308s；kodi.target到达内核起算约18.121s。kodi-waitonnetwork在关键链上耗4.215s，systemd-hwdb-update约3.226s；wait-time-sync9.555s但不在Kodi关键链，不处理。以上不包含U-Boot加载时间，也不等于上电到可见菜单的准确时间。

本轮预先声明的配置组合：

1. 原始内核/SYSTEM/DTB不变，bootargs hw_init_wait从1改0，允许bus-ready时自动初始化；控制台loglevel7→4，完整内核ring仍保留。
2. 持久systemd drop-in令Kodi不阻塞等待联网，连接服务仍运行。触碰/storage/.config/e900-boot-wait-network即可重新允许原等待服务。
3. 保存原三个启动入口于/storage/e900-boot-speed/previous；诊断wait=1引导另放/flash/e900-boot-diagnostic，回退脚本/storage/e900-boot-speed/rollback.sh已准备。

## 失败结果

新bootf01e34cc-a97d-414e-a2dd-6609c55896fd。硬件初始化1.334014秒complete，network-wait按新增Condition跳过，Kodi active、GUI RPC为Home；HPD1、1080p60，采样IRQ有值。**用户确认界面黑，未通过，不以init complete或RPC Home替代画面。**

systemd报告kernel9.005s+userspace11.477s=20.482s，但kodi.target在userspace8.197s到达（内核起算约17.202s）。与基准相比Kodi目标只早约0.919s，userspace目标早3.111s被kernel阶段约2.193s波动抵消；全系统就绪反而更晚。只有一次软件重启，不把差值写成可靠加速或上电菜单耗时。

本轮同时变更等待、控制台级别及联网阻塞，尚未区分是哪项/时序导致黑屏。自动MMIO初始化更早是事实，不能直接认定唯一根因。完整kernel trace及Kodi日志已保留。

得知黑屏后仅保存只读状态，未再写显示寄存器、未继续播放/重启。按照AGENTS.md要求已询问能否回退重启，等待用户确认。源码e900-usb-image.src的试改已恢复基准，避免下一次构建默认带入未通过的快速模式；失败候选只留在本目录evidence，未作为正常默认。

后续先恢复已知正常菜单；若用户仍需优化，再逐项验证：保持诊断wait=1/log7，只隔离网络等待；自动初始化必须验证合适的软件阶段，不能仅把它前移到bus-ready就宣布安全。hardware-db服务不盲目禁用，现有3.3秒工作生成/run/hwdb.bin（约11.7MiB），缓存是否划算及失效条件尚未测。

[基准](evidence/boot-speed-20261128/before.txt)、[失败状态](evidence/boot-speed-20261128/failed-fast/state.txt)、[内核日志](evidence/boot-speed-20261128/failed-fast/dmesg.txt)、[Kodi日志](evidence/boot-speed-20261128/failed-fast/kodi.log)、[回退脚本](evidence/boot-speed-20261128/rollback.sh)。
