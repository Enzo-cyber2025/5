; =============================================================================
;  EnzoOS — apps/sysmon.asm: SYSMON.ENZ — monitor do sistema
;  Swap (demand paging), HPET, uptime e teste de áudio HDA.
;  App .ENZ cru (org 0, entry 0) — o cabeçalho é gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_RECT   1
%define API_TEXT   2
%define API_TITLE  4
%define API_UPTIME 5
%define API_INVAL  12
%define API_SYSINFO 15
%define API_PX     20
%define API_GRAD   22
%define API_ROUND  23
%define API_SWINFO 33
%define API_SWFORCE 34
%define API_HPET   35
%define API_TONE   36
%define API_BEEP   18

%define BTN_TONE_X 16
%define BTN_TONE_Y 296
%define BTN_SWP_X  170
%define BTN_SWP_Y  296
%define BTN_W      140
%define BTN_H      30

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
        jmp epilogue

ev_tick:
ev_paint:
        call render
        jmp epilogue

ev_mouse:
        mov eax, [r13+32]
        test eax, 1
        jz .out
        mov ebx, [r13+16]
        mov ebp, [r13+24]
        ; botão Tone
        cmp ebx, BTN_TONE_X
        jl .swp
        cmp ebx, BTN_TONE_X + BTN_W
        jg .swp
        cmp ebp, BTN_TONE_Y
        jl .swp
        cmp ebp, BTN_TONE_Y + BTN_H
        jg .swp
        mov edi, 440
        mov esi, 300
        mov rax, [r12 + 8*API_TONE]
        call rax
        jmp .out
.swp:
        cmp ebx, BTN_SWP_X
        jl .out
        cmp ebx, BTN_SWP_X + BTN_W
        jg .out
        cmp ebp, BTN_SWP_Y
        jl .out
        cmp ebp, BTN_SWP_Y + BTN_H
        jg .out
        mov edi, 16
        mov rax, [r12 + 8*API_SWFORCE]
        call rax
        mov [sw_done], eax
        mov edi, 880
        mov esi, 120
        mov rax, [r12 + 8*API_BEEP]
        call rax
        call render
.out:
        jmp epilogue

; ---- helpers ----------------------------------------------------------------
slen:                           ; rdi = str -> eax
        xor eax, eax
.l:
        cmp byte [rdi + rax], 0
        je .d
        inc eax
        jmp .l
.d:
        ret

text_at:                        ; edi=x esi=y rdx=str r8d=cor
        push rdi
        push rsi
        push rdx
        push r8
        call slen
        mov ecx, eax
        pop r8
        pop rdx
        pop rsi
        pop rdi
        mov rax, [r12 + 8*API_TEXT]
        jmp rax

label_at:                       ; edi=x esi=y rdx=str r8d=cor (comprimento fixo)
        mov ecx, 0
        push rdi
        push rsi
        push rdx
        push r8
        call slen
        mov ecx, eax
        pop r8
        pop rdx
        pop rsi
        pop rdi
        mov rax, [r12 + 8*API_TEXT]
        jmp rax

; draw_num: edi=x esi=y eax=val r8d=cor
draw_num:
        push rbx
        push rdx
        push rdi
        push rsi
        push r8
        mov ebx, eax
        lea rdi, [numbuf + 15]
        mov byte [rdi], 0
        mov ecx, 10
.d:
        test ebx, ebx
        jz .fin
        mov eax, ebx
        xor edx, edx
        div ecx
        mov ebx, eax
        add dl, '0'
        dec rdi
        mov [rdi], dl
        jmp .d
.fin:
        cmp byte [rdi], 0
        jne .p
        dec rdi
        mov byte [rdi], '0'
.p:
        mov rdx, rdi
        pop r8
        pop rsi
        pop rdi
        call label_at          ; usa rdi/rsi/rdx/r8
        pop rdx
        pop rbx
        ret

; draw_hex64: edi=x esi=y rax=qword r8d=cor
draw_hex64:
        push rbx
        push rdx
        push rdi
        push rsi
        push r8
        mov rbx, rax
        lea rdi, [numbuf + 15]
        mov byte [rdi], 0
        mov ecx, 16
.d:
        test rbx, rbx
        jz .fin
        mov rax, rbx
        and eax, 0xF
        cmp al, 10
        jb .dg
        add al, 'A' - 10
        jmp .st
.dg:
        add al, '0'
.st:
        dec rdi
        mov [rdi], al
        shr rbx, 4
        jmp .d
.fin:
        cmp byte [rdi], 0
        jne .p
        dec rdi
        mov byte [rdi], '0'
.p:
        mov rdx, rdi
        pop r8
        pop rsi
        pop rdi
        call label_at
        pop rdx
        pop rbx
        ret

