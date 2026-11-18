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

## Actual binary decision tree (bisect14)

`--late --bisect` supplies four ordered candidates between rest_init and the
first init execution attempt: kernel_init_freeable entry; before smp_init;
after main initcalls before opening console; before userspace exec attempt.
It starts with the second candidate, the middle boundary of this four-point
partition. PASS selects the upper subinterval; absence of the expected marker
selects the lower subinterval. It never runs all four in order. Maximum three
physical attempts narrow the result to adjacent candidate boundaries.

Decision tree (candidate indices 0..3): start 1; 1 PASS -> 2, 1 FAIL -> 0;
2 PASS -> 3, 2 FAIL -> finish; either result at 0 or 3 finishes. Terminal
PASS/FAIL records suppress repeat launches. All selected hooks and their
original instruction words are pinned. The latest durable outcome plus this
decision tree identifies the narrowed interval; host archives preserve the
preceding evidence before deploying another test.

This is a reachability search, not proof of fault causality. FAIL means the
expected retained marker was not observed. Reset, RAM retention, physical
relocation conventions and probe failure remain possible explanations.
A terminal all-PASS path reaches the first userspace exec attempt; it does
not prove /init actually executes or that a diagnostic initramfs is valid.

## Narrowed SMP/initcall search (bisect15)

bisect14 returned stage 2 FAIL, implying stage 1 reached before smp_init and
no observed marker after all main initcalls. `--late --bisect --initcalls`
searches only that interval with four ordered candidates: smp_init return;
before main initcall levels; levels 0..3 completed; levels 0..5 completed.
Start at candidate 1, branch down to 0 on absent marker or up to 2/3 on PASS.

The last two images replace the loop comparison at 0x12b0d10 with a branch
into a conditional payload. x21 contains the incremented level index. A target
value 4 or 6 resets; otherwise the payload reexecutes the exact original
`cmp x21,#8` and branches back to the original b.ne at 0x12b0d14, preserving
the normal loop flags. All code outside the hook and scratch payload is
unchanged. Source and pinned disassembly identify the inline loop. Tests
check both conditional prefixes, return destinations, decision branches,
wrong marker handling, terminal states and failed writes. As before, absence
of a marker is not definitive proof of a kernel fault.

## Function-count binary split (bisect16)

bisect15 passed levels 0..5. Recovered RELA entries from the pinned Image
identify the level boundary table at file offset 0x1312c18, with 400 level-6
functions and 51 level-7 functions. These counts are asserted by the builder.
`--late --bisect --functions` defines candidates after 112, 225, 338 device
initcalls, and after all device plus 25 late initcalls. The same middle-first
tree selects the needed candidates rather than running them sequentially.

At the loop's original `cmp x25,x0` (0x12b0cf4), the conditional payload checks
x21 (level), then computes x25 minus the table's start pointer loaded via x22.
Only the matching level and byte count trigger a reset. Non-target iterations
restore the original comparison and return to b.hs at 0x12b0cf8. The payload
uses x16 only as a caller-clobbered temporary; it preserves x0/x21/x22/x25 and
the loop's condition flags on the normal path. The marker VA adjustment
accounts for the extra 32-byte conditional prefix. Pinned instruction words,
branch destinations, counter operands and full generated-controller branches
are tested. These tests do not establish hardware success or fault causality.

## Narrow function window (bisect17)

bisect16 observed 225 device initcalls completed, but no 338-completed marker.
`--window 225:338` with the function probe options creates candidates at
253, 281, 309 and 323 completed callbacks. The middle-first controller starts
at 281. This parameterized mode currently uses a distinct bisect17 magic and
record prefix; prepare a distinct profile/magic before reusing another window.

Each image differs from its bisect16 counterpart only in the existing 128-byte
scratch payload. Deployment may verify all old full-file hashes, upload four
128-byte deltas, use filesystem dd with conv=notrunc,fsync, verify new full-file
hashes, and only then replace script aliases. This is not raw block writing.
Keep normal kernel/initrd/DTB files and preserve the preceding evidence first.
No new reboot is allowed until all records and scripts also pass full hashes.

bisect17 returned 281-completed PASS and no 309-completed marker. The next
window `281:309 --run-id 18` defines counts 288, 295, 302, 305 and starts at
295. `--run-id` assigns a distinct profile prefix and marker magic to avoid
confusing an earlier pass with the new window. Run IDs must not be reused for
a different window while old on-device state remains. Image deltas are still
restricted to the existing 128-byte payload and fully hash checked.

