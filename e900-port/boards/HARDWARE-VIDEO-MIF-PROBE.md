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
states; other CPU/default behavior is compared to upstream. Full ARM build succeeded in run 44555272578. The hardware results below
show that this table selection alone does not fix visible playback.

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

## Run 44555272578 and SR0 collision evidence (2026-11-20)

The source-built G12 MIF probe booted with legacy blend retained and the
expected table addresses. H264 counters advanced with zero reported errors,
but the user confirmed black video and a working menu. OSD plane alpha=0
and a native 1280x720 output axis independently gave the same physical result;
both controls were restored. RDMA continued without new resets.

The existing RDMA submission logger then recorded this sequence for handle 1:

```text
3200 = 0x38000043   # VD1 GEN setup
3200 = 0x050002d0   # overwritten by packed 1280x720 size
```

Pinned source defines G12 VD1 GEN and legacy SR0 HVSIZE at the same 0x3200
address. vpp_set_super_scaler_regs writes the SR0 size even when super_scaler
is false; the observed zero SR0 offset causes the collision. This invalidates
a clean comparison of the MIF banks: the G12 candidate is overwritten by an
unrelated legacy SR write. It does not establish which hardware bank is right.

Offline diagnostic 181 preserves the exact build and skips only that SR0 size
write (two compiler copies, eight bytes total). It retains the original kernel
and uses a separate USB kernel path and backed-up loaders. It is specific to
this image/box and is not a general source fix. Verify disappearance of the
size overwrite in submission logging, then assess physical playback. No direct
physical-memory or live register access is involved.

## Physical results of offline isolation 185–188

After USB recovery and restoration of user-moved kernel files, diagnostic 185
booted successfully. The submission logger confirmed that 0x3200 retained
0x38000043 and the packed size overwrite was absent. H264 test 186 still gave
physically black video; counters advanced 63/123/184 with zero reported errors.
The missing SR0 write alone does not resolve playback.

Diagnostic 187 retained that isolation and G12 MIF, changing legacy_vpp's initial
value to false in a separate image. The boot log confirmed legacy_blend=0.
Kodi ran and VSYNC/RDMA advanced at 60/120 per second, reset_count stayed 3.
Test 188 advanced H264 counters 62/123/183 with zero reported decode errors,
but the user reported no picture, including after pressing confirm; button
sounds remained audible. The global G12 VPP selection is rejected for normal
use on this build. It changes several capability/blend branches and therefore
does not by itself prove that every G12-associated hardware block is absent.

Restored the verified original MIF1 loaders and requested reboot 189 to return
to the user-confirmed menu baseline. Neither offline diagnostic is a source
fix or a verified hardware-decoding solution.

## Formatter isolation 191–194

Both control and candidate used the legacy MIF and legacy VPP policy. The
control's RDMA log showed formatter 0x1a68 changing from 0x00310c11 to
0x20310c11 through the numeric CPU>=G12A bit29 path. The candidate skipped
only the two formatter bit29 calls; its log confirmed 0x00310c11 retained
and GEN 0x1a50 unchanged. User still reported black H264 video. The user
clarified they had not pressed confirm, so menu visibility in this trial is
UNTESTED; do not record it as a menu failure. Decode counters advanced with
zero reported errors, taint4096/reset3 stable, clean stop. This narrow change
is not a visible-playback fix. Original menu baseline restored for reboot195.

## Native-size and hold-line controls 196–200

Native-size playback used the unmodified kernel, legacy MIF/blend, and the
normal driver axis/bypass controls. The submission log confirmed PPS top
enable cleared at 0x1d19, both phase steps unity, and super scalers disabled.
User confirmed black video and subsequently saw playback controls briefly.
Thus record partial OSD visibility, not a complete output failure. Restoring
vpp_hold_line from0 to the source initial value8 changed GEN submission from
0x38000043 to0x38400043 but still produced black video. Temporary values and
trace controls were restored; these tests are not initialization fixes.

## Reliable pixel readback 202–204

Same-file reference decoding and byte-order analysis identified BGR24 output.
The earlier right-side capture noise was then isolated to capture timing:
paired immediate/delayed reads at320x180,640x360,1280x720 produced incomplete
immediate captures but complete delayed color bars. At640 width the static
right-quarter mean error fell from65.3 to2.2 after waiting. The nonblocking
GE2D call followed by immediate Canvas/frame release and success reporting
explains the observed race; delay is diagnostic, not a proper completion fence.

For this H264 sample, decoder output can be read correctly through Canvas and
GE2D. This supersedes the suspicion that capture169 alone proved damaged
decoded pixels. HDMI video remains black. Patch0011 makes GXLX2 capture wait
through the existing blocking GE2D API; patch0010 separately provides an opt-in
video-init-after-buses diagnostic. Both need full ARM build and hardware tests.
See [updated chain and images](DISPLAY-CHAIN-REVIEW.md).
