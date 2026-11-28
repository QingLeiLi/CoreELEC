# build294重启黑屏：持久开机补偿

用户纠正“重启黑屏的问题你忘了？”后继续处理；不把此前单次运行时恢复当成重启修复。依据为[OSD初始化丢失及单次因果恢复](OSD-STARTUP-RDMA-20261128.md)。

## 实现与范围

不需重新编译。脚本[启动补偿](../scripts/e900-osd-rdma-boot.py)和[service](../config/e900-osd-rdma-boot.service)安装在U盘STORAGE分区：

- `/storage/.config/e900-osd-rdma-boot.py`
- `/storage/.config/system.d/e900-osd-rdma-boot.service`
- `/storage/.config/system.d/kodi.service.d/30-e900-osd-rdma.conf`

Kodi通过Requires/After依赖此oneshot，它在graphical.target之后、Kodi之前执行，避免已开始播放后再修。不是定时延迟、循环写寄存器或全局RDMA reset。

仅接受本机DT ID、build294精确版本21.3-Omega_devel_20261128084424、4.9.269、正常自动初始化模式wait0、hw_init_status2、无vdec活动。先采独立OSD完成计数：正在增长则零写入跳过；仅当计数0、AUTO0x120、DMA页34e10000及表长度合法时恢复已验证CH3字段。重新读回防止状态变化；恢复后必须两次采样持续增长且CH3字段正确，否则只恢复原CH3字段并失败，保留其它通道变化。

未知构建自动跳过；同构建异常状态拒绝写入并阻止Kodi盲目继续，SSH仍保留。这是**当前构建的持久开机补偿**，不是已完成内核RDMA初始化依赖的通用根修。换新内核/镜像需重新审计或合入驱动修复，不能删掉版本保护盲用；无HDMI启动/热插拔尚未验收。

## 检查与部署结果

主机检查 `tests/check-osd-boot-recovery.py` 覆盖正常恢复、已健康跳过、不同构建/诊断模式跳过、错误板/内核/总线未就绪/活动解码/异常AUTO/DMA/非零停滞/写前状态变化拒绝，以及失败仅回退CH3而保留CH2。检查已加入workflow。

现机执行`--check`：同2a016423，OSD完成22415→22422，输出already-completing，未再写控制器。安装unit和drop-in后daemon-reload，systemd-analyze verify通过；Kodi Requires/After均包含新服务。当前尚未启动此service，也尚未重启验收，用户画面未因此更改。

验收：用户方便时软重启，不按遥控器；记录新boot、oneshot在Kodi之前的日志、OSD完成持续增长、菜单是否自行出现及时间。不能以服务success替代用户看到正常菜单。

## 开关、日志与回退

- 禁用开机补偿：`touch /storage/.config/e900-osd-rdma.disable`，下次启动跳过，便于保留原始故障；删除该文件重新启用。
- 诊断wait1启动也会跳过，不抢先写硬件。
- 每次日志：`/storage/e900-boot-speed/boot-rdma/<boot-id>.json`，同时进入systemd journal；记录先创建，再尝试硬件写入。
- 完全撤销：删除Kodi的30-e900-osd-rdma.conf、该service与脚本，daemon-reload。原build294内核/SYSTEM、TF配置未改；原诊断引导仍在/flash/e900-boot-diagnostic。
- 上一轮屏保临时关闭、网络等待开关保留，不在本轮叠加新亮度/分辨率/颜色变化。
