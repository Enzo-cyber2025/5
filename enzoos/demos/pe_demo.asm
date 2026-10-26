; =============================================================================
;  EnzoOS — demos/pe_demo.asm: payload do DEMO.EXE (PE Windows x86-64
;  "freestanding" — sem CRT, sem importações; console via int 0x80 do EnzoOS).
;
;  Demonstração: escrita no console, Collatz 1..12, laço longo (Ctrl+C) e
;  laço infinito (o watchdog do kernel mata com 0xDEAD0010).
; =============================================================================
BITS 64
org 0x1000
default rel

entry:
        lea rsi, [msg1]
        mov rdx, msg1_len
        call con_write
        lea rsi, [msg2]
        mov rdx, msg2_len
        call con_write
        ; Collatz 1..12
        mov r12d, 1
.clz:
        cmp r12d, 12
        ja .clz_done
        mov ebp, r12d                  ; n preservado
        mov r13d, 0                    ; passos
.step:
        cmp ebp, 1
        je .stepped
        test ebp, 1
        jnz .odd
        shr ebp, 1
        jmp .count
.odd:
        lea ebp, [ebp + ebp*2 + 1]
.count:
        inc r13d
        jmp .step
.stepped:
        mov eax, r12d
        call print_dec
        lea rsi, [s_sep]
        mov rdx, s_sep_len
        call con_write
        mov eax, r13d
        call print_dec
        lea rsi, [s_nl]
        mov rdx, s_nl_len
        call con_write
        inc r12d
        jmp .clz
.clz_done:
        ; laço longo
        lea rsi, [msg3]
        mov rdx, msg3_len
        call con_write
        xor r13d, r13d
.slow:
        inc r13d
        cmp r13d, 0x10000000
        jb .slow
        ; laço infinito — watchdog
        lea rsi, [msg4]
        mov rdx, msg4_len
        call con_write
.spin:
        pause
        jmp .spin

; ---- helpers -----------------------------------------------------------------
con_write:                         ; rsi=buf, rdx=len
        mov eax, 1
        mov edi, 1
        int 0x80
        ret

print_dec:                         ; eax=valor -> escreve decimal no console
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

msg1: db "DEMO.EXE — binario PE (Windows x86-64) rodando no EnzoOS", 10
msg1_len equ $-msg1
msg2: db "Collatz 1..12 (passos):", 10
msg2_len equ $-msg2
msg3: db "Laco longo (256M)... aperte Ctrl+C para interromper.", 10
msg3_len equ $-msg3
msg4: db "Laco infinito: o watchdog do kernel vai me matar (0xDEAD0010).", 10
msg4_len equ $-msg4
s_sep: db " -> ", 0
s_sep_len equ 4
s_nl: db 10
s_nl_len equ 1

numbuf: times 32 db 0
