# TVBian GXLX2 对比分析（2026-11-23）

> 实机复核更新：同一build278开启晚初始化无法上线，关闭后能启动；尚未确认黑屏根因。下面“根因定位”“修复”等表述应视为当时假说。尤其CE的video_hw_init只读VPP_HOLD_LINES，主线显式写该寄存器，不能假设重跑读取就能恢复值。主线与树外驱动的区别、具体字段和下一步对照见[后续源码核对](MAINLINE-PLAYBACK-COMPARISON-20261123.md)。

范围：对比 TVBian (sormy/tvbian) 在主线 Linux 6.18 上的 GXLX2 成功实现与 CE 4.9 BSP 栈的差异，定位硬解黑屏根因。

## 对比对象

| 项目 | TVBian | CE (本项目) |
|---|---|---|
| 内核 | 主线 6.18 | 厂商 BSP 4.9.269 |
| 视频栈 | DRM/KMS + V4L2 M2M | amvideo + media_modules (RDMA/VSYNC) |
| 目标盒子 | H96 Max M20 (S905L3, P291, 2GB) | E900V21C (S905L3-B, P291, 1GB) |
| CPU major ID | 0x2a | 0x2a |

S905L3 和 S905L3-B 的 major ID 相同（0x2a），内核层面无差异。TVBian socinfo 补丁用 `{0x2a, 0, 0x0}` 匹配任意 package，不区分 L3/L3-B。两者都是 P291 板型。

## 关键发现

### 1. 解码器路径：TVBian 用 G12A 类，CE 用 legacy/GXL

TVBian `meson-codecs/0001`:
- GXLX2 用 `VDEC_REVISION_GXLX2`，排在 G12B 之后（G12A 类）
- HEVC/VP9 使用 G12A 固件（`g12a_hevc_mmu.bin`、`g12a_vp9.bin`）和 G12A codec ops
- MPEG-1/2 用 `gxl_mpeg12_multi`（multi codec）
- 两个 G12A 例外：无 HEVC front clock (`clk_hevcb_mux`)、`HEVC_SAO_CTRL1[15:14]` 保持 reset 值
- DMC 基址用 GX 的 `0xc8838000`（非 G12A 的 `0xff638000`）

CE 0008 补丁:
- `legacy_vpp = true`（排除 GXLX2 出 G12A 路径）
- MIF 寄存器表选 legacy（非 G12A）

注意：这是**解码器**（硬件 codec 核心）和**显示管线**（VPP/blend）的区别。解码器核心确实是 G12A 类的，但显示管线是 GXL 类。CE 0008 只管显示侧 `legacy_vpp` 和 MIF 表选择，解码器侧的 media_modules 是独立的。

### 2. 显示管线：GXLX2 是 GXL，不需要特殊处理

TVBian 对主线 DRM 显示驱动**零 GXLX2 补丁**：
- `meson_overlay.c` — 无修改（VD1 plane 配置）
- `meson_viu.c` — 无修改（VIU 初始化）
- `meson_crtc.c` — 无修改（CRTC/vsync 提交）

GXLX2 在主线 DRM 中走 GXL 路径（非 `VPU_COMPATIBLE_G12A`），开箱即用。
CE 0008 保持 `legacy_vpp=true` 是正确的。

### 3. FIFO 和 hold_line 值

| 参数 | 主线 meson_viu.c | 主线 meson_overlay.c | 厂商 3.14 | CE 4.9 实机读回 | 0019 写的 |
|---|---|---|---|---|---|
| VD1_IF0_LUMA_FIFO_SIZE | 0x00FF00C0 | — | 0x180 (TXL/TXLX) | 0xFF00C0 | 0x180 |
| hold_line | — | VD_HOLD_LINES(9) | 17 | 0 | min 17 |

**0019 补丁的 FIFO=0x180 是错的**。实机读回的 0xFF00C0 是主线所有平台统一的默认值。
hold_line 实机为 0 是因为 video_hw_init 的写入被丢弃了（bus 未注册），不是因为值不对。

**结论：删除 0019，问题出在写入时序而非写入值。**

### 4. HDMI：G12A 直连映射 + GXL PHY

