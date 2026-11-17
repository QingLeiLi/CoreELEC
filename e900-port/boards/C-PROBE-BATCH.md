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

## Later four-way split (batch13)

Generate with `--late`. Hooks target setup_arch return, boot-parameter
processing completion, interrupt enabling, and the call to rest_init. The
exact original instruction word at each hook is checked along with the whole
Image hash. These stages must not use the old identity-map reset stub because
setup_arch removes TTBR0 identity mappings.

Instead the isolated payload addresses boot_args[3] through the current kernel
VA alias using a PC-relative offset, writes a stage-specific magic, cleans the
cache line to PoC, then invokes the verified firmware reset. It does not
continue the kernel. Before booting Android, U-Boot checks physical addresses
0x028f6018 and 0x029f6018, covering the two old DRAM-base conventions with the
Image text_offset. These are not hardware registers. A missing marker can
mean unexpected relocation, marker corruption or probe failure, so it must
not alone be reported as a proven kernel fault. Positive stage-specific
markers are required for automatic advancement. One ledger result summarizes
progress; the old evidence is saved on the host before replacing payloads.

No cloud build is needed. The four-stage controller and the previous three-
stage controller pass the same cold/warm/no-repeat/write-failure tests, with
an additional wrong-stage magic rejection case for batch13. Deployment hashes
must be verified before the explicitly authorized ADB reboot.
