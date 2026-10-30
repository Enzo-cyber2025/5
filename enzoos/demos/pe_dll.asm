; =============================================================================
;  EnzoOS — demos/pe_dll.asm: payload do LIBDEMO.DLL (DLL PE x86-64). O
;  tradutor do EnzoOS carrega a imagem, aplica relocações e chama o entry.
; =============================================================================
BITS 64
org 0x1000
default rel

entry:
        lea rsi, [msg1]
        mov rdx, msg1_len
        call con_write
        ; soma de verificação simples do próprio código (prova de execução)
        lea rsi, [entry]
        mov ecx, 512
        xor eax, eax
.sum:
        movzx edx, byte [rsi]
        add eax, edx
        inc rsi
        dec ecx
        jnz .sum
        mov edi, eax
        call print_hex
        lea rsi, [msg2]
        mov rdx, msg2_len
        call con_write
        mov eax, 1
        ret

con_write:                         ; rsi=buf, rdx=len
        mov eax, 1
        mov edi, 1
        int 0x80
        ret

print_hex:                         ; edi=valor -> escreve 8 dígitos hex
        lea rsi, [numbuf]
        mov ecx, 8
.l:
        rol edi, 4
        mov eax, edi
        and eax, 15
        cmp eax, 10
        jb .dig
        add eax, 'A' - 10
        jmp .wr
.dig:
        add eax, '0'
.wr:
        mov [rsi], al
        inc rsi
        dec ecx
        jnz .l
        lea rsi, [numbuf]
        mov rdx, 8
        jmp con_write

msg1: db "LIBDEMO.DLL — biblioteca PE carregada pelo EnzoOS; checksum do entry: 0x", 0
msg1_len equ $-msg1
msg2: db 10, "DllMain retornou TRUE (1).", 10
msg2_len equ $-msg2

numbuf: times 32 db 0
