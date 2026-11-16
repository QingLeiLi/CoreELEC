# E900V21C USB 首轮板级描述

适用待测板：创维 E900V21C / 5800-2ATA411，GXLX2（CPU ID 0x2a）、1GB DDR3L、8GB eMMC。目标是使用现有 Android 引导程序从外置 USB 启动 CoreELEC 21.3 NG；此 DTS 尚未实机验证。

## 配置依据

同版 CE 4.9 的 `coreelec-gxl/gxl_p212_1g.dts` 提供厂商媒体/显示节点。本板差异依据原备份及当前可启动 Android 的 `gxlx2_p291_1g` 设备树逐项核对。没有把 Android 二进制 DTB 放入源码或 artifact。

| 项目 | 首轮配置及理由 |
|---|---|
| 内存 | 1GB，沿用 P291 的 usable-memory 范围 |
| 安全固件区 | 固定保留 0x10000000 起的 2MiB，防止覆盖旧引导固件的安全区 |
| CE secmon 缓冲池 | 保留 CE 独立的 4MiB CMA；驱动需要从中分配约 3MiB，不能直接用上面的 2MiB no-map 区代替 |
| framebuffer | 0x3dc00000 起的 36MiB，覆盖旧固件 framebuffer 区 |
| USB | 两个 USB2 端口，无 USB3 物理端口 |
| 有线网 | 内部 RMII PHY；不使用 P212 的外部 PHY 复位与 RGMII 引脚 |
| HDMI | 保留 GXL PHY 配置 `ic_type=3`，独立启用 GXLX2 直接寄存器访问候选补丁 |
| Mali 用户库 | 保留大小写敏感的 `amlogic, Gxl` 兼容项供 CE 选择 Mali-450 库，真实 CPU 仍标识为 GXLX2 |
| eMMC / SD / SDIO / 无线 / GPIO 外设 | 首轮禁用，避免未核实的引脚、电源与调谐配置；不能安装到 eMMC |

`validate-board.py` 检查编译后的 DTB 属性和上述保留区的相互独立性。它不能验证实机总线时序、PHY 电源、HDMI PLL、显示、声音或视频解码。

## USB 启动入口

`e900-usb-autoscript.src` 被打包为传统 U-Boot script，同时放入 FAT 根目录的 `aml_autoscript`、`s905_autoscript` 和 `cfgload`，兼容现有多重启动入口。USB 内核容器加载到 0x20000000，DTB 位于 0x01000000；保留 CE 现有 Android boot image 格式，不重新打包其内部加载地址。

脚本只改变内存变量，不执行 `saveenv`、`defenv` 或存储写入命令。内核命令行启用 `ssh`，便于 HDMI 黑屏时获取日志。仍需实机验证旧引导程序能否执行这一入口并传递 DTB；已有 Armbian USB 启动成功不能代替这一步。

镜像准备脚本操作构建目录中的普通 `.img` 文件，不使用磁盘设备或挂载权限。它会回读 DTB 和三个入口脚本，并核对内核与本次编译一致、SYSTEM 为 SquashFS，输出 SHA-256 和本次 run/attempt 的来源记录。旧任务留下的镜像不作为本次成功产物导出。

首轮使用有线网络和已确认规格的独立供电；暂不执行系统更新、BL301 注入或 eMMC 安装。测试顺序为能否进入内核、USB 根文件系统、有线 SSH、HDMI/Kodi、音频，最后再验证解码微码及各格式硬解。不得以编译成功推断这些功能已可用。

## 本地验证记录

- 用固定内核版本自带 DTC 1.4.5 编译板级 DTS 通过。
- DTB 大小 46328 字节，SHA-256：`3601a010bb14a506ad9a8e8dcc78cc716fa3549b87ec179ed317c4e3b6679af3`。
- 属性检查通过；云端 DTC 的 phandle/布局可能不同，应以云端实际校验结果及其哈希为准。
- 真实 mtools/mkimage 已通过合成系统文件的 FAT 打包/回读测试；完整 SYSTEM/Kodi 镜像构建与实机启动仍待下一轮执行。
