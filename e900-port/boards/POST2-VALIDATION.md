# GXLX2 POST2 isolation and source fix (59–63)

The failure is narrower than disabling all CSC/HDR processing. With the tested
P291 GXL VPU profile, accessing the G12A POST2 matrix path causes the observed
lockup. Physical absence versus missing clock/power support is not established;
the adaptation currently treats that bank as unsupported.

## Evidence

- Persistent console59 records both VD1 and OSD1 HDR bypass returning, followed
  by the CSC state update. This contradicted the earlier guess that the HDR
  bypass call itself never returned. The messages come from amcsc_pip.c called
  by amcsc.c; inspect both files when mapping logs to source.
- With disable_flush_flag=1, CSC=7 survives and VSYNC/RDMA keep running. This
  isolates register access from the policy/state processing, but is not a fix.
- Candidate61 changes only the POST2 conditional branch in mtx_setting, from
  its register-access block to an existing exit that restores all saved registers
  and the stack. One byte differs in one instruction; other matrix selectors,
  kernel text and existing DI guard remain unchanged.
- Candidate61 runs CSC=7 and disable_flush_flag=0, maintains ~60Hz VSYNC/RDMA,
  and completes the generated 60s H.264 Main 720p30 clip with normal EOF/codec
  shutdown, taint 4096 and Kodi NRestarts=0. Samples advance about 90 frames/3s;
  the last live sample at 57s has 1714 frames, followed by No vdec at EOF. Reported
  output is usually 29–30fps, with startup output latency and occasional 1fps
  counter deficits; decoder error/drop counters remain zero. This does not
  establish zero display drops, physical HDMI pixels, HDR content or audio.

## Source equivalent

linux0007 guards POST2_MTX only on GXLX2 in mtx_setting and its companion
mtx_init. CSC remains enabled. Other CPU/selector paths retain upstream writes.
The host test compiles both real upstream and patched functions and compares
complete I/O traces across CPU IDs, selectors, conversion modes, on/off and
flush states. Register tokens are synthetic; the test does not validate the
hardware map or replace an ARM kernel build. Decoder now installs nine patches.

## Diagnostic trampoline correction

The earlier DI trampoline occupied __cpu_soft_restart at Image offset 0xcf1350.
The source-level DI fix never has this problem, but the runtime diagnostic
kernel must restore that function too. The revised generator starts from the
original build and places its 28-byte stub in verified zero padding at 0xcfff00,
after __idmap_text_end and below _etext. A read-only live page-table walk confirms
that location maps to physical 0x01d7ff00 with privileged execute permitted.

Candidate63 combines that relocation with the tested POST2 branch. The original
soft-restart bytes are restored; only the DI hook, padding stub and POST2 branch
differ from the original build. A fresh boot and read-only live-RAM comparison
verify all four locations against the staged file. Kernel SHA256:
e121350b99e2cabf31e78131106d1e6e2ed56d9abeb333edc6056f6eed379a8f.
Its final playback regression remains a separate runtime check.

Old E9B0–E9B3 probe images were hash-verified and archived to STORAGE before
removal from FAT. All active scripts were checked against the normal loader
hash. The archive manifest preserves provenance; FAT free space rose to 116MiB.
An SSH observation timeout did not terminate the original archive phase: a later
read proved it finished. No duplicate mutation was inferred from the timeout.

## Delivery gate

Native source-built kernel/module/image regression is still required. Current
runtime playback uses a temporary seven-bus helper and matching media overlay;
neither is persisted. The real image must include native bus/DI/POST2 fixes,
correctly installed media modules, and the raw Image/booti packaging. The cloud
build remains user-triggered; no push or workflow dispatch was performed.
