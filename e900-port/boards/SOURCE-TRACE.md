# Source boot diagnostics

Workflow option `source_trace=true` is restricted to profile `decoder`.
It adds `0004-e900-source-boot-trace.patch`; ordinary builds remain unchanged.
Build target `linux` compiles the kernel first; use `image` when a full USB
image is required. Compatible toolchains are retained; linux and media modules
are invalidated when this patch changes.

The source patch records normal-RAM stages at 0x074ff000:

- 0xe9110001: primary ARM64 entry, before argument preservation.
- 0xe9110002: CPU setup completed, before the MMU switch.
- mapped global `e900_virtual_boot_stage=3`: virtual-address entry reached.
- 0xe9110004: setup_arch completed; printk reports the virtual stage.

The board DT keeps a separate no-map trace page and shortens the preceding
ramoops reservation to avoid overlap. The early physical stores use only
x16/x17; after switching mappings, assembly stores through a virtual symbol.
No early filesystem calls or raw disk writes are added to the kernel.

Add `initcall_debug ignore_loglevel loglevel=8 panic=10` to diagnostic bootargs.
Preserve ramoops with the source-build board DT (the old binary trace DT
explicitly disables ramoops and must not be substituted).

`e900-userspace-init.src.in` is the diagnostic PID1 source used by the pending
USB repackaging flow. It writes a RAM marker, waits up to 60 iterations for
USB storage, checks a per-run nonce before writing E9USER.TXT, and exports
dmesg/cmdline before rebooting. It replaces normal CE initialization for this
test only. It is not automatically included by the kernel-only workflow.
Preparing it against a newly built kernel/initramfs still requires validating
that build's artifacts; do not reuse the old pinned binary patch generator
on a newly compiled Image.

Status: patch application to pinned sources and cache invalidation checks pass.
Full ARM64 compile, source-build initramfs packaging and hardware verification
remain pending. No cloud workflow was started and no device files were changed
while preparing this source option.
