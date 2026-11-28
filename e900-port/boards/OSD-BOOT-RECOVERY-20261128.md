# E900重启黑屏：已验收开机补偿与源码集成

用户纠正“重启黑屏的问题你忘了？”后继续处理；不把此前单次运行时恢复当成重启修复。依据为[OSD初始化丢失及单次因果恢复](OSD-STARTUP-RDMA-20261128.md)。

## build294运行时实现与范围

不需重新编译。脚本[启动补偿](../scripts/e900-osd-rdma-boot.py)和[service](../config/e900-osd-rdma-boot.service)安装在U盘STORAGE分区：

- `/storage/.config/e900-osd-rdma-boot.py`
- `/storage/.config/system.d/e900-osd-rdma-boot.service`
- `/storage/.config/system.d/kodi.service.d/30-e900-osd-rdma.conf`

Kodi通过Requires/After依赖此oneshot，它在graphical.target之后、Kodi之前执行，避免已开始播放后再修。不是定时延迟、循环写寄存器或全局RDMA reset。

仅接受本机DT ID、build294精确版本21.3-Omega_devel_20261128084424、4.9.269、正常自动初始化模式wait0、hw_init_status2、无vdec活动。先采独立OSD完成计数：正在增长则零写入跳过；仅当计数0、AUTO0x120、DMA页34e10000及表长度合法时恢复已验证CH3字段。重新读回防止状态变化；恢复后必须两次采样持续增长且CH3字段正确，否则只恢复原CH3字段并失败，保留其它通道变化。

未知构建自动跳过；同构建异常状态拒绝写入并阻止Kodi盲目继续，SSH仍保留。这是**当前构建的持久开机补偿**，不是已完成内核RDMA初始化依赖的通用根修。换新内核/镜像需重新审计或合入驱动修复，不能删掉版本保护盲用；无HDMI启动/热插拔尚未验收。

## 检查与部署结果

主机检查 `tests/check-osd-boot-recovery.py` 覆盖正常恢复、已健康跳过、不同构建/诊断模式跳过、错误板/内核/总线未就绪/活动解码/异常AUTO/DMA/非零停滞/写前状态变化拒绝，以及失败仅回退CH3而保留CH2。检查已加入workflow。

现机执行`--check`：同2a016423，OSD完成22415→22422，输出already-completing，未再写控制器。安装unit和drop-in后daemon-reload，systemd-analyze verify通过；Kodi Requires/After均包含新服务。随后用户授权软重启并完成下述验收。

### 软重启验收通过（2026-11-28）

新boot `787ad4a9-eb6d-4d60-a74b-7817315d77d7`，用户反馈“正常”。无需手动再写寄存器，服务在Kodi启动前完成：

- 初始独立OSD计数0→0，AUTO=0x120，表START=0x34e10000、END=0x34e10107。
- 仅恢复CH3后计数12→26，AUTO=0x014001e0；后续4593→4655，证明完成持续推进。CH2由正常回调配置，未被补偿覆盖。
- 服务于17.444s结束，Kodi17.476s开始；Linux+systemd目标17.569s，**不含U-Boot时间，也不是测得的上电到菜单时间**。
- 初始化状态2，TF卡仍自动挂载。没有更换内核/SYSTEM或写eMMC。

原始记录：[启动与顺序](evidence/osd-boot-acceptance-20261128/state.txt)、[补偿日志](evidence/osd-boot-acceptance-20261128/recovery.json)。本次证明这一配置的一次软重启成功，未覆盖断电、无HDMI启动/热插拔及长期重复。

## 源码和镜像集成

用户确认正常后要求持久化到源码。`install-patches.py`对decoder配置安装CE官方device filesystem overlay，`scripts/image`每次组装SYSTEM时复制以下启动配置（另含hwdb预生成，见下述链接）：

- `/usr/lib/e900-boot/e900-osd-rdma-boot.py`
- `/usr/lib/e900-boot/source-contract.json`
- `/usr/lib/systemd/system/e900-osd-rdma-image.service`
- `/usr/lib/systemd/system/kodi.service.d/30-e900-osd-rdma-image.conf`
- `/usr/lib/systemd/system/kodi-waitonnetwork.service.d/20-e900-fast-boot.conf`

执行顺序、唯一CH3写入、前置检查和失败回退沿用已实测方案。正常USB引导默认wait0/log4，诊断wait1仍可手动使用且不会触发补偿。后续按用户要求纳入可恢复的跳过网络等待配置，屏保默认保持上游。

新镜像不按构建日期放开：只读SYSTEM内契约必须与固定CE/Linux revision、板型、4.9.269和RDMA布局完全匹配，并核对os-release的BUILD_ID；源码pin变更时installer拒绝安装，要求重新审计。现场的AUTO、独立计数、DMA页等保护仍保留，内存布局变化会拒绝写入。build294原运行时安装仍支持原精确版本。

镜像service使用独立的`e900-osd-rdma-image.service`名，避免旧STORAGE安装同名unit遮蔽SYSTEM版本。现盒子原有运行时服务保持不动；换新镜像后旧脚本因版本不同跳过，由镜像内服务执行。源码部署不代表已在盒子执行新版本。

overlay文件纳入构建状态哈希与本地修改保护；只改这些overlay项时不清理内核或工具链，CE重新打包即带入。43项主机检查全部通过，包括实际CE镜像复制函数、源码契约、保护/回退和缓存保留。**新源码镜像完整构建及实机启动仍待下一轮验收**；构建选择decoder + image。

这是将已验证的启动补偿纳入源码构建，尚未消除内核早期codec dispatcher未发布导致写入丢弃的底层依赖问题。

hwdb后续优化见[预生成与规则重建](HWDB-PREBUILD-20261128.md)，额外安装systemd-hwdb-update条件drop-in，不改变OSD补偿。

## 开关、日志与回退

- 禁用开机补偿：`touch /storage/.config/e900-osd-rdma.disable`，下次启动跳过，便于保留原始故障；删除该文件重新启用。
- 诊断wait1启动也会跳过，不抢先写硬件。
- 每次日志：`/storage/e900-boot-speed/boot-rdma/<boot-id>.json`，同时进入systemd journal；记录先创建，再尝试硬件写入。
- 旧运行时安装完全撤销：删除Kodi的30-e900-osd-rdma.conf、该service与脚本，daemon-reload。镜像内版本使用上述disable标记禁用；要移除文件需源码改动后重新打包。原build294内核/SYSTEM、TF配置未改；原诊断引导仍在/flash/e900-boot-diagnostic。
- 屏保临时关闭已按用户要求恢复dim模式；网络等待开关已纳入源码，详见启动速度文档最新条目。
