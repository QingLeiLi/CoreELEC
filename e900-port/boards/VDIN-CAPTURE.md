# E900 分阶段像素抓取：实验构建

目标是把已经验证的解码帧输入 A，与显示链路下游的内部回环帧 B 对照。B 使用旧式 VIU/VENC 回环候选路径；具体位于输出矩阵前后仍需硬件校验，不能将它等同于 HDMI 线上最终像素。

目前只有 A 点的 H.264 色条像素证据，B 点尚无有效实拍证据。构建 44682660724（12d76eb）已通过完整 ARM 编译、链接和实机启动。两路 VDIN 探测、格式设置及四帧 CMA 分配已经实机执行；启动服务后失联并重启，实时内核日志最后到达 `vdin_set_hdr fmt:0`。新增旧式矩阵/HDR 保护修复已完成主机测试，尚需重新 ARM 构建和硬件验证。

## 构建

GitHub Actions 手动运行现有 E900 workflow：

- `profile`: `decoder`
- `target`: `image`
- `source_trace`: 不勾选
- `vdin_capture`: 勾选

默认不勾选 `vdin_capture`，仍安装原来的 13 个候选补丁；勾选后安装 18 个，并将 VIN/TVIN、VDIN/VIUIN 及其直接使用的 V4L2 核心/缓冲依赖内置到内核。Linux kernel config 的原始摘要固定核验；取消开关会恢复原文件，遇到本地改动则拒绝覆盖。

切换选项仅使 `linux`、`media_modules-aml` 失效；兼容工具链、下载和编译对象缓存继续复用。完整镜像需要重新打包，单独选择 `media` 不能提供首次部署所需的新内核及全部模块。

新固件运行时仍默认关闭 VDIN：系统启动完成后显式写入 `gxlx2_capture`，再通过标准平台总线 `drivers_probe` 探测两个固定 DT 设备。修改开关本身不操作硬件，避免内置驱动在早期探测时碰到尚未注册的媒体总线。启动、镜像准备与 eMMC 写入策略未因此改变。代码没有自动推送、触发 workflow 或部署到盒子。

## 实现范围

- GXLX2 VDIN1 使用原厂二进制支持的 `0x80` 偏移，采用旧式回环路由与时钟门控；原厂明确针对该 CPU 使用的 `0xd4` 同步配置保留。
- 同时注册 VDIN0 的状态供原有启动/中断逻辑使用；只允许 VDIN1 的普通 VIU1 诊断服务启动，保留内容保护检查。
- VDIN 诊断使用独立工作模式，不向显示 VFM 注册采集帧提供者；完成帧仍进入其私有队列。VDIN 的 RDMA 关闭，显示 RDMA 不受此设置影响。
- 启动前预留 IRQ；时钟、前端和缓冲区准备失败会向 sysfs 调用者返回错误并清理本次资源，避免错误地报告已启动。
- 写入前建立 DMA 映射，只接受所用 Canvas 地址仍有效的直接映射；读取与归还通过该映射同步。没有任意地址读取接口。
- `capture_ready` 拒绝冻结队列、活动/待用目标冲突、非 8 位、压缩/保护内容和不支持的像素布局。最多等完成队列 2 秒。
- 持有完成帧、同步并复制到独立 CPU 内存后，先归还帧、释放设备/前端锁，再写文件；短写、信号、打开失败、fsync/close 失败会传播错误。
- DMA 归还出现不应发生的状态错误时，不把 CPU 所有的帧交回写入队列，并暂停后续采集；该会话需停止/重启检查。

## 首版生命周期限制

停止后的硬件 DMA 排空尚无经验证的栅栏。首版保留成功分配的采集缓冲池直到重启；VDIN 已内置，不能独立卸载。禁止同一次开机重新启动采集，禁用该平台的手动 bind/unbind 属性。一个运行中的会话可重复抓图并切换本地测试视频。

这不是已验证硬件排空的声明，也不覆盖内核其他组件主动移除平台设备。失败分配不会保留缓冲池，其他 CPU 的释放行为保留。采集会话应使用独立输出文件名。

