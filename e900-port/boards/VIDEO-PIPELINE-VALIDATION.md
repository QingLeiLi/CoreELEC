# GXLX2 playback black screen: source candidate

Update 2026-11-19: the unmodified source-built run 44441905557 has booted.
See [runtime and unattended results](NATIVE-RUN-44441905557.md); physical
HDMI playback remains pending because HPD is 0.

On 2026-11-19 the user confirmed working HDMI menus and remote navigation,
but H.264 playback caused a physical black screen that persisted after stop.
A Kodi screenshot during the fault still contained the menu. Restarting Kodi
restored the physical menu in the first test. Disabling automatic refresh-rate
adjustment removed repeated display-loss/reset messages, but did not fix the
physical black screen in the following bounded playback test.

At runtime, `legacy_vpp` was false. The board's framebuffer uses the inherited
GXL OSD_NORMAL profile. The original `video_early_init()` selects both its
non-legacy blend policy and G12 video MIF table solely from CPU ID >= 0x28;
GXLX2 is 0x2a. OSD software requested mask 0x1030 while sampled VPP_MISC was
0x100000ca after stop. This is a concrete policy mismatch worth testing;
it does not prove that every GXLX2 display block equals GXL hardware.

Patch 0008 excludes GXLX2 only at those two initialization decisions. It does
not globally spoof the CPU ID, change other SoCs, or claim to correct all
numeric family checks elsewhere in video/HDR/scaler code. The test compiles
actual upstream and patched selection blocks with distinct register-table
sentinels and compares all other CPU IDs/revision states. Full kernel/module
compilation and physical playback remain required.

A direct userspace mmap register-write experiment subsequently triggered
SError and a secondary fault in dump_dmc_reg. That probe had no successful
post-write readback and must not be counted as the original playback fault,
or as validation of the source candidate. Python byte-oriented stores are not
a suitable MMIO write primitive; no further direct writes were performed.
The complete log was saved and the device rebooted. New boot ID:
`e411e9f7-36fb-48ab-90a5-8371a301c74a`; Kodi active, NRestarts=0, taint=4096
(out-of-tree modules only), persistent remote navigation mappings present.

Next hardware gate: decoder/image build with source_trace=false, then verify
unmodified source kernel boot, HDMI menus, H.264/HEVC actual video, clean stop
back to the menu, and no new SError/Oops. Retain the USB rollback files and
leave eMMC unchanged. A successful compile alone is not playback validation.
