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
