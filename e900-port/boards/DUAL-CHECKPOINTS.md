# MMU and diagnostic /init in one physical test

This USB-only package uses the verified old kernel; no source rebuild needed.
`make-dual-checkpoint.py` prepares an isolated MMU binary probe and repacks the
same initramfs with diagnostic PID1. Scripts are deployed separately after
`tests/check-dual-checkpoint.py KIT ORIGINAL_IMAGE` and live FAT slot checks.

Phase 1 replaces the __enable_mmu return with a branch within its identity
mapped 4KiB page. The stub checks SCTLR.M, disables translation/cache before
accessing the reserved physical trace page, writes e9100001 and requests the
verified firmware reset. It overwrites an unused cpu_soft_restart region for
this isolated test only; it is not a production kernel modification.

On reset, retained marker verification produces E9MMU.TXT proof. The script
then tries the original unmodified Image with a diagnostic initramfs. PID1
writes a RAM marker and attempts to mount only USB disk partitions. A nonce
check precedes E9USER.TXT, E9DMESG.TXT and E9CMD.TXT writes. It requests reboot
and never executes the original CE init; that file is retained in the archive.

Persistent phase prefixes prevent retry loops. The script does not attempt
phase 2 without phase 1 proof. Each boot call requires successful checkpoint
writing. If RAM retention or USB initialization fails, absence of proof is
inconclusive. No eMMC/raw system writes are performed. Kernel panic timeout
is 10 seconds for this diagnostic. USB discovery waits up to 60 iterations;
mount attempts can add time. Allow about two minutes before manual recovery.

After a stall, power off, remove USB, boot Android and reinsert the drive.
Read evidence before changing files or retry flags. Do not relocate evidence
files or reuse these scripts on another USB drive: guarded sector addresses
are bound to the verified FAT allocation.

Host checks: exact original Image pin; MMU instruction sequence and scratch
region hash; same identity page; legacy script/initrd CRC; preserved original
CPIO entries; shell syntax; actual generated shell with cold, warm, missing
markers, phase guards and write-failure branches. Hardware test pending.
