# GXLX2 hardware video plane investigation

## Observed on source-built run 44441905557

- A boot without HDMI followed by hotplug produces VSYNC but no RDMA IRQ,
  watchdog reset loops and a physically black display. Kodi restart does not
  restore it. Rebooting with HDMI connected restores the physical menu;
  baseline reset_count=3 then stays stable while RDMA IRQ advances.
- H.264 Main 720p30: decoded frames advance to 452 in 15 seconds, reported
  errors/drops zero, but the user sees black video. Stop restores the menu.
- DI bypass_all=1: user still sees black video; parameter restored to 0.
- HEVC Main 8bit 720p30: decoded frames advance 95/185/275; the user reports
  initial flashing then solid green without a menu. RDMA IRQ stops and the
  reset loop recurs. Reboot with connected HDMI restores operation.
- Software decoding of the SAME H.264 MP4: confirmed FFmpeg decoder, no
  hardware vdec instance. User confirms normal video AND normal menu.
- The first attempted software test was invalid: a settings operation was in
  an assertion removed by Kodi's optimized Python. The corrected test uses
  explicit operations, verifies amcodec=false during playback and true after.
- Decoder MMU was already disabled. Driver-supported 32x32 and 64x32 canvas
  layouts both still give black physical video; settings restored to default.
- Standard /dev/amvideocap0 capture during hardware H.264 playback returns a
  320x180 RGB24 frame, state=300, 172800 bytes. It contains identifiable color
  bars and the white marker, not a solid black frame. Its right-hand region
  is visibly corrupted. This is not proof of fully correct decoder pixels:
  GE2D/Canvas/capture formatting may contribute. No direct memory mapping or
  physical address access was used. Kernel taint remains 4096, reset_count=3.

The candidate in patch 0008 changed blend policy and MIF table together.
A legacy OSD profile alone does NOT prove that GXLX2's video MIF register bank
is identical to GXL. Standard frame capture and software decoding now provide
better controls, so the next experiment separates those decisions.

## Boot-only diagnostic probe, patch 0009

Default `amvideo.gxlx2_g12_mif=0` preserves patch 0008 behavior. Setting
`amvideo.gxlx2_g12_mif=1` in the USB script's kernel command line selects the
existing G12 MIF register table ONLY for GXLX2; legacy blend remains selected.
The parameter is read-only after boot (0444). Live switching is unsupported.
No global CPU identity change or new register addresses are introduced.

The driver logs the chosen software table addresses at boot:
`e900-video: legacy_blend=1 mif=... vd1_gen=... vd1_canvas=... vd1_fmt=...`.
This log does not read hardware registers. Host tests compile the actual
selection blocks for both probe values, all CPU IDs 0..0x3f and revision
states; other CPU/default behavior is compared to upstream. Full ARM build
and this probe's hardware test have NOT been performed.

Build decoder/image with source_trace=false. Keep HDMI connected. After
verifying the native default boot and log, use a separate reversible USB
loader to add the one boot argument. Keep the default loader and previous
SYSTEM available. Compare short H.264 playback, clean stop/menu, decoded and
displayed frame counts, RDMA IRQ/reset deltas, and optional standard RGB frame
capture. Do not install to eMMC. Do not declare success from frame counts.

If neither bank produces correct hardware video, retain the evidence and
investigate formatter/scaler/color-routing and lost early initialization
writes before making further generation-wide assumptions. Numeric >=G12A/B
checks remain in those paths and are not automatically proven wrong merely
because GXLX2 has ID 0x2a.