bisect18 observed 302 completed device callbacks, but no 305-completed marker.
The three candidates' offsets and printk function-name strings identify
303 di_module_init, 304 dim_module_init, 305 dil_init. The final discriminator
uses `--window 302:305 --run-id 19 --counts 302,303,304,305`. The 302 boundary
is a redundant lower-bound control; remaining probes check each callback
completion. A positive/negative adjacent boundary isolates a callback without
skipping or changing its implementation. It still does not exclude probe
interference or non-deterministic behavior. Old evidence is archived first.

## DI registration/probe split (bisect20)

bisect19 observed 303-completed marker absent, then 302-completed PASS. The
pinned callback is di_module_init. RELA at the registered di_driver structure
identifies di_probe at 0xcd4904. The source and disassembly agree that
platform_driver_register invokes the matching platform probe.

`--late --bisect --di-probe` targets probe entry, after reserved-memory setup,
before di_hw_init, and immediately after di_hw_init. The same binary tree
starts at the second candidate. Missing an interior point can include an
ordinary early error return, not necessarily a crash or hang; record it only
as an unobserved milestone until a controlled bypass/log test confirms cause.
The hardware-init call is identifiable from its two bool arguments and source
position following request_irq; early DT/IRQ/CMA setup runs unmodified.

When updating from bisect19, restore the old loop comparison at 0x12b0cf4,
install one new four-byte branch at the selected probe site and replace the
128-byte reset payload. Verify old/full new hashes and preserve the preceding
ledger. No initcall is skipped or driver disabled in this test.

## DI setup subregion (bisect21)

bisect20 passed after reserved-memory initialization and did not observe the
pre-di_hw_init marker. `--di-probe --di-setup` selects four stable milestones:
CMA processing complete before IRQ mapping; DT/clock-property processing
complete before canvas setup; canvas complete before local metadata allocation;
sysfs and nr_drv_init complete before buffer arithmetic and IRQ registration.
The root is the second milestone. Pinned disassembly checks each hook and the
old hooks are restored before installing the new ones. Early error branches
can bypass later milestones, so absence remains inconclusive without further
operation-specific confirmation. No hardware setup is bypassed or modified.

## IRQ/RDMA/VPU clock split (bisect22)

bisect21 observed CMA completion but not later DT/clock-property completion.
`--di-probe --di-clocks` places candidates after IRQ mapping, after RDMA
registration, immediately before VPU clkb enable, and after that enable path.
The second candidate is the middle-first root. Source di_get_vpu_clkb logs an
error for a failed clk_get("vpu_clkb_composite"), while its caller still uses
that pointer. This is a hypothesis only; the probe does not alter clock calls,
CPU identity, driver matching or DT properties. Old hook instructions are
restored and all image changes confined to new hooks/reset payloads.

## Actual clock handle capture (clock23)

bisect22 passed immediately before the VPU clkb enabling sequence and lacked
its after marker. The diagnostic DT has no deinterlace clocks/clock-names.
Source logs clk_get failure but the caller still invokes clk_prepare_enable.
To verify the hypothesis, make-clock-value-image.py patches the same before
point to snapshot the handle at di_devp+136 without dereferencing that handle.

The 148-byte stub formats `clk=XXXXXXXXXXXXXXXX\n` at the mapped boot_args
region and writes the reset marker at offset 24. It cleans the cache line,
requests reset and never calls the clock API. The clock23 reset ledger verifies
the marker, imports only 21 ASCII bytes from the matching physical alias with
`env import -t`, and appends e9_clock to the Android command line. No environment
is saved. `unavailable` means no value was recovered. The durable ledger still
records reachability; the pointer itself is returned via volatile bootargs,
so collect it before another power cycle. No raw pointer is dereferenced.

The complete image is pinned, edit bounds and offsets checked, disassembly
reviewed, hex-loop edge vectors tested, and the actual generated shell exercised
for cold boot, captured ERR_PTR text, absent marker and no-repeat handling.
The standalone generator reproduces the deployment image exactly. Hardware
snapshot value remains pending.

## Controlled missing-clock guard (guard24)

clock23 returned e9_clock=fffffffffffffffe, confirming ERR_PTR(-ENOENT) in the
vpu_clkb field before its enable path. guard24 changes only that path for a
controlled test. The original clk_is_enabled BL at 0xcd4e04 branches to a
28-byte guard: NULL or IS_ERR_VALUE causes the saved handle to be cleared and
control to continue after the clock-enable block. Valid pointers retain the
original clk_is_enabled call and exact return address, followed by the
unchanged prepare/enable sequence. No driver initcall is disabled. This is
not the final SoC clock-topology correction or a proposal to ignore all errors.

