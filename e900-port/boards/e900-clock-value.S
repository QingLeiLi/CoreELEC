.text
.balign 8
    adr x16, .
    ldr x17, data_offset
    add x16, x16, x17
    mov w17, #0x6c63
    movk w17, #0x3d6b, lsl #16
    str w17, [x16], #4
    ldr x12, [x19, #136]
    mov x13, #16
    adr x14, hex_digits
1:  lsr x15, x12, #60
    ldrb w17, [x14, x15]
    strb w17, [x16], #1
    lsl x12, x12, #4
    subs x13, x13, #1
    b.ne 1b
    mov w17, #10
    strb w17, [x16]
    strb wzr, [x16, #1]
    ldr w17, reached_magic
    str x17, [x16, #4]
    dc cvac, x16
    dsb sy
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, #0
    mov x2, #0
    mov x3, #0
    smc #0
2:  wfe
    b 2b
.balign 8
data_offset: .quad (0x1876000 - 0xcf1350)
reached_magic: .word 0xe9230001
hex_digits: .ascii "0123456789abcdef"
