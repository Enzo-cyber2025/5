; =============================================================================
;  EnzoOS — apps/terminal.asm: TERMINAL.CE — console de texto do EnzoOS.
;  Mostra o anel de saída (conout) do kernel; teclas F1..F5 executam as demos
;  (PE, ELF, APK, DLL, script). Ctrl+L limpa a tela.
; =============================================================================
BITS 64
org 0
default rel

%define LINESZ   80
%define LINES_MAX 40

; ---- cabeçalho .ce -----------------------------------------------------------
header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 640, 420
        dd 0
        db "Terminal", 0
        times 64-($-header) db 0

; =============================================================================
app_entry:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; api_table
        mov r13, rsi                    ; ev
        mov eax, [rsi]
        cmp eax, 1
        je ev_init
        cmp eax, 2
        je ev_paint
        cmp eax, 3
        je ev_mouse
        cmp eax, 4
        je ev_key
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

; ---- INIT ---------------------------------------------------------------------
ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        mov dword [nlines], 1
        mov byte [line_buf], 0
        lea rdi, [s_b1]
        call line_add
        lea rdi, [s_b2]
        call line_add
        lea rdi, [s_b3]
        call line_add
        lea rdi, [s_b4]
        call line_add
        jmp epilogue

; ---- PAINT --------------------------------------------------------------------
ev_paint:
        call render
        jmp epilogue

; ---- MOUSE (ignora) -------------------------------------------------------------
ev_mouse:
        jmp epilogue

; ---- KEY -----------------------------------------------------------------------
ev_key:
        mov eax, [r13+16]               ; ch
        cmp eax, 0x90                   ; F1
        je .f1
        cmp eax, 0x91
        je .f2
        cmp eax, 0x92
        je .f3
        cmp eax, 0x93
        je .f4
        cmp eax, 0x94
        je .f5
        cmp eax, 0x80                   ; backspace
        je .bs
        ; Ctrl+L limpa
        cmp eax, 'l'
        jne .notl
        mov ecx, [r13+32]               ; mods
        test ecx, 2
        jz .notl
        mov dword [nlines], 1
        mov byte [line_buf], 0
        call invalidate
        jmp epilogue
.notl:
        cmp eax, 32
        jb .done
        cmp eax, 126
        ja .done
        call curline_put
        call invalidate
.done:
        jmp epilogue
.bs:
        call curline_bs
        call invalidate
        jmp epilogue
.f1:
        lea rdi, [s_d1]
        call do_exec
        jmp epilogue
.f2:
        lea rdi, [s_d2]
        call do_exec
        jmp epilogue
.f3:
        lea rdi, [s_d3]
        call do_exec
        jmp epilogue
.f4:
        lea rdi, [s_d4]
        call do_exec
        jmp epilogue
.f5:
        lea rdi, [s_d5]
        call do_exec
        jmp epilogue

; ---- TICK: drena o conout --------------------------------------------------------
ev_tick:
        lea rdi, [tick_buf]
        mov esi, 512
        mov rax, [r12 + 8*10]           ; api_conout_read
        call rax
        test rax, rax
        jz .noout
        mov rcx, rax
        lea rsi, [tick_buf]
.lb:
        test rcx, rcx
        jz .noout
        movzx eax, byte [rsi]
        cmp eax, 10
        je .newline
        cmp eax, 13
        je .skipch
        cmp eax, 9
        jne .put
        mov eax, ' '
.put:
        call curline_put
.skipch:
        inc rsi
        dec rcx
        jmp .lb
.newline:
        call line_break
        inc rsi
        dec rcx
        jmp .lb
.noout:
        call render
        jmp epilogue

; =============================================================================
; helpers
; =============================================================================
invalidate:
        mov rax, [r12 + 8*12]
        jmp rax

do_exec:                           ; rdi=nome
        mov rax, [r12 + 8*9]
        jmp rax

; curline_put: eax=char
curline_put:
        push rdi
        push rsi
        push rcx
        mov edi, [nlines]
        dec edi
        imul edi, LINESZ
        lea rdi, [line_buf + rdi]
        ; fim da linha
        xor ecx, ecx
