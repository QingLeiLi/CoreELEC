# E900V21C / GXLX2 CoreELEC 开发工作区

手动部署入口：[构建产物结构、U盘整盘写入与保留分区更新](boards/ARTIFACTS-AND-MANUAL-USB-DEPLOY.md)。包含当前网络诊断等待模式、脚本上传和回退步骤。

2026-11-23网络诊断：[netconsole与初始化等待模式](boards/NETCONSOLE-INIT-DIAGNOSTICS.md)。USB测试镜像先等网络日志校准，再显式执行新增配置；无需第二次编译。

2026-11-23源码更新：[视频寄存器初始化拆分](boards/VIDEO-REGISTER-INIT-FIX-20261123.md)。移除整套晚初始化，新增0019固定寄存器完成路径；宿主检查通过，ARM构建和实机待验证。

**最新接手入口（2026-11-21）：[基线、借鉴来源与播放代码导航](BASELINE-AND-PLAYBACK.md)，[实机阶段收尾](boards/HANDOFF-20261121.md)。** 下文早期构建/待验证描述保留为历史，当前状态以上述两份文档为准；硬解黑屏尚未解决。

目标：基于 CoreELEC 21.3 NG 的厂商 4.9 栈，开发外置 USB 启动的播放器。

当前已通过外置 USB 启动 Linux 4.9.269，物理 HDMI 上的 Kodi 菜单、遥控导航、界面音效和同一 H.264 样片的软件解码已验证。等待GE2D完成并按BGR解读后，已从硬解帧读出完整原尺寸色条；电视硬解视频仍黑屏，尚未通过HDMI播放验证。最新证据、链路边界和初始化时序问题见 [显示链路复盘](boards/DISPLAY-CHAIN-REVIEW.md)；早期 [显示路径诊断](boards/DISPLAY-PIPELINE.md) 和 [POST2记录](boards/POST2-VALIDATION.md) 仅作为过程资料。

任务 `43886158436` 完成了初版完整构建，但 SYSTEM 漏装全部媒体模块；已修正隐藏构建路径过滤问题。最新源码还补齐 MP2/固定 framebuffer、DI 可选时钟、七条媒体总线注册和 VLD DMC 通道。等价运行实验不代表这些源码已完成全量 ARM 编译。镜像打包已切到实测的 `booti` 布局，并检查 SYSTEM 的实际模块清单，详见 [当前启动与验证状态](boards/NORMAL-USB-BOOT.md)。仍是实验性适配，eMMC 保持禁用。

现在优先使用 [GitHub Actions 云编译](CLOUD.md)，无需本地 Docker。下面保留 Docker 入口作为本地备用方案。

## Docker 现在需要准备什么

安装并启动 Docker Desktop，使用 Linux 容器。当前这台 Intel Mac 使用 `linux/amd64`：

```sh
docker pull --platform linux/amd64 ubuntu:22.04
```

这就是需要提前拉取的基础镜像。后续根据本目录 Dockerfile 自动装编译工具，无需另找 Armbian 镜像或 CoreELEC 容器成品。

