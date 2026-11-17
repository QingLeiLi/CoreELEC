/* Isolated probe in the same identity-mapped 4KiB page as __enable_mmu. */
.text
.balign 8
    mrs x15, sctlr_el1
    tbnz x15, #0, 2f
1:  wfe
    b 1b
2:  bic x14, x15, #1
    bic x14, x14, #4
    dsb sy
    msr sctlr_el1, x14
    isb
    .balign 8
    ldr x16, trace_address
    ldr w17, mmu_magic
    str w17, [x16]
    dsb sy
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, #0
    mov x2, #0
    mov x3, #0
    smc #0
3:  wfe
    b 3b
trace_address: .quad 0x074ff000
mmu_magic: .word 0xe9100001
    .word 0
