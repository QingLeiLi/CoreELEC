# 启动速度优化与网络等待配置

## 最新状态：补偿验收后落地（2026-11-28）

此前黑屏已通过独立OSD CH3补偿完成一次软重启验收并纳入源码，见[启动补偿](OSD-BOOT-RECOVERY-20261128.md)。下文保留实验历史，不代表当前仍失败。

用户要求跳过网络等待落地：SYSTEM overlay新增`kodi-waitonnetwork.service.d/20-e900-fast-boot.conf`，仅对等待服务增加ConditionPathExists；默认先启动Kodi，不禁用ConnMan、DHCP、NTP或连接后台任务。网络未就绪时IPTV、网络媒体库和共享访问仍需等待连接；依赖启动即联网的用户可执行`touch /storage/.config/e900-boot-wait-network`，下次启动恢复上游等待逻辑（仍需满足其原条件）。删除标记重新跳过。现机已使用同内容drop-in，无需重启或再次部署。

时钟检查：2026-11-28盒子显示14:15:56 UTC，ConnMan TimeUpdates=auto、TimeserverSynced=True；日志有启动时NTP jump及14:09:31的slew +0.033915s。问题为UTC时区，而非缺少NTP。经Kodi Settings API设China/Asia/Shanghai后，系统显示22:16:55 CST，`/var/run/localtime`指向Asia/Shanghai。ConnMan Clock缓存Timezone仍显示UTC，不据此否定实际系统链接与本地时间；不重启网络进程。默认四个pool.ntp.org作为fallback，未另加校时守护程序或强制改NTP服务器。

按用户要求恢复原屏保`screensaver.xbmc.builtin.dim`，不改源码屏保默认。时区和屏保属于当前用户配置，未全局强制所有刷机用户采用中国时区。无重启、播放或显示寄存器操作。实际CE overlay复制及构建缓存测试通过；新镜像构建验收仍待进行。


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

## 同配置复测及当前现场

用户随后报告首次快速启动的画面已恢复，并明确要求“软重启一下，我再看下”。未回退、未改配置，按原wait0/log4+不阻塞网络再次软件重启，boot `0db732f8-7884-4c6d-a82a-d7b1d9fd5b9c`。该事实纠正“首次一直黑”的理解；首次恢复时间/触发条件未采到，不据此认定永久初始化失败或已解决。

第二轮：自动初始化1.329985s complete；kernel8.875s/userspace11.711s，总体20.587s；kodi.target为userspace8.186s（内核起算约17.061s）。用户报告“目前是黑屏”，随后只读检查：HPD=1、1080p60、AVMUTE=0，无活动vdec；OSD/VSync合并IRQ7062→7123、RDMA IRQ7020→7081（约1秒）；fb0虚拟1920×3240/32bpp；Kodi Home/Movies、屏保与DPMS均false。

这些只证明软件在线和显示时序/中断推进，不能证明OSD新鲜像素、图层混合或实际HDMI图像有效。第二轮黑屏不与旧的RDMA中断停滞现场混同；不能以这些参数声称“显示链路全部正常”。未在这次黑屏后继续重启、改寄存器或播放。当前仍保留快速启动现场，尚未执行回退。

[第二轮启动](evidence/boot-speed-20261128/repeat/state.txt)、[黑屏状态及IRQ对照](evidence/boot-speed-20261128/repeat/black-state.txt)、[Kodi状态](evidence/boot-speed-20261128/repeat/kodi-state.json)。

## 第二轮菜单迟到且偏暗

用户随后报告“现在出现菜单了”，再报告“但是很暗，感觉是到了降低亮度的低功耗状态下了”。没有写显示寄存器、重启或恢复配置。收到菜单出现反馈后的采样uptime=234.58s；不是精确的第一帧时间，只能说明17s的Kodi服务/target就绪不能等同于可见菜单就绪。内核207.066747s曾打印 `fb: update_table_item overflow!vsync_cnt=12382, rdma_cnt=0`；尚无原始正常到异常的完整OSD表/独立通道中断对照，不能直接认定该条为迟到/偏暗根因。

偏暗时只读RPC：ScreenSaverActive=false、DPMSActive=false，屏保模式screensaver.xbmc.builtin.dim、超时3分钟。布尔名称已与Kodi官方说明核对。配置了dim与当下处于dim是不同结论；尚未把画面暗归因于省电。已请用户只轻按一次方向键，观察是否立即恢复亮度，等待反馈；不改亮度/寄存器。

[菜单出现后的日志](evidence/boot-speed-20261128/repeat/menu-appeared.txt)、[偏暗时屏保和DPMS状态](evidence/boot-speed-20261128/repeat/dim-state.json)。