本 Dockerfile 参考固定版本的 [CoreELEC jammy Dockerfile](https://github.com/CoreELEC/CoreELEC/blob/fc61125e8900ab0c2593a29b615980ed0cd5b939/tools/docker/jammy/Dockerfile)；它使用 Ubuntu 22.04、GCC 12、Go 1.22 等宿主工具。安装软件包仍需联网，首次构建尚未运行。`ubuntu:22.04` 是可更新标签，不是已锁定的镜像 digest；首次成功构建后应记录其 digest 和实际软件包版本。

建议 Docker 分配 4 个 CPU、6–8GB 内存，预留约 100GB 磁盘空间；资源不足可以降低并行度。源码/编译树使用 Docker 命名卷 `e900-coreelec-work`，下载缓存共享，避免在 macOS 的文件系统上编译大小写敏感的源码。

## 已写的补丁

| 文件 | 行为 | 状态 |
|---|---|---|
| `patches/linux/0001-gxlx2-identity.patch` | 内核增加真实 CPU ID 0x2a 及独立判断函数 | 真实 CPU ID 已实机确认；本地及原云端编译通过 |
| `patches/media/0001-gxlx2-identity-and-firmware-trace.patch` | 补解码器 DT 匹配、型号名称、实际取用微码的日志 | 实机日志确认型号及微码选择；原云端模块编译通过 |
| `patches/linux/0002-gxlx2-opt-in-hdmi-transport.patch` | 用独立 DT 属性启用 DWC/TOP 直接访问，保留 GXL PHY 配置 | 本地映射/分流测试及云端内核编译通过，硬件未验证 |
| `patches/media/0002-gxlx2-experimental-clock-registration.patch` | 将 GXLX2 加入现有共享时钟注册列表 | 入口已编译通过；能力分支尚未完整审查 |
| `patches/linux/0003-e900v21c-usb-board.patch` | 注册 E900V21C 1GB USB 实验板级 DTS | MP2/固定 framebuffer 运行实验通过；更新源码已通过 DTB 检查 |
| `patches/linux/0005-gxlx2-optional-di-clock.patch` | 缺失 DI 可选 clkb 时处理 ENOENT | 源码 ARM 构建、启动及无显示器下解码器启动/释放通过；实际视频待验 |
| `patches/linux/0006-gxlx2-direct-media-register-buses.patch` | GXLX2 在晚期初始化注册七条已核对的媒体总线 | 修订源码 ARM 构建及原生晚期注册启动通过，无 blacklist/helper；见 [实机记录](boards/NATIVE-RUN-44441905557.md) |
| `patches/media/0003-gxlx2-vld-dmc-channel.patch` | VLD 启用/停止/复位使用 bit13 | 等价模块实验可正常停止；源码宿主范围测试通过，ARM 构建待做 |
| `patches/linux/0007-gxlx2-post2-matrix-guard.patch` | GXLX2 避免访问当前 VPU 配置不支持的 POST2 矩阵 | 源码 ARM 构建、启动及无显示器解码器启动/释放通过；实际显示待验 |
| `patches/linux/0008-gxlx2-legacy-video-pipeline.patch` | GXLX2 保留旧式视频混合策略与 MIF 表选择 | 源码 ARM 构建及启动通过，运行时 legacy_vpp=1；无 HDMI，黑屏修复仍待验，见 [实机记录](boards/NATIVE-RUN-44441905557.md) |
| `patches/linux/0009-gxlx2-mif-selection-probe.patch` | 默认关闭的启动期 MIF 表对照；保持旧式混合策略 | 宿主分支测试通过，ARM/实机待验；见 [记录](boards/HARDWARE-VIDEO-MIF-PROBE.md) |
| `patches/linux/0010-gxlx2-late-video-init-probe.patch` | GXLX2 默认在媒体总线就绪后再初始化视频驱动 | 修复 video_hw_init 在总线未注册时的 9 次丢写；默认开启，可用 `amvideo.gxlx2_late_video_init=0` 关闭对比；ARM 构建及实机播放待验 |

补丁固定基线见 `pins.json`。`scripts/generate-patches.py` 从相邻 `coreelec-audit` 中经过校验的原文件生成补丁；不会修改原文件。

HDMI 补丁没有增加或重排原有 `chip_type` 枚举。它要求真实 CPU 为 GXLX2，HDMI 的 `ic_type` 保留为 3（GXL PHY 配置），另用 `amlogic,gxlx2-direct-hdmi` 选择直接访问。其他芯片及未启用该属性的路径继续使用现有配置。

**仍需处理：**持续解码、HDMI TOP/DWC 初始化、HPD/DDC/VSYNC、PHY/PLL、音频及 parser/demux/AIU 寄存器偏移，以及媒体驱动依据 `>= G12A` 作出的其他能力判断。HDCP/安全寄存器访问路径也未完成核对；当前补丁只处理基础非安全寄存器传输，不能据此宣称 HDCP 可用。

`decoder` 配置现包含 `boards/gxlx2_p291_1g_e900v21c.dts` 和对应 Makefile 补丁。它继承同版 CE 的 P212 1GB 定义，覆盖本板 CPU、USB、内存保留区、内部 RMII PHY 和 HDMI 访问方式；首轮禁用 eMMC、SD、SDIO、无线及未核对的 GPIO 外设。详细依据和限制见 [板级说明](boards/README.md)。旧 HDMI 片段仅保留作为参考。

任务 `43886158436` 已用 `profile=decoder`、`target=image` 成功生成完整 SYSTEM/Kodi 和 `*-E900V21C-USB-TEST.img.gz`。工作流会替换 USB 启动入口，读回核对 DTB、脚本、内核及 SYSTEM；只有 `build-metadata.json` 的 `usb_image_prepared=true` 才表示本次镜像打包校验成功。这不代表盒子已经启动或硬解可用。

## Docker 好了之后的入口

进入目录：

```sh
cd e900-port
bash scripts/docker.sh build-env
```

先用未修改配置验证工具链和官方内核基线：

```sh
bash scripts/docker.sh prepare baseline
bash scripts/docker.sh linux baseline
```

再编译第一阶段的识别及诊断补丁：

```sh
bash scripts/docker.sh prepare identify
bash scripts/docker.sh linux identify
bash scripts/docker.sh media identify
bash scripts/docker.sh export identify
```

这些命令编译内核/模块，可能需要下载并编译工具链和依赖，耗时取决于网络及机器。现在先准备 Docker 即可，等环境就绪后再按顺序执行和排错。

构建配置：

| profile | 包含内容 |
|---|---|
| `baseline` | 固定官方源码，没有本工作区补丁 |
| `identify` | CPU 识别和固件日志 |
| `hdmi` | identify + 可选 HDMI 寄存器传输 |
| `decoder` | hdmi + E900 USB 板级 DTB + DI/媒体总线/VLD DMC/解码时钟修复 |

每个 profile 使用独立源码及编译目录，共用下载和 ccache 目录；同一卷禁止并发构建。修改补丁后，本地默认拒绝直接复用已有编译树；CI 显式开启受控增量更新，只清理受影响的内核/媒体包，保留兼容工具链。详见 [缓存说明](CLOUD.md#增量缓存)。

可以用 `E900_JOBS=2` 降低单包编译并行度；`E900_THREADS` 默认 1，避免同时编译多个大包。不同测试卷可以用 `E900_BUILD_VOLUME` 指定，不能把它当作清理旧卷的命令。

云端 `decoder/image` 在通用镜像基础上生成本板外置 USB 测试镜像；其他 profile 的通用镜像不导出为测试包。本地 Docker 的原 `image` 入口只执行基础构建，尚未自动执行后处理；需额外运行 `scripts/prepare-usb-image.py <CoreELEC-decoder源码目录>` 和 `scripts/export-artifacts.py <源码目录> decoder image 0`。首测不进行系统更新、BL301 注入或 eMMC 安装。

导出目录在 `output/<profile>/`，包含编译产物、日志和 `build-metadata.json`；元数据记录最后一次动作的退出状态，失败时目录内可能留有较早的产物，应以日志及状态为准。

## 已运行的本地检查

```sh
python3 tests/check-local.py
python3 tests/check-build-cache.py
python3 tests/check-usb-image.py
python3 tests/check-host-policy.py
```

检查了五个补丁按顺序应用、真实 CPU 头文件的 C 测试、从补丁后源码提取的 HDMI 映射/分流函数的 C 测试，以及补丁安装器的版本及本地修改保护。测试中的 MMIO 使用模拟函数，只验证代码分流，不验证硬件地址是否能实际工作。

缓存检查覆盖宿主/profile/路径隔离、相同状态重用、补丁或板级构建选项变化后的选择性清理、失败清理的重试，以及从实际 CoreELEC 目录层级导出内核与模块。GitHub 远端缓存上传/恢复仍需工作流运行验证。

既有版本的 ARM64 内核和媒体模块已完成编译及本板USB启动验证。新增0010后置视频初始化实验默认关闭；0011修正GXLX2抓帧等待时机。两者仅通过宿主检查，完整ARM构建和新驱动硬件验证待执行；硬解HDMI画面仍未通过，eMMC仍保持禁用。

首次通过的 [GitHub Actions 运行](https://github.com/QingLeiLi/CoreELEC/actions/runs/43807610508)，提交 `e92f2c5`：内核版本 4.9.269，28 个模块的 ELF 架构为 AArch64，vermagic 均匹配该内核；HDMI 诊断与固件选择日志字符串已在二进制中找到。此结论不能代替本板运行验证。

可选镜像打包集成检查：

```sh
python3 tests/check-usb-roundtrip.py <本板编译后DTB> <mtools所在目录> <mkimage路径>
```

已使用 GNU mtools 4.0.43 和与 CE 同版本并应用其补丁的 U-Boot mkimage 2016.03，通过真实 FAT 写入/回读、镜像导出及失败重试清理检查。该测试的内核/SYSTEM 是合成占位文件，只验证打包链路；实际 CoreELEC 镜像也已通过独立 FAT 回读校验；内核启动及硬件仍需后续验证。

宿主工具现固定使用通用 x86-64 参数，以支持不同 runner CPU 共享后续缓存；旧 native 构建状态和 ccache 已隔离，首次切换需较大重编译。详见 [宿主 SIGILL 与可移植缓存](CLOUD.md#宿主-sigill-与可移植缓存)。这属于宿主构建策略调整，目标 ARM 指令集配置未变化。

首次完整 USB 镜像的来源、哈希和验证结果见 [构建记录](tests/full-image-build-43886158436.json)。首次上机只写外置 U 盘，按 USB 启动方式测试，使用有线网络；不进行 eMMC 安装、BL301 注入或系统更新。

最新显示验收：软件解码正常；H.264 硬解黑屏、HEVC 绿屏，热插拔 RDMA 恢复未解决。不能将驱动帧计数视为播放通过，详见 [视频排查记录](boards/HARDWARE-VIDEO-MIF-PROBE.md)。

Optional staged-pixel capture experiment: [VDIN capture build and validation limits](boards/VDIN-CAPTURE.md). The `vdin_capture` workflow input is off by default; a full ARM build and on-device downstream capture remain pending.

成对快照、生命周期 hook 和离线对比工具：[基础调试功能](boards/DEBUG-FOUNDATION.md)。

阅读Canvas→VD1/VPP→输出回环的代码与证据：[显示链路分析导航](boards/DISPLAY-CHAIN-ANALYSIS.md)。
