# GXLX2 SR0初始化访问故障：2026-11-24

## 实机证据

build279来自云任务45207870443、源码3a58f58120。等待模式能启动，SSH/Kodi正常，初始化status=1、step=0。Mac实际收到netconsole READY后，只触发过一次固定寄存器初始化。

* 网络日志包含步骤1–6全部write.end。
* 最后记录为`step=7 read.begin reg=3eb0`，未见read.end；随后新SSH连接超时。
* 后来设备以新boot_id重新上线，回到等待模式。重启是自动还是人为，当时未确认。
* 成功取回`console-ramoops-0`，其尾部同样停在该读取。没有可用Oops调用栈；这定位了首个未返回访问，不等于已经证明视频黑屏的最终根因。

本地原始证据：`trial-build279/netconsole.log`、`previous-boot-console.txt`及`deployment.json`（均在工作区根目录下）。

## 源码不一致与修复

`SRSHARP0_SHARP_SYNC_CTRL=0x3eb0`。BSP的`video_hw_init()`按`cpu_after_eq(G12B)`访问SR0同步位；GXLX2 major ID=0x2a满足该数值条件。

但`vpp_sr_init()`的能力路径没有给GXLX2启用SR0：本机使用通用amvideo profile，sr0_support/sr1_support为0xff，而旧型号匹配分支未包含GXLX2，最终清除`sr_info.sr_support`中的两个SUPER_CORE支持位。因此“数值ID较大”与“实际声明支持SR0”不一致。

新增[0021补丁](../patches/linux/0021-gxlx2-sr0-capability-guard.patch)：

* 新增的固定初始化路径，仅在`sr_info.sr_support & SUPER_CORE0_SUPPORT`时执行步骤7、8；否则记录跳过原因，继续其余配置。
* 原有初始化函数的G12B数值分支也对GXLX2添加相同能力检查，保护关闭新修复时的对照路径；其他SoC的原判定不变。
* 使用`sr_support`位掩码，而非`core_support`枚举。后者`ONLY_CORE0=0`，不能把它当支持位掩码。

**这里不再以“把丢失的九次写入全都重放”作为修复标准。** 原序列包含这两次缺少能力依据、且已在本机读取时失联的SR0读改写，必须先过滤。剩余配置及有限读回能否完成，还需实机验证。

## 无需再编译的临时对照

为先验证停点，准备Image280：以同一Image279为基础，仅将步骤7、8两处调用`gxlx2_hw_update_bits`的BL指令替换成NOP，其余镜像字节和SYSTEM279/DTB279/initramfs279不变；等待模式保留。

| 调用地址 | 镜像偏移 | 原指令字节 | 临时替换 |
|---|---|---|---|
| ffffff80098f1ce8 | 8854760 | f4151394 | 1f2003d5 |
| ffffff80098f1d00 | 8854784 | ee151394 | 1f2003d5 |

离线核对BL目标为`gxlx2_hw_update_bits`，对应参数为step7、step8；完整镜像仅这两处指令修改。符号来自本机同一内核的只读kallsyms，反汇编针对本地文件，不读取运行时内存。

该临时镜像**无条件跳过两次调用**，不含正式0021的能力位判断及跳过日志，因此只作为本机停点对照，不能冒充新源码构建或通用修复。材料位于`trial-sr280/{prepare.py,manifest.json,apply279.asm,boot280.src}`。

源码补丁应用与初始化宿主测试通过；测试覆盖SR0能力位开/关、只有SR1能力时不访问SR0，以及没有SR0访问时仍能进入后续读回。正式0021的ARM构建尚未执行。临时镜像实机结果应另行记录，不以准备成功认定初始化/播放通过。

## Image280实机结果

同一SYSTEM279、DTB279及initramfs279，仅两处BL改为NOP；boot_id=`76c32043-7048-4eb0-a601-7d4d550c1db3`。等待模式先正常启动，Mac重新收到本次READY后，执行一次释放：

