.text
.balign 8
    /* Translate this code's virtual alias, then branch into the existing
     * identity map before disabling translation. No guessed kernel VA base. */
    adr x12, physical_entry
    at s1e1r, x12
    isb
    mrs x13, par_el1
    tbnz x13, #0, failed
    ubfx x13, x13, #12, #36
    lsl x13, x13, #12
    and x12, x12, #0xfff
    orr x13, x13, x12
    br x13
physical_entry:
    mrs x15, sctlr_el1
    bic x14, x15, #1
    bic x14, x14, #4
    dsb sy
    msr sctlr_el1, x14
    isb
    ldr x16, trace_address
    ldr w17, marker
    str w17, [x16]
    dsb sy
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, #0
    mov x2, #0
    mov x3, #0
    smc #0
failed:
    wfe
    b failed
trace_address: .quad 0x074ff000
marker: .word 0xe9120001
    .word 0