The trial uses the existing diagnostic PID1 initramfs, checks its marker and
returns to Android with a persistent single-attempt guard. If PID1 runs, it
tries to write E9USER.TXT, E9DMESG.TXT and E9CMD.TXT before rebooting. The same
trace DTB protects the RAM marker. Preserve existing clock23 cmdline and file
evidence before replacing USB scripts. Host checks cover emitted pointer
range guard, NULL/ERR boundary vectors, valid-call return address, full Image
edit bounds, initramfs proof contents and actual recovery shell. No source
build, eMMC write or bootloader/env modification is involved. Hardware trial
outcome is pending; a later failure may expose additional unsupported paths.

## Normal CE init and framebuffer reservation (ce25)

Guard24 reached diagnostic PID1 and exported a log with di_probe:ok. The log
shows DI CMA allocated 0x3d800000..0x40000000 before the framebuffer allocator
requested 0x3dc00000..0x40000000 and failed. make-full-boot-trial.py changes
only the framebuffer reservation to a fixed reg with reusable shared-DMA
semantics, removing its size/alignment/alloc-ranges properties. Fixed reg
regions are reserved before dynamic CMA allocation; the DI allocator can
choose a different range. Other board properties stay unchanged except the
existing reserved trace area's compatible value, as checked by FDT decoding.
This hardware trial still needs to confirm CMA accepts the fixed framebuffer.

The same generator starts from the pinned original CE initramfs and changes
only /init: add a RAM entry marker, export the before/after boot-step checkpoints
to /flash once mounted, and record before_switch_root plus a second RAM marker.
All other original entries are preserved. This is the normal CE flow, not the
diagnostic PID1 that immediately reboots. It uses the successful clock-guard
kernel, full CE boot/disk labels and HDMI bootargs. It does not enable eMMC.

The ce25 reset ledger launches the attempt once and falls back to Android only
if the bootloader runs again. Successful CE does not run Android ADB and will
remain running. Diagnose with HDMI/SSH and E9BOOT.TXT/E9CELOG.TXT/E9CECMD.TXT;
on a stall use established USB-removed Android recovery, reinsert the drive,
and preserve logs. No automatic reboot is injected into normal CE userspace.
Host checks cover CPIO preservation/CRC, shell syntax, FDT changes, cold and
both retained stage markers, correct labels and unchanged disabled eMMC/SDIO.
Complete Kodi/HDMI playback remains unvalidated.

## Display-disabled comparison with early init logs (ce26)

ce25 produced HDMI black and no logs after /flash. Only before_booti survived
manual Android recovery, so failure before PID1 cannot be distinguished from
an initramfs stall before mounting /flash. ce26 is a temporary comparison:
same guarded kernel, same CE flow and framebuffer reservation, but meson-fb
and amhdmitx status disabled. Decoded FDT comparison confirms those are the
only DT differences from ce25; eMMC/SDIO stay disabled.

An early PID1 background logger waits for the USB block device, verifies the
per-run proof token before writing E9EARLY.TXT and E9STAGE.TXT, then stops when
normal /flash becomes available. The original init sequence and switch_root
are retained. Logging cannot capture a pre-PID1 kernel hang; absence remains
inconclusive. HDMI black is expected for this comparison. Observe network/SSH
or recover Android and collect files before repeating. This is not the final
user-facing configuration or an assertion that graphics caused ce25 failure.

## Isolate CE bootargs (control27)

ce26 is Android after recovery and no post-booti evidence was recovered, even
with graphics disabled. This does not prove a graphics fault or pre-PID1 hang.
control27 returns to the verified guard24 kernel and original trace DT, plus
the same diagnostic PID1. Only bootargs change to the full CE bootargs used
in ce25. Instrumentation names/markers are versioned to avoid stale proof:
E9C27.TXT, E9D27.TXT, E9A27.TXT, and marker e9270001. The original diagnostic
initrd is SHA256 pinned; only its init text (output names), proof text and
marker file differ. All other archive entries/metadata remain unchanged.

Prepare with make-control-initrd.py VERIFIED_DIAGNOSTIC_INITRD OUTPUT --mkimage
PATH; generate reset ledger profile control27. Verify the actual on-device
kernel and original trace DT match the successful reference before replacing
scripts. This test requests automatic reboot after logs, unlike normal CE.
The lack of a new marker/file still cannot independently prove fault cause.

## Isolate framebuffer DT reservation (control28)

control27 proved diagnostic PID1 and log export with CE bootargs and the old
trace DT. control28 changes only the DT framebuffer reservation to the fixed
reg from ce25. The guarded kernel and CE bootargs are unchanged. Diagnostic
PID1 only versions output names and RAM markers: E9C28.TXT/E9D28.TXT/E9A28.TXT,
marker e9280001. FDT decoding confirms that framebuffer reservation properties
are the only differences versus the passing control27 DT; both display nodes
remain enabled. Keep this separate from the previous headless/normal-init
attempts so failure or success has an interpretable single-variable boundary.