当前 DT 的私有 VDIN1 CMA 池为 20 MiB。首试请求把当前 1080p/720p 输入缩到 640×360 RGB444，降低四帧缓冲区的需求。实际输出格式、步幅、位深和申请结果仍需读取并核对。

## 构建后调试工具

这些命令仅适用于包含诊断接口的新固件。准备阶段现已在硬件运行，完整服务尚未成功启动。

仓库脚本：

- `scripts/e900-start-capture.sh`：核对当前显示模式，显式打开运行时开关并经平台总线探测，要求两个 VDIN 实例成功注册，开始单次 640×360 诊断会话；不改变 HDMI 模式。每个关键操作前将阶段同步落盘至 `/storage/e900-capture/start-phase.txt`；设置 `E900_CAPTURE_PREPARE_ONLY=1` 只探测、设置转换，跳过服务启动。
- `scripts/e900-capture-ready.sh menu`：保存 `/storage/e900-capture/menu.e9cap`。先写 `.partial`，sysfs 成功才发布正式文件；失败清理本次临时文件，不覆盖已有结果。
- `scripts/inspect-vdin-snapshot.py menu.e9cap --out decoded`：验证格式、完整长度和摘要，导出原始像素及 JSON。只有显式指定 `--rgb-order RGB` 或 `BGR` 才生成 PNG；实际通道顺序必须用色条校验。

先抓正常菜单作为回环自身的阳性对照，再抓本地 H.264 色条的“仅视频”和“视频＋菜单”。没有完成帧、接口拒绝或缓冲区错误必须判定为抓图失败，不能解释为视频像素黑。

## 快照格式 v1

80 字节小端头部，后接逐行去除步幅填充的三字节样本。魔数为 `E9VDIN1\0`。

- 10 个 u32：version、header_bytes、width、height、format_convert、active_row_bytes、source_stride、frame_index、bitdepth、flags。
- 4 个 u64：frame_timestamp、sample_jiffies、completion_count、payload_bytes。

`flags=3` 仅表示经过软件完成队列与 DMA 同步步骤，不代表 HDMI 有效。frame_timestamp 是原驱动的帧时间字段；sample_jiffies 与 completion_count 是取样时的计数，不是媒体 PTS 或精确的逐帧跨取点同步编号。format_convert 为本次固定内核的枚举值，不能据此省略字节顺序/颜色空间校准。

## 验证边界

`tests/check-vdin-capture.py` 在固定源码上应用整个补丁包，执行完整快照 copy/save、帧发布、DMA 映射/保留及完整启动服务的主机 C 测试，使用模拟的内核依赖和 ASan/UBSan；另验证真实 C 产生的合成文件与 Python 解析器兼容、PNG 校验、临时文件发布与失败清理，以及构建选项切换/本地文件保护/缓存保留。

这些检查不能替代完整 ARM 构建或硬件完成/缓存验证。新采集代码目前没有 B 点实拍证据，也没有证明修复播放黑屏。

## 模块链接失败修正

初版 `VDIN=m` 在 MODPOST 报告 11 个未定义符号。逐项对应到已有内核代码：IRQ/MM/FD/extcon 核心、VPU、VLOCK 和 TVIN 公共函数都存在定义，但没有导出为模块接口。这份旧驱动应与这些提供者一同内置，而非为所有内部接口新增导出或伪造实现。

VDIN/VIUIN 改为 `y`，Kconfig 为 VDIN 声明 V4L2/DMA 依赖并选择 VB2 DMA-contiguous（隐藏配置不能仅靠写入 `.config` 保持为 `y`）。其直接引用的 MEDIA_SUPPORT、VIDEO_DEV、VIDEO_V4L2、VIDEOBUF2_CORE、VIDEOBUF2_MEMOPS、VIDEOBUF2_DMA_CONTIG 一起设为 `y`，避免内置 VDIN 反向依赖动态模块。运行时探测门仍默认关闭。

安装器识别上一轮失败缓存中精确的 `m` 配置并迁移，同时保留原始摘要和本地改动保护。新增检查覆盖全部 11 个提供者、真实 GNU89 TVAFE 公共函数的跨对象链接、失败缓存迁移以及运行时探测顺序。完整 ARM 链接现已由构建 44682660724 验证通过，尚无有效 B 点实拍证据。

