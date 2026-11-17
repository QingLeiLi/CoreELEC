.text
.balign 8
#ifdef E9_FN_LEVEL
    cmp x21, #E9_FN_LEVEL
    b.ne 3f
    ldr x16, [x22]
    sub x16, x25, x16
    cmp x16, #E9_FN_BYTES
    b.eq 2f
3:  cmp x25, x0
    .inst E9_RETURN_BRANCH
2:
#endif
#ifdef E9_LEVEL_PREFIX
    cmp x21, #E9_LEVEL_PREFIX
    b.eq 2f
    cmp x21, #8
    .inst E9_RETURN_BRANCH
2:
#endif
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
#if defined(E9_FN_LEVEL)
offset_to_marker: .quad (0x1876018 - 0xcf1370)
#elif defined(E9_LEVEL_PREFIX)
offset_to_marker: .quad (0x1876018 - 0xcf1360)
#else
offset_to_marker: .quad (0x1876018 - 0xcf1350)
#endif
marker: .word E9_LATE_MAGIC
    .word 0
