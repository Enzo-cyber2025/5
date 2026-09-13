.text
.globl check_callee_saved
.type check_callee_saved,@function
check_callee_saved:
    push %rbp
    mov %rsp, %rbp
    push %rbx
    sub $8, %rsp
    mov %rdi, %rax
    mov %rsi, %rdi
    movabs $0x1122334455667788, %rbx
    call *%rax
    mov %rbx, %rax
    add $8, %rsp
    pop %rbx
    pop %rbp
    ret
.size check_callee_saved, .-check_callee_saved
.section .note.GNU-stack,"",@progbits
