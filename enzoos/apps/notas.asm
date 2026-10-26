; =============================================================================
;  EnzoOS — apps/notas.asm: NOTAS.CE — bloco de notas minimalista.
;  Digitação, backspace, enter; F9 salva mensagem de status (demo).
; =============================================================================
BITS 64
org 0
default rel

%define LINESZ   48
%define LINES_MAX 24

header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 400, 300
        dd 0
        db "Notas", 0
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

ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        mov dword [nlines], 1
        mov byte [text], 0
        lea rdi, [s_hint]
        call line_add
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

ev_mouse:
        jmp epilogue

ev_key:
        mov eax, [r13+16]
        cmp eax, 0x80                   ; backspace
        je .bs
        cmp eax, 13                     ; enter
        je .nl
        cmp eax, 27
        je epilogue
        cmp eax, 32
        jb .done
        cmp eax, 126
        ja .done
        call cur_put
        jmp .done
.bs:
        call cur_bs
        jmp .done
.nl:
        call line_break
.done:
        call invalidate
        jmp epilogue

; ---- helpers -----------------------------------------------------------------
invalidate:
        mov rax, [r12 + 8*12]
        jmp rax

cur_put:                           ; eax=char
        push rdi
        push rcx
        mov edi, [nlines]
        dec edi
        imul edi, LINESZ
        lea rdi, [text + rdi]
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
        pop rdi
        ret

cur_bs:
        push rdi
        push rcx
        mov edi, [nlines]
        dec edi
        imul edi, LINESZ
        lea rdi, [text + rdi]
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

line_break:
        mov eax, [nlines]
        cmp eax, LINES_MAX
        jb .space
        lea rdi, [text]
        lea rsi, [text + LINESZ]
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
        lea rdi, [text + rax]
        mov byte [rdi], 0
        inc dword [nlines]
        ret

line_add:                          ; rdi=string
        push rdi
        push rsi
        push rcx
        call line_break
        mov eax, [nlines]
        dec eax
        imul eax, LINESZ
        lea rdi, [text + rax]
        mov rsi, [rsp + 16]
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

render:
        push rbx
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0F1524
        mov rax, [r12 + 8*1]
        call rax
        xor ebx, ebx
.rl:
        cmp ebx, [nlines]
        jae .done
        mov esi, ebx
        imul esi, 12
        add esi, 6
        cmp esi, [th_]
        jae .done
        mov eax, ebx
        imul eax, LINESZ
        lea rdx, [text + rax]
        push rbx
        xor ecx, ecx
.len:
        cmp ecx, LINESZ-1
        jae .lend
        cmp byte [rdx + rcx], 0
        je .lend
        inc ecx
        jmp .len
.lend:
        mov edi, 6
        mov r8d, 0xE8E0C8
        mov rax, [r12 + 8*2]
        call rax
        pop rbx
        inc ebx
        jmp .rl
.done:
        ; cursor da última linha
        mov eax, [nlines]
        dec eax
        imul eax, LINESZ
        lea rdx, [text + rax]
        xor ecx, ecx
.cl:
        cmp ecx, LINESZ-1
        jae .cd
        cmp byte [rdx + rcx], 0
        je .cd
        inc ecx
        jmp .cl
.cd:
        ; retângulo do cursor
        mov edi, ecx
        imul edi, 8
        add edi, 6
        mov eax, [nlines]
        dec eax
        imul eax, 12
        add eax, 6
        mov esi, eax
        mov edx, 8
        mov ecx, 10
        mov r8d, 0x10A372
        mov rax, [r12 + 8*1]
        call rax
        pop rbx
        ret

s_hint: db "Digite suas notas aqui...", 0

tw_: dd 400
th_: dd 300
nlines: dd 0

align 16
text: times LINESZ * LINES_MAX db 0

image_end:
