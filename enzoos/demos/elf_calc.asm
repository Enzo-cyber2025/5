; =============================================================================
;  EnzoOS — demos/elf_calc.asm: payload do CALC.RUN (ELF x86-64, ET_EXEC,
;  sem libc — syscalls int 0x80 do EnzoOS).
;
;  Tabela de quadrados e Fibonacci + fatorial de 12.
; =============================================================================
BITS 64
org 0x10000000
default rel

entry:
        lea rsi, [msg1]
        mov rdx, msg1_len
        call con_write
        ; quadrados 1..10
        mov r12d, 1
.sq:
        cmp r12d, 10
        ja .sq_done
        mov eax, r12d
        imul eax, eax
        call print_dec
        lea rsi, [s_sp]
        mov rdx, 1
        call con_write
        inc r12d
        jmp .sq
.sq_done:
        lea rsi, [s_nl]
        mov rdx, 1
        call con_write
        ; Fibonacci 1..12
        lea rsi, [msg2]
        mov rdx, msg2_len
        call con_write
        xor r12d, r12d                 ; a
        mov r13d, 1                    ; b
        mov r14d, 12
.fib:
        test r14d, r14d
        jz .fib_done
        mov eax, r12d
        add eax, r13d
        mov r12d, r13d
        mov r13d, eax
        mov eax, r12d
        call print_dec
        lea rsi, [s_sp]
        mov rdx, 1
        call con_write
        dec r14d
        jmp .fib
.fib_done:
        lea rsi, [s_nl]
        mov rdx, 1
        call con_write
        ; fatorial de 12
        lea rsi, [msg3]
        mov rdx, msg3_len
        call con_write
        mov r12d, 1
        mov r13d, 1
.fat:
        cmp r13d, 12
        ja .fat_done
        mov eax, r12d
        imul eax, r13d
        mov r12d, eax
        inc r13d
        jmp .fat
.fat_done:
        mov eax, r12d
        call print_dec
        lea rsi, [s_nl]
        mov rdx, 1
        call con_write
        ; exit(0)
        mov eax, 60
        xor edi, edi
        int 0x80
.hang:
        pause
        jmp .hang

; ---- helpers -----------------------------------------------------------------
con_write:                         ; rsi=buf, rdx=len
        mov eax, 1
        mov edi, 1
        int 0x80
        ret

print_dec:                         ; eax=valor
        lea rdi, [numbuf+20]
        mov byte [rdi], 0
        xor r8d, r8d
        mov ecx, 10
        test eax, eax
        jz .zero
.d:
        test eax, eax
        jz .done
        xor edx, edx
        div ecx
        add dl, '0'
        dec rdi
        mov [rdi], dl
        inc r8d
        jmp .d
.zero:
        dec rdi
        mov byte [rdi], '0'
        mov r8d, 1
.done:
        mov rsi, rdi
        mov rdx, r8
        jmp con_write

msg1: db "CALC.RUN — binario ELF x86-64 rodando no EnzoOS", 10
      db "Quadrados 1..10:", 10
msg1_len equ $-msg1
msg2: db "Fibonacci:", 10
msg2_len equ $-msg2
msg3: db "12! = "
msg3_len equ $-msg3
s_sp: db " "
s_nl: db 10

numbuf: times 32 db 0
