# USB boot probes

All probes return to the existing boot command without saving the environment or launching CE.

- `write`: attempts a USB FAT marker and waits 12 seconds. Hardware: Android boots after an approximately 12-second extra pause, but no marker is created. FAT-write success remains unconfirmed.
- `capabilities`: appends command-help results to transient Android bootargs. Hardware: `e9probe=cap02` appears in `/proc/cmdline`, proving the USB script executes and this return channel works. **The original `absent` labels are invalid**: U-Boot 2016.03 `common/command.c` makes `cmd_usage()` return 1, including when help exists. Current labels say `unconfirmed`; do not use this mode to establish absence.
- `preflight`: loads the existing raw CE Image at 0x11000000, legacy uInitrd at 0x15000000 and DTB at a scratch address 0x18000000. It checks the legacy initrd with `iminfo` and appends load results and hexadecimal lengths to Android bootargs. It does not change the active FDT. Deployment verified; cold-boot hardware results pending.

Generate with `scripts/make-usb-probe.py OUTPUT --mkimage PATH --mode preflight`. Copy E9INPUT.TXT and all three script aliases to the USB FAT root. Expected tag is `e9probe=pre03`. `iminfo` failure does not distinguish unavailable command from rejected image; successful CRC validation is positive evidence. Successful loading and initrd CRC do not prove the DTB is suitable or the kernel will execute.

Hardware pre03 result: USB device 0, Image 28,051,464 bytes, DTB 56,995 bytes,
uInitrd 3,901,932 bytes; all lengths match. `iminfo` returned failure, so CRC
validation remains unconfirmed. Android boot and the return channel worked.

## ARM64 entry trace (entry04 / entry05)

`scripts/make-entry-trace.py VERIFIED_BOOTI_KIT OUTPUT --mkimage PATH` accepts
only the pinned successful build's raw Image, DTB and initramfs. It replaces the
initial unconditional branch with a branch to a 40-byte appended trampoline,
which writes `0xe9000001` to normal RAM at `0x074ff000`, executes a DSB, then
branches to the original entry target. x0..x3 and the original header fields
remain intact; x16/x17 are scratch registers. The append fits inside the
existing Image size and is executed before normal BSS initialization.

The diagnostic DTB changes only the existing 1MiB ramoops reservation's
compatible value to `e9trace`, keeping the region reserved and preventing
ramoops from consuming the marker. This deliberately sacrifices pstore for
this one entry-stage test. The DTB is loaded at `0x18000000` to preserve the
existing Android DTB at `0x01000000` if the script returns.

The script first checks a retained marker. Otherwise it loads the files,
loads an eight-byte armed marker (`0xe9000000`, zero padding) and verifies RAM
readback before calling `booti`. All writes target USB files or normal RAM;
there are no persistent env, eMMC or MMIO writes.

If the bootloader reexecutes the USB script after a warm reset **and** RAM is
retained, Android receives `e9probe=entry05` with one of:

- `e9_entry=reached`: the injected ARM64 entry instructions ran; this does not
  prove normal Linux initialization or a working display.
- `e9_entry=not_observed`: the armed marker remains; no entry write was observed.
- `e9_booti=returned`: the booti command returned; this is not evidence of a
  successful kernel jump.
- `e9_trace=...`: a prerequisite failed; see the script for the exact stage.

Neither RAM retention nor warm-reset USB reexecution has been established on
this device. Missing results are inconclusive. If two resets occur, remove USB
and boot Android rather than repeating the test. Restore the pre03 script
aliases to return to the loading-only probe. No cloud rebuild is required.

Host validation: script CRC, pinned inputs, reservation-preserving DTB change,
branch destinations, append bounds, unchanged original code after the initial
branch, and Clang ARM64 assembly byte comparison. Hardware execution pending.

Hardware entry04 result: `e9_trace=setexpr_unavailable`. Its initial unary
`setexpr.l` command failed, so this probe did not call booti. This establishes
no kernel failure and does not prove command absence.