; ---- render -----------------------------------------------------------------
render:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0B1220
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; faixa título
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, 34
        mov r8d, 0x14203A
        mov r9d, 0x0B1220
        mov rax, [r12 + 8*API_GRAD]
        call rax
        ; título
        mov edi, 12
        mov esi, 10
        lea rdx, [s_title]
        mov r8d, 0xF2F5FA
        call text_at
        ; ---- swap ----
        lea rdi, [swbuf]
        mov rax, [r12 + 8*API_SWINFO]
        call rax
        mov edi, 14
        mov esi, 48
        lea rdx, [l_swtitle]
        mov r8d, 0x2D9CDB
        call text_at
        mov edi, 16
        mov esi, 68
        lea rdx, [l_armed]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 68
        mov eax, [swbuf + 0]
        mov r8d, 0xF2F5FA
        call draw_num
        mov edi, 16
        mov esi, 86
        lea rdx, [l_faults]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 86
        mov eax, [swbuf + 12]
        mov r8d, 0xF2F5FA
        call draw_num
        mov edi, 16
        mov esi, 104
        lea rdx, [l_out]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 104
        mov eax, [swbuf + 4]
        mov r8d, 0xF2F5FA
        call draw_num
        mov edi, 16
        mov esi, 122
        lea rdx, [l_in]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 122
        mov eax, [swbuf + 8]
        mov r8d, 0xF2F5FA
        call draw_num
        mov edi, 16
        mov esi, 140
        lea rdx, [l_use]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 140
        mov eax, [swbuf + 16]
        mov r8d, 0xF2F5FA
        call draw_num
        mov edi, 16
        mov esi, 158
        lea rdx, [l_slots]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 158
        mov eax, [swbuf + 20]
        mov r8d, 0xF2F5FA
        call draw_num
        ; ---- HPET ----
        mov edi, 14
        mov esi, 190
        lea rdx, [l_hp]
        mov r8d, 0x2D9CDB
        call text_at
        lea rdi, [hpetbuf]
        mov rax, [r12 + 8*API_HPET]
        call rax
        mov edi, 16
        mov esi, 210
        lea rdx, [l_ns]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 210
        mov rax, [hpetbuf]
        mov r8d, 0xF2F5FA
        call draw_hex64
        ; ---- uptime ----
        mov edi, 16
        mov esi, 228
        lea rdx, [l_up]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 190
        mov esi, 228
        mov rax, [r12 + 8*API_UPTIME]
        call rax
        mov r8d, 0xF2F5FA
        call draw_num
        ; ---- botões ----
        mov edi, BTN_TONE_X
        mov esi, BTN_TONE_Y
        mov edx, BTN_W
        mov ecx, BTN_H
        mov r8d, 7
        mov r9d, 0xFF1C3B72
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, BTN_TONE_X + 22
        mov esi, BTN_TONE_Y + 8
        lea rdx, [s_btone]
        mov r8d, 0xF2F5FA
        call label_at
        mov edi, BTN_SWP_X
        mov esi, BTN_SWP_Y
        mov edx, BTN_W
        mov ecx, BTN_H
        mov r8d, 7
        mov r9d, 0xFF205040
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, BTN_SWP_X + 16
        mov esi, BTN_SWP_Y + 8
        lea rdx, [s_bswp]
        mov r8d, 0xF2F5FA
        call label_at
        ; resultado swap_force
        cmp dword [sw_done], 0
        je .nsw
        mov edi, 16
        mov esi, 268
        lea rdx, [l_pout]
        mov r8d, 0x9FB4D8
        call label_at
        mov edi, 200
        mov esi, 268
        mov eax, [sw_done]
        mov r8d, 0x7CE8A0
        call draw_num
.nsw:
        pop rbx
        ret

; ---- dados ------------------------------------------------------------------
tw_:    dd 460
th_:    dd 360
sw_done: dd 0
align 16
swbuf:   times 32 db 0
hpetbuf: dq 0
numbuf:  times 16 db 0

s_title:  db "SysMon — memoria e tempo", 0
l_swtitle: db "Area de troca (swap por demand paging)", 0
l_armed:  db "Armado:", 0
l_faults: db "Page faults:", 0
l_out:    db "Paginas out:", 0
l_in:     db "Paginas in:", 0
l_use:    db "Trocadas agora:", 0
l_slots:  db "Slots:", 0
l_hp:     db "HPET (timer de alta resolucao)", 0
l_ns:     db "Contagem (ns):", 0
l_up:     db "Uptime (ms):", 0
l_pout:   db "swap_force removeu:", 0
s_btone:  db "Tone 440 Hz", 0
s_bswp:   db "Swap: tirar 16 pgs", 0
