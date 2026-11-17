.text
.balign 8
    /* Address boot_args[3] using the running kernel VA alias. The original
     * startup saves x3 here; this isolated probe never continues after write. */
    adr x16, .
    ldr x17, offset_to_marker
    add x16, x16, x17
    ldr w17, marker
    str w17, [x16]
    dc cvac, x16
    dsb sy
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, #0
    mov x2, #0
    mov x3, #0
    smc #0
1:  wfe
    b 1b
offset_to_marker: .quad (0x1876018 - 0xcf1350)
marker: .word E9_LATE_MAGIC
    .word 0