本地还运行了固定 Linux 4.9 的真实 `olddefconfig`（ARCH=arm64，主机只构建 Kconfig 工具），确认 VDIN/VIUIN、直接 V4L2/VB2 依赖及 VPU/VECM/extcon 等 13 项全部保持 `y`。此验证不包含 ARM C/汇编编译或最终链接。

## 构建 44682660724 实机记录（2026-11-20）

35 个导出文件及 18 个补丁摘要一致，原生 FAT 回读确认内核、SYSTEM、DT 和 initrd 配套。新旧固件使用独立文件名，`SYSTEM_IMAGE=SYSTEM212` 已在实机启动命令行确认。完整旧启动分区备份在盒子 `/storage/e900-pre212-backup/flash.tar` 和 Mac `trial-build212/rollback/flash.tar`，SHA256 为 `ca03ac33b37384ae95005f0f54b5aed5527406f44948bd1d879634927c2d0b66`。未写入 eMMC。

新固件 SSH/Kodi 正常，采集参数初始为 N。HDMI HPD=0，内部模式为 1080p60。第一次尝试期间曾失联并重启，但命令没有留下执行标记，原因未确定。用户明确授权重试后，带落盘标记的测试证实两个 probe 及 conversion 返回；记录停在 before-service-start，之后设备重启。再次将准备与服务分离后，准备过程正常结束。

实时 `/dev/kmsg` 日志在 Mac 保存，证明服务经过前端打开、IRQ 准备和 CMA 分配，四帧缓冲池大小 `0x1c8000`，最后输出如下：

```
vdin1 cma alloc 4 buffers ok!
vdin_game_mode_check: flag=0x0, game_mode=0x0 force mode:0x0
vdin_change_matrix1 id:28
vdin_set_hdr fmt:0
```

随后 SSH 失联并再次重启。源码在最后一条日志后会调用 `hdr_set(5, 0x9)`；它是嫌疑入口，日志本身还不能排除后续无日志的寄存器配置。没有完成帧，不能解释成回环黑帧，也没有证明 HDMI 黑屏已修复。

尝试仅通过已有 `rgb_info_enable` 参数选择旧式矩阵对照，发现该参数在 DEBUG_SUPPORT 下，本镜像没有编入；未改变该参数，未继续启动服务。设备已恢复 SSH/Kodi，运行时采集参数为 N，记录的最后启动 ID 为 `335cfdc6-80f1-457c-9ace-8cbd87459051`。

## 旧式矩阵/HDR 修复候选

GXLX2 的 CPU ID 0x2a 满足上游 `cpu_after_eq(G12A)`，使其选择 matrix1 并调用 G12 VDIN HDR 接口。补丁 0012 现为 GXLX2 选择旧式 matrix0，并在调用点和 `vdin_set_hdr` 内保护，其他 CPU 保留原路径。另在 matrix、blackbar、histogram、write-control、input-route、measurement-route 前后增加仅该 CPU 的日志，供下次细分失败位置。

新增测试执行真实上下游 C 函数，在 Dolby 支持开/关两种配置共 6912 个组合中比较非 GXLX2 的调用参数序列，验证一致；GXLX2 默认采集路径使用 matrix0 且没有 HDR 调用。主机测试不证明硬件修复。本轮补丁尚未 ARM 重编译或部署，现有构建缓存可保留兼容工具链，需重建 linux/media_modules 并重打包镜像。

## 构建 44689624531 验证

12e02fb 已部署。旧式矩阵修复后服务正常返回，全部寄存器配置阶段完成，没有再因采集启动重启。脚本已实机修正：逐行扫描值为 1；VIU 的 YUV444 输入请求 RGB 时，上游选择器回落 YUV422，改请求相同 YUV444(2)后得到 640×360、步幅1920、8位的三字节输出。快照已越过状态/格式检查，但等待完成帧超时，VDIN1 中断计数为零；重新应用相同显示模式无效。当前 HDMI HPD=0，SSH/Kodi 正常。尚无完成帧，不能声称视频黑屏修复；下一步接 HDMI 对照，不需为脚本变更重新构建。212 配套文件及启动脚本保留供回滚。
