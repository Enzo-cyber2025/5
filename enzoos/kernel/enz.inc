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
        push r13
        xor r13d, r13d
        lea rbx, [k_exports]
.loop:
        mov r12, [rbx]
        test r12, r12
        jz .nf
        inc r13d                       ; slot canônico desta entrada (1-based)
        mov rsi, r12
        call k_strcmp
        test rax, rax
        jz .found
        add rbx, 16
        jmp .loop
.found:
        mov rax, [rbx + 8]
        mov edx, r13d                  ; rdx = slot canônico (0 = não existe)
        pop r13
        pop r12
        pop rbx
        ret
.nf:
        xor eax, eax
        xor edx, edx
        pop r13
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
        ; tabela CANÔNICA: slot i = API número i ([0] = magic). Imports
        ; parciais eram gravados em sequência e o app chamava [r12+8*N]
        ; pelo N canônico — slot errado = ponteiro de lixo = panic 0x90
        mov edi, (K_EXPORTS_N + 1) * 8
        call k_alloc
        test rax, rax
        jz .done
        mov r15, rax
        mov rdi, rax
        mov esi, (K_EXPORTS_N + 1) * 8
        call k_memzero
        mov dword [r15], 0x325A4E45 ; "ENZ2" (magic da tabela do app)
        mov [rbx + A_APITBL], r15
        mov dword [rbx + A_APITBL_N], K_EXPORTS_N
        mov dword [rbx + A_FMT], 2
        ; resolve os imports (cada um no SEU slot canônico)
        mov eax, [r14 + 48]         ; imp_off
        add r14, rax                ; r14 = primeira string
        xor r12d, r12d
.imp:
        cmp r12d, r13d
        jae .done
        mov rdi, r14
        call enz_lookup_export      ; rax = fn, rdx = slot canônico (0 = não achou)
        test rdx, rdx
        jz .badimp                  ; import desconhecido: app inválido
        mov rcx, rdx
        mov [r15 + rcx*8], rax     ; rcx = slot 1-based: slot 1 fica em r15+8
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
        ; rax = base da imagem (o app_launch soma o entry RVA em cima disso;
        ; sem isto o rax residual era o endereco do ultimo import resolvido
        ; e o A_ENTRY virava lixo -> app executava NOP slides -> panic 0x90)
        mov rax, [img_ptr]
        pop r15
        pop r14
        pop r13
        pop r12
        ret
.badimp:
        ; hardening: import não resolvido — aborta o launch sem executar
        ; nada (antes: o slot ficava NULL e o app crashava ao chamar)
        mov rdi, r15
        mov esi, (K_EXPORTS_N + 1) * 8
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
        mov qword [rbx + A_APITBL], 0
        mov dword [rbx + A_APITBL_N], 0
        xor eax, eax
        pop r15
        pop r14
        pop r13
        pop r12
        ret

section .kdata

%endif
