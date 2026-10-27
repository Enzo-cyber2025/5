; =============================================================================
;  EnzoOS — kernel/enz.inc: formato .ENZ (EnzoOS Native eXecutable)
;
;  Cabeçalho de 64 bytes (compatível com os deslocamentos do .ce):
;    +0  "ENZ1"          magia
;    +4  dw hdrsz (64) / +6 dw flags
;    +8  dd entry RVA    +12 dd isize
;    +16 dd nimports     +20 dw win_w  +22 dw win_h
;    +24 dd cor do ícone +28 db nome[20]
;    +48 dd imp_off      +52 dd sdk (2)
;  Strings de importação (ASCIZ, uma após a outra) a partir de imp_off.
;  No carregamento, cada nome é resolvido contra k_exports e a tabela
;  própria do app recebe os ponteiros — linkagem dinâmica por nome.
; =============================================================================
%ifndef ENZ_INC
%define ENZ_INC

section .ktext

; -----------------------------------------------------------------------------
; enz_lookup_export: rdi = nome -> rax = ponteiro da função (ou 0)
; -----------------------------------------------------------------------------
enz_lookup_export:
        push rbx
        push r12
        lea rbx, [k_exports]
.loop:
        mov r12, [rbx]
        test r12, r12
        jz .nf
        mov rsi, r12
        call k_strcmp
        test rax, rax
        jz .found
        add rbx, 16
        jmp .loop
.found:
        mov rax, [rbx + 8]
        pop r12
        pop rbx
        ret
.nf:
        xor eax, eax
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; enz_build: monta a tabela de importações do app do slot rbx
; -----------------------------------------------------------------------------
enz_build:
        push r12
        push r13
        push r14
        push r15
        mov r14, [img_ptr]
        mov r13d, [r14 + 16]        ; nimports
        test r13d, r13d
        jz .done
        ; aloca a tabela (n+1) * 8 bytes
        lea rdi, [r13]
        inc rdi
        shl rdi, 3
        call k_alloc
        test rax, rax
        jz .done
        mov r15, rax
        mov dword [rax], 0x325A4E45 ; "ENZ2" (magic da tabela do app)
        mov [rbx + A_APITBL], rax
        mov [rbx + A_APITBL_N], r13d
        mov dword [rbx + A_FMT], 2
        ; resolve os imports
        mov eax, [r14 + 48]         ; imp_off
        add r14, rax                ; r14 = primeira string
        xor r12d, r12d
.imp:
        cmp r12d, r13d
        jae .done
        mov rdi, r14
        call enz_lookup_export
        mov [r15 + 8 + r12*8], rax
.skipz:
        cmp byte [r14], 0
        je .adv
        inc r14
        jmp .skipz
.adv:
        inc r14
        inc r12d
        jmp .imp
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        ret

section .kdata

%endif
