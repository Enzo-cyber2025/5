; =============================================================================
;  EnzoOS — demos/so_demo.asm: payload do libdemo.so (ELF ET_DYN x86-64 com
;  relocações R_X86_64_RELATIVE) — vai dentro do DEMO.APK.
; =============================================================================
BITS 64
org 0
default rel

entry:
        lea rsi, [msg1]
        mov rdx, msg1_len
        call con_write
        ; prova de relocação RELATIVE: lê um ponteiro movido pelo carregador
        mov rsi, [ptr_msg]
        mov rdx, msg2_len
        call con_write
        mov eax, 60
        xor edi, edi
        int 0x80
.hang:
        pause
        jmp .hang

con_write:
        mov eax, 1
        mov edi, 1
        int 0x80
        ret

msg1: db "libdemo.so: biblioteca nativa ELF (ET_DYN) do APK demo", 10
msg1_len equ $-msg1
msg2: db "libdemo.so: reloacao R_X86_64_RELATIVE OK", 10
msg2_len equ $-msg2

ptr_msg: dq msg2

numbuf: times 16 db 0
