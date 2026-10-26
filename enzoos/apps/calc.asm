; =============================================================================
;  EnzoOS — apps/calc.asm: CALC.CE — calculadora inteira com teclado e botões.
; =============================================================================
BITS 64
org 0
default rel

%define BTN   52
%define GAP   6

header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 268, 388
        dd 0
        db "Calc", 0
        times 64-($-header) db 0

; rótulos dos botões (linha, coluna) — grid 4 colunas × 5 linhas
; 7 8 9 ÷      4 5 6 ×      1 2 3 −      0 C = +
app_entry:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        mov r13, rsi
        mov eax, [rsi]
        cmp eax, 1
        je ev_init
        cmp eax, 2
        je ev_paint
        cmp eax, 3
        je ev_mouse
        cmp eax, 4
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

ev_paint:
        call render
        jmp epilogue

ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        mov qword [acc], 0
        mov dword [disp], 0
        mov dword [op], 0
        mov dword [fresh], 1
        jmp epilogue

ev_key:
        mov eax, [r13+16]
        cmp eax, '0'
        jb .done
        cmp eax, '9'
        jbe .dig
        cmp eax, '+'
        je .add
        cmp eax, '-'
        je .sub
        cmp eax, '*'
        je .mul
        cmp eax, '/'
        je .div
        cmp eax, 13
        je .eq
        cmp eax, 'c'
        je .clr
        cmp eax, 'C'
        je .clr
        jmp .done
.dig:
        sub eax, '0'
        call push_digit
        call invalidate
        jmp .done
.add:
        mov dword [op], 1
        call apply_op
        jmp .done
.sub:
        mov dword [op], 2
        call apply_op
        jmp .done
.mul:
        mov dword [op], 3
        call apply_op
        jmp .done
.div:
        mov dword [op], 4
        call apply_op
        jmp .done
.eq:
        call apply_eq
        jmp .done
.clr:
        call do_clear
.done:
        call invalidate
        jmp epilogue

ev_mouse:
        mov ebx, [r13+16]               ; x
        mov ebp, [r13+24]               ; y
        ; área dos botões: y >= 96
        cmp ebp, 96
        jl .out
        ; linha = (y-96) / (BTN+GAP); col = (x-4) / (BTN+GAP)
        mov eax, ebp
        sub eax, 96
        xor edx, edx
        mov ecx, BTN+GAP
        div ecx
        cmp eax, 5
        jae .out
        mov r14d, eax                   ; linha
        mov eax, ebx
        sub eax, 4
        xor edx, edx
        mov ecx, BTN+GAP
        div ecx
        cmp eax, 4
        jae .out
        ; idx = linha*4 + col
        shl r14d, 2
        add r14d, eax
        ; mapeia índice -> chave
        lea rax, [keymap]
        movzx edi, byte [rax + r14]
        ; simula tecla
        mov eax, edi
        cmp eax, '0'
        jb .done2
        cmp eax, '9'
        jbe .dig2
        cmp eax, '+'
        je .add2
        cmp eax, '-'
        je .sub2
        cmp eax, '*'
        je .mul2
        cmp eax, '/'
        je .div2
        cmp eax, '='
        je .eq2
        cmp eax, 'C'
        je .clr2
        jmp .out
.dig2:
        sub eax, '0'
        call push_digit
        jmp .done2
.add2:
        mov edi, 1
        call apply_op
        jmp .done2
.sub2:
        mov edi, 2
        call apply_op
        jmp .done2
.mul2:
        mov edi, 3
        call apply_op
        jmp .done2
.div2:
        mov edi, 4
        call apply_op
        jmp .done2
.eq2:
        call apply_eq
        jmp .done2
.clr2:
        call do_clear
.done2:
        call invalidate
.out:
        jmp epilogue

; ---- lógica ------------------------------------------------------------------
push_digit:                        ; eax=dígito
        test dword [fresh], 1
        jz .append
        mov dword [disp], 0
        mov dword [fresh], 0
.append:
        mov ecx, [disp]
        imul ecx, ecx, 10
        add ecx, eax
        mov [disp], ecx
        ret

apply_op:                          ; edi = nova operação
        cmp dword [op], 0
        je .first
        call compute
        jmp .set
