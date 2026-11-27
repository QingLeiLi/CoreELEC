# FTP安装终端、开启ADB与断联修复

## 从电视界面取得本机root终端

成功入口是固件内置“小白文件管理器”的FTP服务器；当时选择“客人”，显示`ftp://192.168.31.59:2121`。Mac通过FTP把`Term-1.0.70.apk`传入盒子，再在电视端文件管理器找到APK并安装，进入Android Terminal Emulator（包名`jackpal.androidterm`）。历史进程日志确认该终端实际运行过。本地APK位于`IPTV/CoreELEC-E900V21C/Term-1.0.70.apk`，哈希见assets.json。

可复用的Mac上传方式（用新盒子实际IP；FTP目录由文件管理器映射决定）：

```sh
BOX=192.168.31.59
curl --user 'anonymous:' "ftp://$BOX:2121/"
curl --user 'anonymous:' -T /实际路径/Term-1.0.70.apk "ftp://$BOX:2121/Term-1.0.70.apk"
```

先确认FTP根目录对应电视上的哪个共享目录，再在电视文件管理器打开APK安装；不要假设FTP `/` 等于Android文件系统 `/`。这是复用命令示例，不是保留下来的原始上传命令。若需允许未知来源，仅为本次APK安装开启。遥控映射不顺时本机已验证USB键盘可用。

## 设备端启用/恢复ADB

在**电视上的本机终端**执行，先运行`su`，接受超级用户授权，`id`应为uid=0。下列是依据恢复记录整理的操作单，最初逐条键入顺序没有完整日志：

```sh
su
id
setprop persist.adb.tcp.port 5555
setprop service.adb.tcp.port 5555
settings put global adb_enabled 1
stop adbd
start adbd
getprop init.svc.adbd
getprop service.adb.tcp.port
```

成功记录同时确认`persist.adb.tcp.port=5555`、`service.adb.tcp.port=5555`、`adb_enabled=1`、USB配置`mtp,adb`。如果该固件USB ADB配置缺失，可在本机root终端设置`setprop persist.sys.usb.config mtp,adb`；它可能触发init重新配置USB和重启adbd，等服务稳定后再连，不能循环重复设置。无需开心助手。

Mac连接与验收：

```sh
BOX=192.168.31.59
adb disconnect "$BOX:5555"
adb connect "$BOX:5555"
adb devices -l
adb -s "$BOX:5555" shell id
adb -s "$BOX:5555" shell getprop ro.build.version.release
adb -s "$BOX:5555" shell cat /proc/device-tree/amlogic-dt-id
```

本机成功输出为`device product:p201_iptv model:E900V22E device:p201_iptv`，`uid=0(root)`，版本4.4.2、DT `gxlx2_p291_1g`。只出现“connected”或TCP端口可达不算验收，必须能执行shell。

## 断联恢复的已证实部分

2026-11-17记录：**设备端root设置属性并重启adbd后，连接恢复**。仅重连Mac端不能替代这个动作；先由电视本机终端执行上面命令，再Mac连接。`nc -vz -G 3 "$BOX" 5555`只测TCP监听，不能测ADB协议握手。

日志确认`com.shafa.market`以普通应用UID10018尝试`setprop/start adbd`被init拒绝，因此沙发管家不能可靠地替代root终端维护ADB。用户随后要求卸载，工程中保存过卸载前APK；后续新机不依赖它。若要卸载，先确认终端root和ADB均已可用，再核对包名执行`adb shell pm uninstall --user 0 com.shafa.market`；本条是复用操作，原卸载完整命令未留档。

这里能确认“恢复方法有效”和“普通应用缺权限”，**不能确认adbd内部最初断联的唯一原因**；不将原因写成安全启动、MAC密钥或新ADB客户端必不兼容。调查摘要见本目录evidence中的两份JSON。

## 持久性验收

设置persist端口后做一次Android正常重启，再执行shell验收。不要把旧原厂备份内的`ADB_AUTOSTART_CONFIG.md`直接当YYF底包已完成配置：它记录2026-05-04给原厂系统写build.prop与init.d的操作，末尾注明重启验证待做，而且init.d是否执行取决于ROM。本轮YYF没有新增init.d脚本的可靠留档。以新机重启后实际服务为准，不盲目叠加开机脚本。

网络root ADB与客人FTP只在可信局域网使用；安装完成后关闭FTP。文档不保存或分发本机ADB私钥、账户、运营商配置。