* release脚本退出0；`gxlx2_hw_init_status=2`、step=13、run=Y。
* 步骤1–6完成，步骤7/8按镜像变更跳过；本次dv_support分支也未执行步骤9，之后步骤10–13全部返回。
* `VPP_HOLD_LINES(0x1d22)=0x08080808`，软件`vpp_hold_line=8`，不再使用早期无回调读取产生的0。
* OFIFO读回`0xfff00fff`、两个窗口均`0x1000`，通过当前有限读回条件；网络收到`E900_VIDEO_INIT_RELEASE_OK`。
* 随后SSH仍在线、同一boot_id，Kodi重新启动并静音；尚未启动视频验收。

这为“SR0同步访问使该初始化序列停滞”的判断提供了单变量对照依据。它不证明所有早期寄存器访问都已修复，也不证明硬解视频已经上屏。

完整记录：`trial-sr280/manifest.json`、`netconsole280.log`、`dmesg-complete.txt`、`release.log`。Mac接收器仍监听UDP6666。当前U盘使用临时Image280并保留等待参数；重启后会重新等待，不会自动执行测试。正式带能力判断/skip日志的0021仍需新ARM构建。


### Repeat-playback evidence: Kodi restart does not recover video

On boot `0acd9243-e933-4046-a190-68208f035bb8`, fresh first H264 playback was visible and smooth after a delay; Stop/replay remained black after 15 seconds. Restarting Kodi alone also remained black (451 decoded frames, zero frame/hardware errors, initialization status 2).

The fixed guarded stage hook during the Kodi-restart test reported live VD1 GEN `0`, RDMA-aware GEN `38400043`; requested/shadow blend `100054b0`, live blend `100010b0`. Thus software requests video enable but the live VD1 reader and VD1 blend enable are absent in these samples. Two samples alone are not a long-duration latch test.

Public driver parameters read twice 2 seconds apart: video RDMA `enable=1,0`, `irq_count=0,0` on both reads, `vsync_cfg_count=4,0` on both reads. Source increments irq_count unconditionally in its completion callback. Kernel log repeatedly reports `rdma_write_reg ... buf overflow`; the pinned manager implementation handles overflow by directly writing accumulated entries to VCBUS. This provides a concrete candidate mechanism for delayed first picture despite absent RDMA completion. A controlled video-RDMA bypass test remains pending; no claim that all previous black-screen cases share this cause.

Evidence: local `trial-sr280/kodi-restart/` and `trial-sr280/manifest.json`. No source fix for RDMA has been applied.


### Video-RDMA bypass: enable writes recover, visible video does not

On the same boot, Stop, set public video RDMA `enable=0,0`, then play the same H264 sample. Fixed guarded probes at approximately 10 and 15 seconds show VD1 live/shadow GEN `38420043` and requested/live/shadow blend `100054b0`. Decoder reached 484 frames with zero errors. User still reports black. OSD RDMA was not changed.

This proves that bypassing video RDMA restores the sampled hardware enables, but it does not establish visible-pixel recovery or a complete black-screen fix. A previous state left in hardware remains a hypothesis. The next controlled test should remove all box power, then disable video RDMA before the first playback after initialization. The mode change above is runtime-only and does not persist across reboot. Evidence: `trial-sr280/rdma-bypass/`.


### Matched first-good / repeat-black baseline

User rebooted; new boot `b4085e08-eaad-4247-bcde-76c0f61f1868`. Kept video RDMA at default `1,0`. Completed gated initialization, played H264, sampled at approximately 10 and 15 seconds. User confirmed visible video. Then Stop/replay with unchanged settings and identical probes: user confirmed black, 481 decoded frames, zero errors. Both tests have RDMA completion count `0,0`.

