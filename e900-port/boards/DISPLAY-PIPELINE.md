# E900 GXLX2 display pipeline experiments (50–56)

Trial55 reference state used the tested clock-guard kernel/MP2 DT, a runtime-only
seven-bus registration helper, candidate44 VLD DMC module overlay, and runtime
`/sys/module/am_vecm/parameters/csc_en=0`. Nothing in this experiment installs
the overlay/helper or parameter into persistent startup. A reboot returns to
the normal USB baseline. eMMC and bootloader environment remain untouched.

Later trials restored CSC=7 using a POST2-only guard; see [POST2 validation](POST2-VALIDATION.md).

## Evidence

- A limited store_disp_mode function graph showed GXL PLL configuration and
  encoder setup returning. The mode write itself returned before the later
  loss of command processing, so an infinite PLL-lock wait was not established.
- Temporary netconsole delivered the PLL lock value and an HDR/DRM callback
  message in hard-IRQ context, but no Oops explaining the loss of responsiveness.
  SysRq logging later exposed a separate stmmac_poll_controller warning: it
  calls sleeping synchronize_irq through disable_irq in atomic context.
  netconsole was withdrawn to avoid that diagnostic confounder.
- Trial52 masked only the audited shared IRQ27 (SPI3, osd-vsync + vsync) via
  the existing disable_irq API before configuring 1080p60. The same display
  configuration then returned and timers/SSH remained healthy. Restoring that
  IRQ in trial54 reproduced the failure. Masking is diagnostic, not a fix.
- The sparse function trace shows the first video VSYNC reaching vpp_crc_check
  at the tail of vsync_isr_in. It does not prove the HDR callback is the exact
  failing function; transport truncation and later frames remain relevant.
- Trial55 changed only csc_en from 7 to 0, registered the verified buses, and
  configured 1080p60 without masking VSYNC. The interrupt count grew by 180
  every three seconds. The runtime stayed healthy for a subsequently verified
  3h25m, Kodi active with NRestarts=0, taint4096 (out-of-tree only).
- The generated 60s H.264 Main 720p30 sample progressed from 239 frames after
  eight seconds to a final observed 1799 frames, zero drops/frame/hardware
  errors. Kodi reached normal demux EOF and shut down its video codec/thread.
  One initial OutputPicture buffer timeout is recorded; do not silently treat
  the log as warning-free. Physical HDMI pixels and audio are not verified.
- After playback, RDMA IRQ121 tracked VSYNC almost one-for-one. Android DT
  specifies SPI89 for RDMA (89+32=121), matching CE. Earlier zero counts before
  active output do not alone establish an incorrect DMA IRQ or hardware fault.
- The post-play GUI screenshot contains the CE welcome wizard; inactivity
  dimming was active. Screenshots do not establish physical HDMI scanout.

## Remaining work

`csc_en=0` skips amvecm_matrix_process, not just HDR packet metadata. Its
success narrows the failing path but does not prove which register generation
or color/HDR capability is wrong. Bit0 enables CSC, bit1 OSD CSC, bit2 video
CSC; trial56 set bit0 alone (value1) with OSD/video matrix bits clear and reproduced the loss of timer/SSH responses, followed by a fresh automatic boot. This rules out requiring either matrix-enable bit for the failure, but does not identify the exact core processing step.
The source contains multiple CPU>=G12A decisions that require a GXLX2 audit.
Do not globally alias the CPU ID or present CSC bypass as completed adaptation.

Keep future ftrace filters small: 724 exact names spent minutes expanding
kallsyms. A trace_pipe reader also holds the current tracer busy; explicitly
close old diagnostic readers before changing tracer type. No full updated
ARM source build, GitHub push or workflow dispatch occurred in these trials.

## Persistent logging restoration (57–58)

Live ramoops parameters showed mem_address=0, mem_size=0 and no pstore backend.
The actual DT compatible was still `e9trace`, a deliberate earlier checkpoint
preservation change in make-full-boot-trial.py. The reservation itself was
present; no ramoops platform device had been created. Kernel source explicitly
populates a compatible ramoops node below reserved-memory, and the built-in
driver supports the existing console/record sizes. The original CE initrd and
normal kernel no longer run the retired checkpoint writers.

make-ramoops-trial.py restores only that eight-byte compatible property in the
pinned MP2 DT, proving every other property unchanged and revalidating the board.
The original DT is backed up under /storage/e900-before58. The source board
already inherits the correct ramoops binding; this repairs the diagnostic runtime
DT rather than adding a new source-board workaround. Live validation completed: backend=ramoops, mem_address=0x07400000, mem_size=1MiB, console/record 32 KiB. A unique emergency-priority marker was found read-only at RAM offset 0xb8bd9 before reboot, then recovered from console-ramoops-0 under a different boot ID. Kodi remained active NRestarts=0 with taint 4096. Persistent console recovery is now demonstrated; persistent function tracing is not compiled in. The generator additionally pins the normal kernel and original CE initrd to reject active checkpoint-writer combinations.
