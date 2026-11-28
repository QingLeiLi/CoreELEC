# E900 引导链与启动耗时研究

2026-11-28；现机build294，boot `787ad4a9-eb6d-4d60-a74b-7817315d77d7`。本轮只读，没有重启、修改启动项/环境/寄存器、写eMMC或打断当前构建。

## 实际路径与证据边界

ROM/DDR → eMMC中的厂商U-Boot → start_autoscript → U盘s905_autoscript → fatload原始ARM64 Image、CE initrd、DTB → booti → Linux → initramfs/platform_init → 检查与挂载FLASH/SYSTEM/STORAGE → load_splash → switch_root/systemd → OSD CH3开机补偿 → Kodi。

Android根系统不是这条成功路径的中转。Android logo是厂商引导画面，可被Linux继承，不能把它消失的时刻当作Linux入口。CoreELEC logo也不能仅凭外观断言来自initramfs还是Kodi；当前Kodi日志配置为`splash=false`，initramfs日志确有load_splash，但实际可见时间仍需目视/视频对应。

历史Android只读记录确认`bootcmd=run start_autoscript; run storeboot`，`start_usb_autoscript`遍历USB设备0..3并从0x01020000执行s905_autoscript。来自`coreelec-audit/usb-probe-01-observation.json`。旧原厂备份的`bootcmd=run storeboot`、bootdelay1及preboot内容属于更早固件，不能直接作为当前U-Boot环境。

现机eMMC控制器禁用，只有用户插入的SD卡mmcblk0；没有/dev/env或/dev/nand_env，fw_printenv默认配置不能用于当前设备。没有尝试拿SD卡读取/写入引导环境，也没为了取环境重启到Android。

实际USB脚本从/flash只读解析，选择Image294/uInitrd294/dtb294及SYSTEM294；内容与源码正式脚本同构，仅文件名不同。脚本无sleep、无saveenv；USB start后串行读三个文件再booti。内核29,073,416字节，initrd3,897,701字节；尚无U-Boot单项加载时间。三份入口脚本是兼容不同调用者的副本，不表示一次成功启动会执行三次。

## 同一次启动时间线

原始记录：[current-boot.txt](evidence/boot-chain-20261128/current-boot.txt)。内核时间起点为Linux入口，不含ROM/DDR/U-Boot；systemd critical-chain的@时间以用户空间起点计，不与内核时间直接混用。

| Linux起算时间 | 事件 | 结论/边界 |
|---|---|---|
| 1.331s | media固定寄存器初始化完成 | 自动初始化已生效，不代表OSD完成链有效 |
| 1.337s | Freeing unused kernel memory | 进入早期用户空间附近；不是精确/init入口日志 |
| 1.644～2.809s | USB枚举、sda发现 | Linux会重新枚举USB，不能等同U-Boot读取速度 |
| 2.412/3.436s | fb0/fb1操作释放 | platform_init阶段显示相关操作 |
| 4.460/5.484s | platform_init启用fb0/关闭fb1 | 两条日志间1.024s |
| 6.518s | init加载模块开始 | 相对1.337s有约5.18s，尚无逐命令计时 |
| 6.525～7.532s | 加载fbcon到控制台切换 | 约1.01s，不能仅凭间隔归因于磁盘 |
| 7.560～7.944s | FLASH/STORAGE fsck | 两分区clean，约0.384s，不值得先禁用fsck |
| 7.944～8.154s | 挂载FAT/SYSTEM/STORAGE | 完成后才load_splash |
| 8.154s | load_splash日志 | 仅表示调用，不证明显示器此刻看见logo |
| 8.668s | systemd-analyze用户空间基点 | 其所谓kernel时间包含前面的initramfs工作 |
| 9.499～12.650s | systemd-hwdb-update | 同boot精确计时3.150385s，在关键链上 |
| 15.836～17.444s | OSD补偿service | 原采样确认CH3触发丢失；恢复后完成计数持续增长 |
| 17.477s | Kodi服务开始 | 不等于菜单第一帧 |
| 17.569s | kodi.target到达 | 不是准确上电到画面时间 |

