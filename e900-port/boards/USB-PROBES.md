# USB boot probes

All probes return to the existing boot command without saving the environment or launching CE.

- `write`: attempts a USB FAT marker and waits 12 seconds. Hardware: Android boots after an approximately 12-second extra pause, but no marker is created. FAT-write success remains unconfirmed.
- `capabilities`: appends command-help results to transient Android bootargs. Hardware: `e9probe=cap02` appears in `/proc/cmdline`, proving the USB script executes and this return channel works. **The original `absent` labels are invalid**: U-Boot 2016.03 `common/command.c` makes `cmd_usage()` return 1, including when help exists. Current labels say `unconfirmed`; do not use this mode to establish absence.
- `preflight`: loads the existing raw CE Image at 0x11000000, legacy uInitrd at 0x15000000 and DTB at a scratch address 0x18000000. It checks the legacy initrd with `iminfo` and appends load results and hexadecimal lengths to Android bootargs. It does not change the active FDT. Deployment verified; cold-boot hardware results pending.

Generate with `scripts/make-usb-probe.py OUTPUT --mkimage PATH --mode preflight`. Copy E9INPUT.TXT and all three script aliases to the USB FAT root. Expected tag is `e9probe=pre03`. `iminfo` failure does not distinguish unavailable command from rejected image; successful CRC validation is positive evidence. Successful loading and initrd CRC do not prove the DTB is suitable or the kernel will execute.

Hardware pre03 result: USB device 0, Image 28,051,464 bytes, DTB 56,995 bytes,
uInitrd 3,901,932 bytes; all lengths match. `iminfo` returned failure, so CRC
validation remains unconfirmed. Android boot and the return channel worked.

## ARM64 entry trace (entry04)

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
loads a four-byte armed marker (`0xe9000000`) and verifies RAM readback with
`setexpr.l` before calling `booti`. All writes target USB files or normal RAM;
there are no persistent env, eMMC or MMIO writes.

If the bootloader reexecutes the USB script after a warm reset **and** RAM is
retained, Android receives `e9probe=entry04` with one of:

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
