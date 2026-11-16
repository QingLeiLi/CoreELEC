# E900V21C / GXLX2 CoreELEC 开发工作区

目标：基于 CoreELEC 21.3 NG 的厂商 4.9 栈，开发外置 USB 启动的播放器。

当前是第一批源码补丁和构建工具，不是已经适配完成的刷机包。未编译完整内核，未实机验证；完整板级 DTB 尚未接入。工作区脚本不连接盒子、不写入磁盘设备，也不执行 eMMC 安装。

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
| `patches/linux/0001-gxlx2-identity.patch` | 内核增加真实 CPU ID 0x2a 及独立判断函数 | 本地 C 头文件测试通过，内核未编译 |
| `patches/media/0001-gxlx2-identity-and-firmware-trace.patch` | 补解码器 DT 匹配、型号名称、实际取用微码的日志 | 应用检查通过，模块未编译 |
| `patches/linux/0002-gxlx2-opt-in-hdmi-transport.patch` | 用独立 DT 属性启用 DWC/TOP 直接访问，保留 GXL PHY 配置 | 本地映射/分流测试通过，硬件未验证 |
| `patches/media/0002-gxlx2-experimental-clock-registration.patch` | 将 GXLX2 加入现有共享时钟注册列表 | 仅补入口；能力分支尚未完整审查 |

补丁固定基线见 `pins.json`。`scripts/generate-patches.py` 从相邻 `coreelec-audit` 中经过校验的原文件生成补丁；不会修改原文件。

HDMI 补丁没有增加或重排原有 `chip_type` 枚举。它要求真实 CPU 为 GXLX2，HDMI 的 `ic_type` 保留为 3（GXL PHY 配置），另用 `amlogic,gxlx2-direct-hdmi` 选择直接访问。其他芯片及未启用该属性的路径继续使用现有配置。

**仍需处理：**完整板级 DTS、HDMI TOP/DWC 初始化差异、HPD/DDC、PHY/PLL 的芯片特例、Mali/fbdev、音频，以及解码电源/时钟中依据 `>= G12A` 作出的能力判断。HDCP/安全寄存器访问路径也未完成核对；当前补丁只处理基础非安全寄存器传输，不能据此宣称 HDCP 可用。

`boards/gxlx2-p291-hdmi-fragment.dtsi` 只是片段，不是板级 DTB，构建脚本不会自动安装它。这样可以先验证编译，再在核对本板引脚和供电后集成板级描述。

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
| `decoder` | hdmi + 实验性解码时钟注册 |

每个 profile 使用独立源码及编译目录，共用下载和 ccache 目录；同一卷禁止并发构建。修改补丁后，本地默认拒绝直接复用已有编译树；CI 显式开启受控增量更新，只清理受影响的内核/媒体包，保留兼容工具链。详见 [缓存说明](CLOUD.md#增量缓存)。

可以用 `E900_JOBS=2` 降低单包编译并行度；`E900_THREADS` 默认 1，避免同时编译多个大包。不同测试卷可以用 `E900_BUILD_VOLUME` 指定，不能把它当作清理旧卷的命令。

`image` 入口可生成通用镜像，但目前没有本板完整 DTB，生成通用镜像也不等于本板适配成功。当前不应拿它试刷。

导出目录在 `output/<profile>/`，包含编译产物、日志和 `build-metadata.json`；元数据记录最后一次动作的退出状态，失败时目录内可能留有较早的产物，应以日志及状态为准。

## 已运行的本地检查

```sh
python3 tests/check-local.py
python3 tests/check-build-cache.py
```

检查了四个补丁按顺序应用、真实 CPU 头文件的 C 测试、从补丁后源码提取的 HDMI 映射/分流函数的 C 测试，以及补丁安装器的版本及本地修改保护。测试中的 MMIO 使用模拟函数，只验证代码分流，不验证硬件地址是否能实际工作。

缓存检查覆盖宿主/profile/路径隔离、相同状态重用、补丁变化后的选择性清理、失败清理的重试，以及从实际 CoreELEC 目录层级导出内核与模块。GitHub 远端缓存上传/恢复仍需工作流运行验证。

完整 ARM64 内核、媒体模块、Docker 镜像和盒子启动测试仍待执行。