Entry05 uses binary `setexpr name *address + 0`, with direct `itest.l` memory
comparisons as an alternative. Either reader must positively verify the seed
before booti is allowed. Seed padding is zero because some old implementations
dereference an unsigned long even for `.l` accesses. Revised script control flow
was tested with command stubs covering both readers, no supported reader, warm
markers, file load failure and boot command return. The instrumented kernel
and diagnostic DTB are unchanged from entry04; only the seed and script aliases
need replacing. Entry05 deployed and hash checked; hardware boot pending.

Hardware entry05 observation: Android logo for roughly ten seconds; USB was
removed and power cut before Android booted. The resulting Android command
line has no probe tag and its RAM no longer contains a diagnostic magic.
This does not establish entry success or failure, nor prove a kernel hang.

## Persistent USB evidence file (usb06)

The earlier `fatwrite` probe did not create its file. `usb06` instead tests
the bootloader USB storage block write path, with a preallocated 512-byte
`E9LOG.TXT`. Preparation creates the file using Android's normal filesystem,
reads the MBR/BPB/FAT/root directory, checks that it occupies one cluster, and
verifies that its first data sector matches a fresh random-nonce payload.
Raw disk reads during preparation are read-only.

`scripts/prepare-usb-write-probe.py --adb-serial DEVICE --mkimage PATH OUTPUT`
creates the two test files on the mounted USB and prepares scripts locally.
It does not deploy scripts or reboot. The generated script is bound to the
current USB layout. Do not use it on another drive, reformat the drive or move
the evidence file without regenerating the slot mapping.

At boot, the script selects USB storage 0, loads both 512-byte files, reads the
mapped sector and uses `cmp.b` to compare it with the FAT-loaded evidence file
before writing exactly one sector. It reads back and compares the replacement
as well. Failure of any prerequisite prevents the write. Neither the partition
table, FAT nor eMMC is a write target. The probe does not execute CE and returns
to Android with `e9probe=usb06 e9_write=...`; a successful file update will
remain readable after a power cycle.

This first test proves only whether a bootloader checkpoint can be persisted.
It cannot directly record an early Linux panic before USB drivers initialize.
Integration with pre-handoff checkpoints and retained-RAM entry results remains
pending successful hardware validation. Parser bounds and script guards have
host tests; local image mapping and the actual USB file/sector mapping were
checked. usb06 deployed and hashes verified; hardware write result pending.

Hardware usb06 result: `e9probe=usb06 e9_write=passed`; E9LOG.TXT has the
expected replacement contents and SHA256, identical to E9NEXT.BIN. The guarded
USB block-write checkpoint path is confirmed on this device.

## Persistent kernel boot ledger (ledger07)

`scripts/make-usb-ledger-boot.py VERIFIED_SLOT_JSON OUTPUT --mkimage PATH`
requires an explicitly hardware-verified slot. It expands the exact usb06
write/readback guard into the entry05 script at 19 diagnostic positions,
including before each RAM reader, file loads, booti, failures and retained
entry observations. Generated 512-byte E9Sxxx.BIN payloads contain the stage
description and the slot nonce. The single E9LOG.TXT keeps the latest written
checkpoint; it is not a complete chronological log.

Before deploying, the live FAT allocation and current evidence bytes must be
revalidated against the slot. Upload the stage payloads and three script
aliases without replacing E9LOG.TXT or changing its allocation. Keep the
entry05 trace Image, diagnostic DTB, seed and verified initramfs. If a
checkpoint cannot be verified, the script suppresses the kernel call. A
before_booti record proves preparation reached that point, not that the CPU
entered Linux. An entry observation still depends on retained RAM; there is
no direct USB driver available to the injected entry instructions.

On a stalled attempt, wait 60 seconds. If Android does not return, power off,
remove USB and boot Android; then reinsert this same drive and read E9LOG.TXT
without overwriting it. Unlike the RAM trace, persisted checkpoints can
survive that recovery. Do not use these generated scripts on a different
drive or after reallocating the evidence file.

