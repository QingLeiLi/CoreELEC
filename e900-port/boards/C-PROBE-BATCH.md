# Automatic C bootstrap batch (batch12)

Three independently patched images target C entry, before the kernel banner,
and before setup_arch. Each retains the original kernel and changes only one
branch and the established 128-byte isolated reset payload. Exact input Image
hash, hook instruction words, unchanged header and edit bounds are checked.
These probes do not continue normal kernel initialization after their target.

The script records an armed state in the verified E9LOG.TXT data sector before
each launch. After reset, a positive retained marker records PASS and advances
in the same boot to the next image. The final image yields PASS and Android.
An absent marker records FAIL and suppresses further attempts, including after
power loss. Missing stage/image files or failed checkpoint writes suppress the
corresponding launch. The latest stage implies earlier successful transitions;
this single file is not an append-only history. Preserve it before another test.

Build: make-c-probe-batch.py ORIGINAL_IMAGE VERIFIED_SLOT OUTPUT --mkimage PATH.
Run tests/check-c-probe-batch.py OUTPUT. Revalidate the live evidence allocation
before deploying images/records, sync, then deploy script aliases and verify
all hashes. Keep the existing verified initrd/trace DTB. Do not relocate the
ledger or use scripts with another drive. Three automatic resets are expected
if all probes pass. Allow about two minutes; on a stall use the established
power-off/remove-USB/boot-Android/reinsert procedure to collect evidence.

A missing marker is inconclusive regarding the diagnostic reset stub itself.
Source/independent disassembly establish hook sites; there is no symbol-bearing
vmlinux here. No new kernel compilation, eMMC write or host-triggered reboot.
