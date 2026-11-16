# GitHub Actions 云编译

此工作流用于 CoreELEC 官方仓库的 fork。基线固定为 21.3-Omega 的 `fc61125e8900ab0c2593a29b615980ed0cd5b939`，本目录应放在 fork 根目录的 `e900-port/`；工作流放在 `.github/workflows/e900-coreelec.yml`。

## 首轮运行

在 fork 的 Actions 页面选择 **E900 CoreELEC experimental build**，手动运行：

- profile：`decoder`，编译检查当前全部四个候选补丁。
- target：`media`，构建内核及媒体模块。

首轮目的是获得编译结果和修复报错，不代表硬件适配完成。完整板级 DTB 尚未接入，云端产物目前不能用于试刷。工作流支持 `baseline`、`identify`、`hdmi` 配置，便于隔离补丁问题；`image` 入口留给后续集成验证。

## 工作流行为

1. 使用 GitHub 托管的 Ubuntu 22.04 x64 runner，在临时虚拟机中清理不用的预装工具，检查剩余磁盘。内核/模块构建要求至少 35GiB 空闲，完整镜像要求至少 50GiB；实际可用空间不足会停止并报告。
2. 安装与 Docker 方案对应的原生构建依赖，不使用 Docker。
3. 下载独立的固定上游源码，按选择的 profile 安装补丁。fork 的变更只提供构建工具和候选补丁，不会绕过版本检查。
   为避开 keyutils 原站连接超时及旧备用镜像 404，安装脚本将其下载地址改为 Debian 的原始源码镜像；仍固定 1.6.3、保留原 SHA-256 和缓存文件名。已实际下载并核对镜像包与原校验值完全相同。此覆盖作用于实际构建的独立源码树，而非仅修改 fork 顶层包配置。
4. 从公开仓库获取固定测试源码，核对 Git blob SHA-1 和 SHA-256，运行补丁应用及本地 C 检查。
5. 编译所选目标。单次编译超时为 300 分钟，job 上限为 360 分钟，留出上传日志的时间。
6. 分层恢复并保存源码下载包、已安装工具链与完整编译目录、ccache、依赖 deb 包。测试源码也保存在下载缓存中。兼容性匹配时，失败后重跑可复用已完成包的构建标记和中间产物。
7. 无论编译成功或失败，都尝试上传日志及已有产物，保留 7 天。查看 artifact 内的 `build-metadata.json`、最后动作退出码和完整日志；较早留下的二进制不能代替本次成功结果。

只启用 `workflow_dispatch`，没有定时任务，也不会因为每次 push 自动开始长编译。工作流只申请 `contents: read`；发布代码和创建 fork 由开发者账号完成，不需要给构建任务额外写入权限。第三方 Actions 固定到核对过的提交 SHA。

官方说明：[托管 runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[Actions 限制](https://docs.github.com/en/actions/reference/limits)。公开仓库使用标准托管 runner 的计算资源免费；可用磁盘和六小时 job 限制仍会影响构建。若 job 超时或磁盘不足，应先调整构建范围和缓存，而不是把失败当作适配结论。

## 文件发布范围

`scripts/stage-fork.py` 只复制公开开发文件和工作流。不会复制原厂固件、盒子完整备份、Mac SSH/ADB 密钥、GitHub 登录文件、照片或用户网络配置。没有本机绝对路径、固件下载账号或令牌需要提交到 fork。

此脚本只准备本地文件，不会自动 fork、推送、合并或启动 Actions。首次远程操作前必须有已登录的 GitHub 账号。

## 增量缓存

| 缓存 | 内容与复用边界 |
|---|---|
| downloads | 源码压缩包、校验过的测试文件；继续兼容先前仅有下载缓存的任务 |
| build-state | 固定上游 checkout、安装后的交叉工具链、sysroot、已解压源码、对象文件、完整/部分编译结果及构建标记 |
| ccache | 同宿主兼容环境的编译对象缓存，host/target 共用目录，上限 1G |
| debs | 安装编译依赖时下载的 deb 文件；每台新 runner 仍需执行 apt 安装，但可少下载 |

完整编译状态按上游 pin、宿主系统/关键工具包版本、构建脚本、profile 及绝对编译路径隔离。`linux`、`media`、`image` 目标可以复用同一 profile 的兼容状态；不同 profile 的编译路径不同，不直接搬用已安装工具链。

优先恢复补丁完全匹配的最近状态；没有精确补丁匹配时，可以恢复相同宿主/固定基线/profile 的旧状态。CI 显式启用 `E900_INCREMENTAL_REUSE=1`：内核补丁变化会通过 CoreELEC 的 `scripts/clean` 清理内核和媒体模块，媒体补丁变化仅清理媒体模块，下载配置变化仅清理 keyutils。工具链不随这些变动一起清理。其他内核相关包继续由 CoreELEC 的 `LINUX_DEPENDS` 内容校验判定失效。

每次 run/attempt 使用新缓存键，正常失败或编译阶段超时后也尝试保存部分状态；缓存上传失败不覆盖原编译错误。手动取消、runner 被强制回收或整个 job 硬超时，不能保证最后的保存步骤执行。先前未保存过的工具链无法从已销毁的 runner 找回。

GitHub 默认缓存容量为每仓库 10GB；本工作流不调整容量或计费设置。完整状态较大，多层缓存及历史快照可能触发淘汰；以 Actions 的 Restore/Save 日志为准。首次部署本次缓存修改后仍需跑一轮，才会有工具链与编译状态可供后续恢复。