First-play 10-second samples show live GEN `240000`, canvas/fmt zero and disabled VD1 blend despite queued enables. At boot time93.852s manager reports buffer overflow; subsequent15-second samples have GEN `38400043`/`38420043`, canvas `5a5958`, correct fmt and enabled blend. This chronology is consistent with overflow direct-write fallback enabling first picture, but has not isolated causation.

Repeat-black samples have the same observed GEN, scaler, matrix and blend as first-good; later review identifies a GEN3 difference (see below). Live canvas stays `5a5958` while queued canvas also selects `605f5e`. A transient live/queued mismatch is not by itself proof of a stale-frame cause; these existing probes do not capture every stage or full register state. Thus no claim that observed register equality proves the downstream pixel path healthy.

Evidence directories: `trial-sr280/paired-first/` and `trial-sr280/paired-repeat/`.


### Healthy-first-play RDMA switch control

Cold-start boot `dc86e5ac-8af0-4214-bdc7-948be27e2588`: user confirmed default-RDMA first playback normal. At switch time the decoder was still active (1598 frames). Set video RDMA0,0, wait3seconds, then Stop/replay. User reports black after15seconds,482 frames,zero errors. Live/shadow GEN, Canvas and blend match under bypass. No separate user observation during the3-second switch interval; do not assume that interval remained visible. Evidence: `trial-sr280/healthy-switch/`.

### New source candidate: DI unregister gates shared CLKB, bypass registration skips ungating

Pinned `drivers/amlogic/media/deinterlace/deinterlace.c` matches runtime log line6992 (`disable post`). In `di_unreg_process_irq`, lines7398–7414, mirror_disable invokes hardware disable and switches `VPU_VPU_CLKB` off unless CPU is exactly GXL/GXM/GXBB/TXLX. GXLX2 is distinct and is not excluded. Actual stop log at133.618s reports `di_unreg_process_irq disable di mirror image`.

In `di_reg_process_irq`, lines7646–7656, `need_bypass(vframe)` returns before the CLKB-on call at7679. Runtime first stream reports DI bypass0→1; repeat again runs disable-post. This is a concrete possible missing restore on the progressive-bypass path, not proof that CLKB is off at failed output. Search for all callers shows the register path above and driver setup/shutdown also manipulate this clock; actual clock state must be measured or guarded lifecycle logs added before claiming causality. GXL VPU profile maps this gate to its clock table; its presence cannot be inferred solely from numeric CPU IDs.

Next useful diagnostic: fixed GXLX2-only trace at unregister gate-off, bypass-return and gate-on. A separate opt-in experiment can preserve the pre-stop CLKB state, without changing RDMA or other pipeline settings. No CLKB behavior patch or new image deployed yet. Avoid repeating broad global-clock overrides already tested historically.

Another candidate: latest matched normal samples use VD1 GEN3=0x33; repeat samples0x3033 (bits12/13 differ). These observations need source/field ownership verification. Correction to earlier note: paired-first normal GEN3 is0x33, not0x3033; older h264-fresh-only0x3033 samples belong to already-black repeat.


### CLKB lifecycle hypothesis tested: restore call is present

User unavailable to view HDMI but authorized terminal-only testing. Enabled existing `/sys/class/vpu/print` logging for one playback/Stop/replay cycle, then restored0. Did not invoke broad `gate r`, `mem r`, arbitrary register access, or VDIN reads.

Actual timestamps: CLKB ON831.080023; Stop marker835.779284; CLKB OFF836.114159, call stack `di_unreg_process_irq+0x16c`; repeat marker839.034961; CLKB ON839.594085, call stack `pre_tasklet+0x6d8`. Thus the simple hypothesis that repeat playback leaves CLKB off due to a skipped restore is contradicted by the observed on-call. The candidate source path alone was insufficient. No physical clock readback or HDMI image result was collected, so this does not certify all clock programming. No clock behavior patch is justified by this test. Evidence: `trial-sr280/clkb-lifecycle/dmesg.txt`.