Host checks ran the actual generated shell source with command stubs for
both readers, missing reader, warm markers, file load failures, block-write
failures and comparison failures. Shell syntax and legacy script CRC passed.
The live allocation was revalidated and all 26 deployed file hashes matched.
ledger07 hardware boot result remains pending; no eMMC change or reboot was
performed during deployment.

Hardware ledger07 result: the saved file exactly matches checkpoint 012,
`before_booti`. File loads and RAM marker readback succeeded; no return
checkpoint was recorded. This bounds the failure to the boot command or what
it executes, but does not establish that Linux entry was reached. The file
was preserved privately before preparing the next test.

## Isolated entry/reset payload (reset08)

This is a bootloader-handoff test, **not a usable CE boot**. The original
pinned Image header, text offset, size, load addresses, DTB and initramfs are
retained. The initial branch now targets a 64-byte appended ARM64 payload
which writes `0xe9080001` to the trace address, issues a barrier and invokes
SMC `0x84000009` with x1..x3 zero. It does not branch back to Linux. If the
reset call returns, it waits in a WFE loop. The live working Android DT
explicitly declares `/aml_restart/sys_reset = 0x84000009` and the SMC method;
the firmware reset identifier was not guessed.

Build with `scripts/make-reset-entry-image.py ORIGINAL_IMAGE IMAGE_OUTPUT`,
then `scripts/make-usb-ledger-boot.py VERIFIED_SLOT LEDGER_OUTPUT --mkimage PATH
--mode reset`. Upload the image, seed, E9Rxxx.BIN payloads and script aliases,
keeping the existing diagnostic DTB and initramfs. Revalidate the file-slot
mapping and deployed hashes as for ledger07.

All reset08 records share a 64-byte attempted prefix with the slot nonce.
The script compares this prefix before writing any new checkpoint. If it
already matches, it suppresses another payload launch regardless of RAM
retention, checks the reset-entry marker and returns to Android. This is a
persistent no-repeat guard; it does not guarantee that a reset reexecutes
the USB script or that the marker survives reset. A positive observed marker
proves ARM64 payload entry. A missing marker remains inconclusive. Preserve
E9LOG.TXT after an attempt; do not reset the guard before collecting results.

Host checks verify the assembled payload bytes, unchanged original code and
header (apart from the initial branch), append bounds, SMC arguments, guard
ordering before writes, cold attempt, warm result, power-loss/no-marker path,
unsupported RAM reader, file-load failures and checkpoint-write failures.
ledger07 generation was regression tested. Hardware reset08 result pending.

Hardware reset08 result: automatic return to Android with
`e9probe=reset08 e9_entry=reached e9_log=passed`; persisted checkpoint 003
matches `ARM64_entry_marker_observed_after_reset`. This positively confirms
ARM64 payload execution, the firmware reset and retention/reexecution of the
RAM marker on this reset path. It does not confirm any normal Linux startup.

## Before-MMU milestone (premmu09)

Use `--profile premmu09` with both reset-image and reset-ledger generators.
The image header and its original branch to stext are unchanged. At the
pinned stext file offset `0x12b0000`, the actual eight instructions match the
source sequence: preserve boot args, el2_setup, physical offset/misalignment,
boot-mode flag, initial page tables, CPU setup, branch to primary switch.
The generator pins all eight exact words and replaces only the final branch
at `0x12b001c` with a branch to the appended reset payload. This executes the
real early assembly through `__cpu_setup`, then resets before entering
`__primary_switch` or enabling the MMU. No normal C initialization is reached.

Marker `0xe9090001`, the premmu09 durable prefix and separate Image filename
prevent an old reset08 result from being mistaken for this milestone.
The same persistent no-repeat guard is retained. Both profiles pass patch
bounds, payload/SMC and shell control-flow tests. Source and independent LLVM
disassembly agree on the patch site. The previous positive reset08 evidence
was preserved and the live slot revalidated before deployment. premmu09
hardware result remains pending.
