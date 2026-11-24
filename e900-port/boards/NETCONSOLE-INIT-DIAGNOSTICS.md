# E900 初始化网络日志诊断

部署前先看[artifact结构与手动U盘部署](ARTIFACTS-AND-MANUAL-USB-DEPLOY.md)，包含完整写盘、离线替换及工具上传步骤。

2026-11-23：源码及宿主检查完成，ARM构建、诊断等待模式启动和真实UDP/netpoll收包仍待验证。本轮未操作设备。

## 本次构建包含什么

* [0020补丁](../patches/linux/0020-gxlx2-netpoll-no-sleep.patch)：仅GXLX2的stmmac_poll_controller改用disable_irq_nosync，移除过去netconsole试验中观察到的原子上下文IRQ同步等待。保留disable→poll→enable配对；不声称整个netpoll路径已实机证明安全。
* [0019补丁](../patches/linux/0019-gxlx2-deferred-video-register-init.patch)：增加`amvideo.gxlx2_hw_init_wait=1`。等待模式下，回调就绪也不执行新增的固定寄存器配置，先让SSH/网卡起来。不是延后整个video_init，也不等待TFTP或DHCP来驱动内核初始化。
* 新准备的USB-TEST镜像默认带等待参数和`loglevel=7`。配置保持原有`CONFIG_NETCONSOLE=m`及`CONFIG_NETPOLL=y`，无需为早期网络另改内核配置。内核默认自动完成模式仍保留，但诊断镜像明确选择等待模式。
* 增加Mac接收脚本、盒子端配置脚本及显式释放脚本；构建额外导出netconsole.ko作为模块检查/诊断备用。正常使用应优先加载配套SYSTEM中的模块。

## 构建选择

当前本地分支`fix/gxlx2-late-video-init`的修改需要提交、推送后才能被Actions使用。本轮没有自动推送或触发构建。

选择`profile=decoder`、`target=image`；无需开启source_trace，vdin_capture不是本次网络日志或初始化修复的必需条件。必须部署该次配套Image/SYSTEM/DTB/initrd。复用已有U盘自定义启动脚本时，也要显式加入`amvideo.gxlx2_hw_init_wait=1`与`loglevel=7`，不能沿用build278的自动配置脚本。

## 先接收，再释放；同一构建无需再编译

Mac运行：

```sh
python3 e900-port/scripts/receive-netconsole.py --output /tmp/e900-netconsole.log
```

盒子需有线接入同一局域网。获取Mac在该局域网的IP和MAC地址，把三个脚本中的arm-netconsole.py、release-video-init.sh上传至盒子的`/storage/e900-netconsole/`。接收工具只处理UDP日志，不会执行包内容，每包写入并fsync到Mac磁盘。

盒子执行（将示例占位符替换为实际值）：

```sh
python3 /storage/e900-netconsole/arm-netconsole.py \
  --receiver-ip MAC_IP --receiver-mac MAC_ADDRESS
```

该脚本检查等待模式、pending状态、有线carrier和路由，设置明确的目标MAC，加载netconsole模块并发送`E900_NETCONSOLE_READY`。它**不会释放寄存器配置**。已加载的netconsole不会被自动卸载或换目标。

只有Mac确认实际收到上述标记后，再执行：

```sh
sh /storage/e900-netconsole/release-video-init.sh
```

释放脚本停止Kodi、确认无解码器，再写入root专用`gxlx2_hw_init_run=1`。内核还会拒绝已有显示视频帧、尚未完成probe、非等待模式或已尝试执行的请求。释放成功且读回状态为2后恢复Kodi；失败时保留错误状态，不反复执行，也不自动恢复播放。

Mac日志应出现RELEASE_BEGIN、13步的读写begin/end及RELEASE_OK。若中途硬卡，已经收到的日志保留在Mac；若没有收到READY，不继续操作。

## 观测边界

netconsole是单向UDP日志，不能当成远程交互串口。它依赖网卡/netpoll及仍可执行的CPU，不保证完全锁死时最后一个包能送出。最后收到的begin只是定位线索，UDP丢包或未及时发送也可能造成end缺失。

本方案通过暂停待测配置来避开“网卡15秒才起，初始化1秒就执行”的时序冲突；**不是捕获所有早期内核故障**。若在等待模式到达网卡之前就卡住，netconsole仍无能为力。现有7次其他调用者早期丢写不因加入网络日志而自动修复。

宿主检查覆盖真实netpoll函数的CPU分支及IRQ配对、手动释放门控、重复执行和活动帧拒绝；真实网络日志链路还必须先用READY标记校准。参考[内核netconsole文档](https://docs.kernel.org/networking/netconsole.html)及旧[试验51记录](DISPLAY-PIPELINE.md)。
