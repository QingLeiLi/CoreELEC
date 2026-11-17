# start_kernel entry isolation (cstart11)

Hardware dual10 confirmed the MMU-enabled marker, but no diagnostic PID1 RAM
or USB file marker was observed. Thus the next probe targets start_kernel's
first instruction at pinned Image offset 0x12b07c8. The preceding assembly
branch and first four C prologue instructions are checked before patching.

make-c-entry-probe.py ORIGINAL_IMAGE OUTPUT creates an isolated image whose
C entry branches to a 128-byte payload at 0xcf1350 in the established identity
page. This overwrites CPU restart/resume code which is unused in this isolated
primary-boot test; it never continues into normal C initialization.

The payload uses AT S1E1R and PAR_EL1 to translate its virtual code address,
branches into its physical identity alias, disables translation/data caching,
writes 0xe9120001 in reserved trace RAM, then invokes the confirmed reset SMC.
This avoids assuming a virtual kernel base or writing a physical address while
translation is active. A translation failure waits instead of using a bad PA.
A missing marker can also mean a diagnostic payload failure and is inconclusive.

Generate the existing reset ledger with --mode reset --profile cstart11.
The phase nonce/prefix prevents repeated launch after reset. Preserve previous
E9LOG.TXT and revalidate its FAT data-sector mapping before deployment. Only
replace USB payloads and script aliases. Keep the verified initramfs and trace
DTB. Do not reuse this generated script on another drive or relocated file.

Checks completed: pinned Image hash; branch target and prologue; header and
all bytes outside the two edits unchanged; stub bounds and same identity page;
assembled/disassembled translation, marker and SMC sequence; script CRC and
shell syntax; actual generated script with cold start, retained marker,
missing marker, unsupported reader and failed-write command stubs. Hardware
results pending. No cloud compile or eMMC change is needed.