TVBian `meson-dw-hdmi/0001`:
- `meson_dw_hdmi_gxlx2_data`：G12A 寄存器读写函数 + GXL PHY 配置
- `uses_direct_regs = true`（跳过 APB3 fail-on-error 位）
- `phy_cntl0_3g = 0x33353382`（GXL 是 `0x33303382`）
- DWC 映射在 `0xda800000`，TOP 在 `0xda808000`

与 CE 0002 补丁的方案一致。

## 根因定位

### 为什么主线能用但 CE 黑屏

**主线（TVBian）**：
- `meson_overlay.c` 每帧通过 `writel_relaxed` 直接 MMIO 重写 VD1_IF0_GEN_REG（hold_line=9, urgent, canvas, 窗口坐标等）
- 没有 bus callback 间接层，没有一次性初始化依赖

**CE 4.9 BSP**：
- `video_hw_init` 在 `module_init(6)` 做一次性初始化（OFIFO、hold_line、dummy data 等 9 次 VCBUS 写入）
- 所有写入走 `codec_reg_write` → bus callback 间接层
- GXLX2 的 bus callback 在 `late_initcall_sync`（0006 补丁）才注册
- **9 次写入在 callback 为 NULL 时执行，全部静默丢弃**
- 结果：VPP_HOLD_LINES=0、OFIFO 未配置 → VD1 MIF 无法正常拉取解码帧 → 黑屏

### 因果链
```
video_early_init [module_init]
  └─ legacy_vpp = true (0008, 正确)
  └─ MIF table = legacy (0008, 正确)

video_hw_init [module_init(6)]  ← 此时 bus callback 未注册
  └─ WRITE_VCBUS_REG(VPP_OFIFO_SIZE, 0xfff)     → 丢弃
  └─ WRITE_VCBUS_REG(VPP_PREBLEND_VD1_H_START_END) → 丢弃
  └─ WRITE_VCBUS_REG(VPP_DUMMY_DATA, ...)         → 丢弃
  └─ READ_VCBUS_REG(VPP_HOLD_LINES) → 返回 0     → vpp_hold_line = 0
  ...共 9 次写入丢弃

gxlx2_reg_ops_late_init [late_initcall_sync]
  └─ 注册 7 条 bus callback ← 太晚了，video_hw_init 已经跑完
```

### 修复
0010 补丁：将 video_hw_init 延迟到 late_initcall_sync 之后执行。
确认 bus callback 就绪后再写入，9 次寄存器写入正常落地。

## 分支状态 (fix/gxlx2-late-video-init)

- 0010：默认开启 (`gxlx2_late_video_init = true`)
- 0019：已删除
- 其他补丁不变

## 验证计划

实机测试时检查：

1. **确认延迟初始化生效**
```
dmesg | grep e900-video-init
```
期望三行：defer → ready → returned 0

2. **确认寄存器写入落地**
```
# VPP_HOLD_LINES 应非零
# VPP_OFIFO_SIZE 应为 0xfff
# 通过 stage hook 或 device_debug 确认
dmesg | grep -i "hold_line\|ofifo"
```

3. **GE2D 抓帧**（0011 已在 decoder profile）确认解码器产出画面

4. **如果仍然黑屏**：勾选 vdin_capture 重编，用 VDIN 诊断管线后段

## 待获取：原厂镜像

原厂固件备份可以提供：
- **DTB**：反编译对比 reserved-memory、时钟、HDMI、vdec 配置
- **vendor kernel**：strings 搜索确认原厂走哪些分支
- **bootloader (BL2/BL31)**：u-boot 预设的 VPU/HDMI/PLL 寄存器状态，Linux 继承这些值

如果 0010 修复后仍然黑屏，原厂 DTB 和 bootloader 分析将是下一步重点。

## 参考源

- TVBian 仓库：`/tmp/tvbian-research/tvbian/`（本次会话克隆）
- 主线 `meson_overlay.c`、`meson_viu.c`、`meson_crtc.c`：kernel.org v6.12
- CE `video_hw.c`：CoreELEC/linux-amlogic commit 50c8e8154c
