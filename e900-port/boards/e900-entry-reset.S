/* Same Image relocation/header; execute no normal Linux initialization. */
.text
#ifndef E9_TRACE_MAGIC
#define E9_TRACE_MAGIC 0xe9080001
#endif
.balign 8
    ldr x16, trace_address
    ldr w17, entered_magic
    str w17, [x16]
    dsb sy
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, #0
    mov x2, #0
    mov x3, #0
    smc #0
1:  wfe
    b 1b
trace_address: .quad 0x074ff000
entered_magic: .word E9_TRACE_MAGIC
    .word 0
