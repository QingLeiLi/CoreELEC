# E900V21C USB 首轮板级描述

> 当前黑屏排查入口：[线索、验证顺序与结果台账](VD1-VPP-CONVERGENCE.md)。下方早期计划及状态以该台账为准，不直接沿历史候选重新试验。

适用待测板：创维 E900V21C / 5800-2ATA411，GXLX2（CPU ID 0x2a）、1GB DDR3L、8GB eMMC。目标是使用现有 Android 引导程序从外置 USB 启动 CoreELEC 21.3 NG；已用等价 DT 修改启动并验证 MP2 GPU、固定 framebuffer、USB 根系统与有线网；最新整套源码仍待重新 ARM 构建。当前状态见 [正常启动记录](NORMAL-USB-BOOT.md)，下方首轮诊断为历史记录。

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
| eMMC / SD / GPIO 外设 | 仍禁用；不能安装到 eMMC |
| SDIO / Wi-Fi / 蓝牙 | 已接入 UWE5621 驱动、固件及 P291 板级配置，待 ARM 构建和实机验收，见[无线适配](UWE5621-WIRELESS-20261128.md) |

`validate-board.py` 检查编译后的 DTB 属性和上述保留区的相互独立性。它不能验证实机总线时序、PHY 电源、HDMI PLL、显示、声音或视频解码。

## USB 启动入口

当前镜像使用 `e900-usb-image.src`，打包为三个入口 `aml_autoscript`、`s905_autoscript`、`cfgload`。以 `booti` 启动原始 ARM64 `e900-Image`（0x11000000）、原 CE initramfs 包装的 `e900-uInitrd`（0x15000000）和 `dtb.img`（0x18000000）。DTB 不再覆盖旧 Android 的 0x01000000 地址；旧 `bootm` 脚本仅保留为历史材料。

脚本不保存环境、不写 eMMC，也不执行探针证据写盘；加载失败则返回原 Android 启动回退。镜像准备只操作普通 `.img` 文件，核对 ARM64 头与地址范围、原 CPIO `/init`、legacy initrd CRC、全部 FAT 文件回读、SYSTEM/build 哈希和实际媒体模块清单。元数据记录本次 run/attempt；失败或旧任务产物不标记为本次成功。

当前实机正常启动使用先前构建加已验证的二进制 DI 守卫/MP2 DT；未来源码镜像采用同样的加载布局，但仍需完整 ARM 构建和实机回归。

首轮使用有线网络和已确认规格的独立供电；暂不执行系统更新、BL301 注入或 eMMC 安装。测试顺序为能否进入内核、USB 根文件系统、有线 SSH、HDMI/Kodi、音频，最后再验证解码微码及各格式硬解。不得以编译成功推断这些功能已可用。

## 首轮本地验证记录（历史）

- 用固定内核版本自带 DTC 1.4.5 编译板级 DTS 通过。
- DTB 大小 46328 字节，SHA-256：`3601a010bb14a506ad9a8e8dcc78cc716fa3549b87ec179ed317c4e3b6679af3`。
- 属性检查通过；云端 DTC 的 phandle/布局可能不同，应以云端实际校验结果及其哈希为准。
- 真实 mtools/mkimage 已通过合成系统文件的 FAT 打包/回读测试；任务 `43886158436` 已完成完整 SYSTEM/Kodi 镜像构建与独立 FAT 回读验证，实机启动仍待执行。

云端实际镜像的 DTB 为 56995 字节，SHA-256 `a6d547b1f883a42ce0fdab84946b18d01a7915b8e2cff4f2b1c8f371907708fd`；属性检查通过，且与镜像 FAT 根目录 `dtb.img` 的独立回读结果一致。

## 首轮实机反馈与 booti 诊断包

首个 USB 镜像在独立供电下出现安卓标、黑屏、再次安卓标，周期不足 5 秒；移除 U 盘后 Android 正常启动。这只定位到与 USB 启动有关，尚未证明是 bootm 容器处理、早期内核 panic、硬件看门狗或其他复位原因。

