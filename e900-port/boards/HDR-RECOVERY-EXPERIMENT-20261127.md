# GXLX2 VD1 HDR 恢复单变量实验（源码准备）

本轮只完成源码补丁与主机测试，未构建、部署、重启或播放。固定 Linux 基线是 `/Volumes/linux-amlogic/linux-amlogic` 的 `50c8e8154c5aba3c7cd8438d04dd5fdd51733e41`；在隔离临时树中按仓库顺序套用影响目标文件的 0019、0022、0029、0031 后生成新 0037。旧 0037 根据 `VD1_HDR2_CTRL` bit12 判错，已替换；旧 0038 人为改 `new_vframe_count`，已从默认清单删除。

## 开关与边界

- `gxlx2_hdr_recovery`（`am_vecm.o`包含amcsc.o；新机核对后使用`/sys/module/am_vecm/parameters/gxlx2_hdr_recovery`）：root 可写，默认 `0`。同一新构建的 A/B 才能比较，分别用独立启动；当前已部署 Claude 固件含旧 0037/0038，不能充当新开关关闭对照。
- 只针对 `is_meson_gxlx2_cpu()` 的 VD1。`video_global_output_store` 看到真实 1→0 时，要求 VD1 有非本地帧、未被 disable 且 enabled；记录 provider 代次、vout mode 与 5 秒期限。匹配的 0→1 才发布请求；恢复瞬间 enabled 可为 0，等待有效首帧。
- provider 注册/注销/重置、VD1 disable、真实关层会取消旧请求。模式/代次变化、超时也取消。fake frame、Dolby Vision、未启用的层不能消费。未触发请求时不新增 HDR 寄存器读写。
- `vpp_matrix_update` 在已有 HDR_BYPASS/Dolby/HDMI 提前返回之后、原无变化早退之前，对符合条件的一次调用注入 `SIG_FORCE_CHG`；GXLX2 的原有分支进入 `video_post_process`。此处只保证函数调用，不能仅凭计数声称硬件完成。已有 0033 `hdr_request`/`hdr_submitted` 与寄存器证据仍须对照。
- 只读计数参数：`gxlx2_hdr_recovery_requests`、`_consumed`、`_cancelled`、`_post_calls`；日志前 16 条打印代次和计数。`post_calls` 表示实际进入函数调用点，不等于硬件提交。

## 离线检查

- `python3 e900-port/tests/check-hdr-recovery.py`：PASS。直接编译 0037 中的生产边沿/消费函数，覆盖默认关闭、首播、匹配恢复、恢复时 layer off、fake frame、单次消费、Stop 取消、代次/模式变化、超时、其他 CPU、Dolby 抑制；同时检查 store 的非布尔输入保护与真实关层钩子。
- 在固定基线隔离树上 `git apply --check 0037...patch`：PASS。未做完整 ARM 内核编译。
- `E900_AUDIT_ROOT=../coreelec-audit python3 e900-port/tests/check-hdr-evidence.py`：PASS。该检查覆盖当前 Linux 补丁栈与原 HDR 写序；未声称硬件完成。

下一步由审计者检查跨模块链接/完整补丁栈与实验手续。VDIN slot 观测链没有在本补丁中改动。

## 构建与实测顺序

构建decoder完整镜像（linux已变更，兼容工具链应复用），source_trace保持关闭，保留现有VDIN构建选项。不触发远端构建或自动部署。主机缺少reference/CoreELEC/.../linux/package.mk，故check-build-cache.py未完成；不能把这个本地依赖缺失写成测试通过。补丁栈应用及HDR原写序测试通过，ARM编译与链接仍待云构建。

新固件部署后，先新boot保持开关N，确认首播并做一次默认global脉冲，保留真实电视反馈；异常即停并审记录。随后另一个新boot开启开关Y，首播正常后做同一脉冲，要求requests/consumed/post_calls各增1，并关联0033的hdr_request/hdr_submitted与0035提交表。计数不符则实验无效，不能解释为HDR无效。开关关闭不新增HDR强制事务。

本轮开关只处理global恢复，不自动覆盖Stop/replay。Stop/replay先作为独立回归记录；真正Stop取消请求，不能为了重播强行沿用上次请求。若全局脉冲实验有效，再设计真实重播的独立事务验证。

回采完成计数增长不足以认定画面正常；必须用户确认电视，并对彩条移动标记验证动态变化。每轮黑屏后不自动重播或重启。VDIN完成槽/读取槽联合观测尚未实现，本次不宣称修复该缺口。