Kodi日志从Starting Kodi到initialize done约4.494s；日志使用墙钟且开机NTP跳时，不能拿它与U-Boot时间拼接成精确总耗时。没有用服务Started或图标出现替代菜单就绪。

## 第一条可验证的新线索：早期OSD等待

源码`projects/Amlogic-ce/devices/Amlogic-ng/initramfs/platform_init`在挂载前执行fbset、free_scale、blank等显示操作。内核`osd_hw.c:osd_wait_vsync_hw_viu1()`在正常显示模式下等待`osd_rdma_vpp0_done_wq`，超时1000ms；`osd_enable_hw()`等会调用它。`osd_rdma.c:osd_rdma_irq()`经`osd_update_vsync_hit()`唤醒该队列。

同boot已独立证明补偿前OSD完成数0、CH3触发缺失，直到17秒附近才恢复。platform_init的多处约1秒间隔与等待超时吻合。因此“现有晚期补偿恢复菜单，却仍让早期framebuffer操作逐次超时”是有源码/现场依据的候选，而非已经量化的全部根因。

下一项对照：保留所有显示语义，在/init入口、platform_init入口/出口及每个fbset/free_scale/blank前后记录/proc/uptime到kmsg；在OSD等待入口/返回记录独立完成计数、耗时和timeout返回值。仅记录启动有限次，不能开启长期高频日志。判据是同一boot具体调用等待约1秒且无完成；若不成立，按实际最慢调用调查。不能通过把timeout改小“修好”，也不能直接把依赖完整Python/SYSTEM的晚期脚本挪进initramfs。

若确认，根修方向是在codec bus ready后由RDMA自身重放丢失的有效通道配置，保留状态/锁/生命周期，而非新增启动期任意寄存器写。必须核对OSD表地址已准备、通道已注册、没有活动播放、回调锁顺序；现有晚期补偿保留兜底，新内核验证健康时它应零写跳过。该修正尚未实现，不加入用户当前构建。

## 第二项：避免每次重建hwdb

用户同意后已接入源码，详见[hwdb预生成与待验边界](HWDB-PREBUILD-20261128.md)。下述内容保留最初候选依据。

现机/run/hwdb.bin为12,297,835字节；SYSTEM内/usr/lib/udev/hwdb.bin不存在。CE固定源码`packages/sysutils/systemd/patches/systemd-0002-move-hwdb.bin-to-run.patch`将默认生成/读取位置改到/run，因此每次启动重建，实测3.15秒。

低风险候选是在镜像组装时生成匹配最终hwdb.d的/usr/lib/udev/hwdb.bin，保留/etc本地覆盖和数据库重建逻辑。需要验证交叉构建的生成工具/格式、hwdb内容与用户覆盖优先级；不能只mask服务，否则可能失去键盘/遥控等硬件规则。预计能移出这3.15秒计算，但整体节省受其它并行服务限制，不能承诺整机正好快3.15秒。新无线镜像规则也必须纳入生成，不能复制build294旧库覆盖。

## U-Boot阶段的测量缺口

早期网络console尚未运行，Linux dmesg只从Linux入口开始，现有netconsole不能提供ROM/DDR/U-Boot日志。厂商U-Boot是否支持gettime/time/timer/netconsole未确认，不能直接给依赖这些命令的脚本。

需要从当前固件的U-Boot二进制或Android只读环境确定完整preboot/start_autoscript、可用计时命令；之后才能制作只放U盘、失败回退Android的一次性计时入口。若没有计时命令，先录一次从上电到菜单的视频并对齐Linux标记，仅获阶段边界，不凭logo猜耗时。暂不改bootdelay/preboot、不绕过DDR、不刷U-Boot或eMMC。

## 执行顺序与当前构建

1. 先完成用户已启动的新镜像构建，按原验收计划验证显示/无线；本研究不改变其输入。
2. 下轮可先用离线派生initrd加入早期逐调用计时，无需重编内核；涉及重启/画面观察时先取得用户回复。纯计时镜像不混入正式刷机材料。
3. 明确1秒等待来源后再做早期RDMA恢复；hwdb预生成独立对照，不与显示修正同时改变，以便归因。
4. 等有U-Boot计时数据，再决定USB载入/扫描是否值得优化。没有改任何固件或现机配置。
