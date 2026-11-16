# USB boot probes

All probes return to the existing boot command without saving the environment or launching CE.

- `write`: attempts a USB FAT marker and waits 12 seconds. Hardware: Android boots after an approximately 12-second extra pause, but no marker is created. FAT-write success remains unconfirmed.
- `capabilities`: appends command-help results to transient Android bootargs. Hardware: `e9probe=cap02` appears in `/proc/cmdline`, proving the USB script executes and this return channel works. **The original `absent` labels are invalid**: U-Boot 2016.03 `common/command.c` makes `cmd_usage()` return 1, including when help exists. Current labels say `unconfirmed`; do not use this mode to establish absence.
- `preflight`: loads the existing raw CE Image at 0x11000000, legacy uInitrd at 0x15000000 and DTB at a scratch address 0x18000000. It checks the legacy initrd with `iminfo` and appends load results and hexadecimal lengths to Android bootargs. It does not change the active FDT. Deployment verified; cold-boot hardware results pending.

Generate with `scripts/make-usb-probe.py OUTPUT --mkimage PATH --mode preflight`. Copy E9INPUT.TXT and all three script aliases to the USB FAT root. Expected tag is `e9probe=pre03`. `iminfo` failure does not distinguish unavailable command from rejected image; successful CRC validation is positive evidence. Successful loading and initrd CRC do not prove the DTB is suitable or the kernel will execute.