.first:
        mov eax, [disp]
        mov [acc], rax
.set:
        mov [op], edi
        mov dword [fresh], 1
        mov eax, [acc]
        mov [disp], eax
        ret

compute:                           ; acc = acc (op) disp
        mov eax, [acc]
        mov ecx, [disp]
        cmp dword [op], 1
        je .add
        cmp dword [op], 2
        je .sub
        cmp dword [op], 3
        je .mul
        cmp dword [op], 4
        je .div
        ret
.add:
        add eax, ecx
        mov [acc], rax
        ret
.sub:
        sub eax, ecx
        mov [acc], rax
        ret
.mul:
        imul eax, ecx
        mov [acc], rax
        ret
.div:
        test ecx, ecx
        jz .dz
        xor edx, edx
        div ecx
        mov [acc], rax
        ret
.dz:
        ret

apply_eq:
        cmp dword [op], 0
        je .none
        call compute
        mov dword [op], 0
        mov eax, [acc]
        mov [disp], eax
        mov dword [fresh], 1
.none:
        ret

do_clear:
        mov qword [acc], 0
        mov dword [disp], 0
        mov dword [op], 0
        mov dword [fresh], 1
        ret

; ---- render ------------------------------------------------------------------
render:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x101726
        mov rax, [r12 + 8*1]
        call rax
        ; visor
        mov edi, 4
        mov esi, 8
        mov edx, 248
        mov ecx, 76
        mov r8d, 0x0A0E18
        mov rax, [r12 + 8*1]
        call rax
        ; número do visor
        lea rdi, [numbuf]
        mov eax, [disp]
        call utoa_local
        mov edi, 12
        mov esi, 24
        lea rdx, [numbuf]
        mov r8d, 0x10A372
        mov rax, [r12 + 8*2]
        call rax
        ; botões
        xor ebx, ebx
.bl:
        cmp ebx, 20
        jae .bdone
        ; rect
        mov eax, ebx
        shr eax, 2                     ; linha
        mov ecx, ebx
        and ecx, 3                     ; coluna
        mov edi, ecx
        imul edi, BTN+GAP
        add edi, 4
        mov esi, eax
        imul esi, BTN+GAP
        add esi, 96
        mov edx, BTN
        mov ecx, BTN
        ; cor: operadores destacados
        mov r8d, 0x1B2A47
        lea rax, [keymap]
        movzx ebp, byte [rax + rbx]
        cmp ebp, '0'
        jb .opcol
        cmp ebp, '9'
        ja .opcol
        mov r8d, 0x16223A
.opcol:
        mov rax, [r12 + 8*1]
        call rax
        ; texto centralizado
        mov eax, ebx
        shr eax, 2
        mov ecx, ebx
        and ecx, 3
        mov edi, ecx
        imul edi, BTN+GAP
        add edi, 4
        add edi, BTN/2
        sub edi, 4
        mov esi, eax
        imul esi, BTN+GAP
        add esi, 96
        add esi, BTN/2
        sub esi, 4
        lea rdx, [keymap]
        add rdx, rbx
        mov ecx, 1
        mov r8d, 0xF2F5FA
        mov rax, [r12 + 8*2]
        call rax
        inc ebx
        jmp .bl
.bdone:
        pop rbx
        ret

invalidate:
        mov rax, [r12 + 8*12]
        jmp rax

; utoa local (igual ao do info)
utoa_local:
        lea rdi, [numbuf + 20]
        mov byte [rdi], 0
        mov ecx, 10
        mov r8d, 0
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
        mov r9, rdi
        lea rdi, [numbuf]
        xor ecx, ecx
.cp:
        cmp ecx, r8d
        jae .cd
        mov al, [r9 + rcx]
        mov [rdi + rcx], al
        inc ecx
        jmp .cp
.cd:
        mov byte [rdi + rcx], 0
        mov ecx, r8d
        ret

; dados
keymap: db '7','8','9','/','4','5','6','*','1','2','3','-','0','C','=','+'

tw_: dd 268
th_: dd 388
acc:  dq 0
disp: dd 0
op:   dd 0
fresh: dd 1

align 16
numbuf: times 32 db 0

image_end:
