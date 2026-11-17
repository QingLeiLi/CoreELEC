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