.find:
        cmp ecx, LINESZ-2
        jae .full
        cmp byte [rdi + rcx], 0
        je .wr
        inc ecx
        jmp .find
.wr:
        mov [rdi + rcx], al
        mov byte [rdi + rcx + 1], 0
.full:
        pop rcx
        pop rsi
        pop rdi
        ret

; curline_bs
curline_bs:
        push rdi
        push rcx
        mov edi, [nlines]
        dec edi
        imul edi, LINESZ
        lea rdi, [line_buf + rdi]
        xor ecx, ecx
.find:
        cmp ecx, LINESZ-1
        jae .done
        cmp byte [rdi + rcx], 0
        je .found
        inc ecx
        jmp .find
.found:
        test ecx, ecx
        jz .done
        dec ecx
        mov byte [rdi + rcx], 0
.done:
        pop rcx
        pop rdi
        ret

; line_break
line_break:
        mov eax, [nlines]
        cmp eax, LINES_MAX
        jb .space
        ; rola uma linha
        lea rdi, [line_buf]
        lea rsi, [line_buf + LINESZ]
        mov ecx, LINESZ * (LINES_MAX - 1)
.rl:
        mov al, [rsi]
        mov [rdi], al
        inc rsi
        inc rdi
        dec ecx
        jnz .rl
        mov eax, LINES_MAX - 1
.space:
        imul eax, LINESZ
        lea rdi, [line_buf + rax]
        mov byte [rdi], 0
        inc dword [nlines]
        ret

; line_add: rdi=string terminada em 0
line_add:
        push rdi
        push rsi
        push rcx
        call line_break
        mov eax, [nlines]
        dec eax
        imul eax, LINESZ
        lea rdi, [line_buf + rax]
        mov rsi, [rsp + 16]             ; rdi original
        xor ecx, ecx
.cp:
        cmp ecx, LINESZ-2
        jae .cd
        mov al, [rsi]
        test al, al
        jz .cd
        mov [rdi], al
        inc rsi
        inc rdi
        inc ecx
        jmp .cp
.cd:
        mov byte [rdi], 0
        pop rcx
        pop rsi
        pop rdi
        ret

; render: desenha tudo
render:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0A0E18
        mov rax, [r12 + 8*1]
        call rax
        ; linhas
        xor ebx, ebx
.rl:
        cmp ebx, [nlines]
        jae .done
        ; y = 4 + i*10
        mov esi, ebx
        imul esi, 10
        add esi, 4
        cmp esi, [th_]
        jae .done
        ; texto
        mov eax, ebx
        imul eax, LINESZ
        lea rdx, [line_buf + rax]
        ; len
        push rbx
        xor ecx, ecx
.len:
        cmp ecx, 78
        jae .lend
        cmp byte [rdx + rcx], 0
        je .lend
        inc ecx
        jmp .len
.lend:
        mov edi, 4
        mov r8d, 0x56C8D8
        mov eax, [nlines]
        dec eax
        cmp ebx, eax
        jne .dim
        mov r8d, 0xF2F5FA
.dim:
        mov rax, [r12 + 8*2]
        call rax
        pop rbx
        inc ebx
        jmp .rl
.done:
        pop rbx
        ret

; =============================================================================
; dados
; =============================================================================
s_b1: db "EnzoOS Console 1.0 — Certamente Executavel", 0
s_b2: db "F1 demo.exe (PE)    F2 calc.run (ELF)   F3 demo.apk (Android)", 0
s_b3: db "F4 libdemo.dll (PE) F5 script.run       Ctrl+L limpa a tela", 0
s_b4: db "Ctrl+C interrompe programas travados.", 0
s_d1: db "DEMO.EXE", 0
s_d2: db "CALC.RUN", 0
s_d3: db "DEMO.APK", 0
s_d4: db "LIBDEMO.DLL", 0
s_d5: db "SCRIPT.RUN", 0

tw_: dd 640
th_: dd 420
nlines: dd 0

align 16
line_buf: times LINESZ * LINES_MAX db 0
tick_buf: times 520 db 0

image_end:
