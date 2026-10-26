; =============================================================================
;  EnzoOS — apps/plasma.asm: PLASMA.CE — plasma animado com tabela de seno.
; =============================================================================
BITS 64
org 0
default rel

%define PW   336
%define PH   224

header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 360, 280
        dd 0
        db "Plasma", 0
        times 64-($-header) db 0

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
        cmp eax, 5
        je ev_tick
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
        mov edi, PW*PH*4
        mov rax, [r12 + 8*13]
        call rax
        mov [fb], rax
        mov dword [t], 0
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

ev_tick:
        call plasma_frame
        call render
        jmp epilogue

; ---- plasma ------------------------------------------------------------------
plasma_frame:
        mov rdi, [fb]
        test rdi, rdi
        jz .done
        mov eax, [t]
        inc eax
        mov [t], eax
        ; t2 = variação de fase
        xor r10d, r10d                  ; y
.row:
        cmp r10d, PH
        jae .done
        xor r11d, r11d                  ; x
.col:
        cmp r11d, PW
        jae .nextrow
        ; c = sin(x*f1+t) + sin(y*f2-t) + sin((x+y)*f3+t/2)
        ; índices: (x + t) & 255, (y*2 - t) & 255, ((x+y) + t/2) & 255
        mov eax, r11d
        add eax, [t]
        and eax, 255
        lea rcx, [sintab]
        movzx eax, byte [rcx + rax]
        mov ebx, eax
        mov eax, r10d
        shl eax, 1
        sub eax, [t]
        and eax, 255
        movzx eax, byte [rcx + rax]
        add ebx, eax
        mov eax, r11d
        add eax, r10d
        mov edx, [t]
        shr edx, 1
        add eax, edx
        and eax, 255
        movzx eax, byte [rcx + rax]
        add ebx, eax                    ; 0..765
        ; cor: paleta indexada por (c + t) — 4 canais
        mov eax, ebx
        add eax, [t]
        shr eax, 2                      ; 0..255 aprox
        and eax, 255
        lea rcx, [paltab]
        mov eax, [rcx + rax*4]
        mov [rdi], eax
        add rdi, 4
        inc r11d
        jmp .col
.nextrow:
        inc r10d
        jmp .row
.done:
        ret

; ---- render ------------------------------------------------------------------
render:
        push rbx
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0B1220
        mov rax, [r12 + 8*1]
        call rax
        mov r8, [fb]
        test r8, r8
        jz .out
        mov edi, 4
        mov esi, 24
        mov edx, PW
        mov ecx, PH
        mov r9d, PW*4
        mov rax, [r12 + 8*3]
        call rax
        ; rótulo
        mov edi, 8
        mov esi, 6
        lea rdx, [s_lbl]
        mov ecx, 26
        mov r8d, 0xF2F5FA
        mov rax, [r12 + 8*2]
        call rax
.out:
        pop rbx
        ret

s_lbl: db "Plasma — tabela de seno em ASM", 0

tw_: dd 360
th_: dd 280
t:   dd 0
fb:  dq 0

%include "plasma_tab.inc"

image_end:
