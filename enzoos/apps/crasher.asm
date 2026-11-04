; =============================================================================
;  EnzoOS — apps/crasher.asm: CRASHER.ENZ — app que gera exceção de propósito.
;  Ferramenta do pen-test: valida que o kernel mata só o app e segue vivo.
;  App .ENZ cru (org 0, entry 0) — cabeçalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_TEXT  2
%define API_INVAL 12

app_entry:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; APITBL
        mov r13, rsi                    ; evento
        mov eax, [rsi]
        cmp eax, 1                      ; EV_INIT
        je ev_init
        cmp eax, 4                      ; EV_KEY
        je ev_key
        jmp epilogue
epilogue:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        mov edi, 12
        mov esi, 40
        lea rdx, [msg]
        mov r8d, 0xFFE8E8E8
        mov rax, [r12 + 8*API_TEXT]
        call rax
        jmp epilogue

ev_key:
        ; QUALQUER tecla: gera #UD (opcode inválido) — crash garantido,
        ; independente de mapeamento (pen-test do kill-app)
        ud2
        jmp epilogue

msg:      db "Digite qq tecla p/ crashar", 0
tw_: dd 0
th_: dd 0