本地已检查先前能启动的 Armbian 镜像：`s905_autoscript` 使用 `booti`，加载内核到 0x11000000、initrd 到 0x15000000、DTB 到 0x01000000。其 uInitrd 是 legacy AArch64/Linux/gzip ramdisk。当前默认 CE 脚本则使用 Android 容器与 bootm。

`e900-usb-booti.src` 是独立的免重编译诊断入口，不改变默认镜像脚本。`scripts/make-booti-test-kit.py <export/decoder> <新输出目录> --mkimage <宿主mkimage>` 从已校验的同一构建提取原始 ARM64 Image 和 Android 容器中的 CPIO，重新打包相同 CPIO 为 gzip legacy ARM64 initrd，复用原 DTB，沿用上述 Armbian 加载地址。额外的 `panic=0` 关闭软件 panic 定时重启，不能保证阻止硬件 watchdog 复位。

解压诊断 ZIP，将根目录六个文件 `e900-Image`、`e900-uInitrd`、`dtb.img`、`aml_autoscript`、`s905_autoscript`、`cfgload` 覆盖到已有 COREELEC FAT 分区。保留 SYSTEM、kernel.img 和 STORAGE；不写 eMMC，不改保存的启动环境。回退时将 `rollback/` 中三个脚本复制回 FAT 根目录。

已验证 legacy header CRC、ramdisk 解压与原 CPIO 完全一致、源内核/DTB 哈希，以及六个文件在真实镜像副本中的 FAT 写入/回读。此验证不能代替实机启动。记录见 `tests/booti-kit-43886158436.json`。

后续实测：booti 诊断入口仍约 5 秒复位，第二次安卓标出现后 U 盘不再闪烁；用户报告 SoC 异常烫手，测试时未安装散热片。当前暂停 CE 上电测试，先恢复原散热结构并建立 Android 温度基线。不能由此认定是过压、热关机、看门狗或单纯加载地址错误；切换 booti 并未验证成功。

## 不接串口的引导器探针

经 Android root ADB 只读核对，实际保存的 `bootcmd` 为 `run start_autoscript; run storeboot`，USB 分支遍历设备 0..3，从 0x01020000 执行 `s905_autoscript`。Android 的 ramoops 模块虽存在，但 mem_address/mem_size 均为 0，工作 Android DTB 也未定义 ramoops 保留区；当前 Android dmesg 无法代替上一次 CE 早期日志。

`e900-usb-probe.src` 是仅运行引导器的第一阶段探针，**不调用任何 CE 内核**。它在包含 `E9INPUT.TXT` 的 USB FAT 分区尝试写出相同内容的 `E9PROBE.TXT`，等待 12 秒后返回原有启动命令。仅使用普通 RAM 缓冲，不访问 MMIO、不写 eMMC、不保存启动环境。归档由 `scripts/make-usb-probe.py <新输出目录> --mkimage <宿主mkimage>` 生成，marker 包含本次唯一 nonce。

将四个文件 `E9INPUT.TXT`、`aml_autoscript`、`s905_autoscript`、`cfgload` 放入现有 COREELEC 根目录并覆盖三个脚本。先删除旧 E9PROBE.TXT（如存在）。预期返回 Android，随后核对 E9PROBE.TXT 是否与 E9INPUT.TXT 完全一致。若有该输出，证明该脚本执行且该 bootloader 能写 FAT；若没有，不能仅凭缺失文件区分脚本未执行和 fatwrite 不支持。若此无内核探针也约 5 秒复位，应先检查引导器阶段，不将复位归因于 CE 内核。

探针的 legacy script CRC、四个文件在 CE 镜像副本中的 FAT 写入/回读已验证。实际 fatwrite 能力与引导结果仍待实机反馈；确认可写后，再增加分阶段检查点或复位后的 RAM 日志转存。
