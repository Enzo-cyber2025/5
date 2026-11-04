.section .rodata
message:
    .ascii "BOX64_X86_64_OK\n"
message_len = . - message

.section .text
.globl _start
.type _start, @function
_start:
    mov $1, %rax
    mov $1, %rdi
    lea message(%rip), %rsi
    mov $message_len, %rdx
    syscall
    mov $60, %rax
    xor %rdi, %rdi
    syscall
.size _start, .-_start
