; =============================================================================
;  EnzoOS — apps/files.asm: FILES.ENZ — navegador de arquivos do ENZFS
;  Lista diretórios, abre arquivos (visualização de texto), navega com clique.
;  App .ENZ cru (org 0, entry 0) — cabeçalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_RECT    1
%define API_TEXT    2
%define API_TITLE   4
%define API_INVAL   12
%define API_ROUND   23
%define API_FSOPEN  25
%define API_FSLIST  26
%define API_FSREAD  27

%define ROW_H   18
%define LIST_Y  44
%define MAX_ROWS 15

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
        ; abre a raiz
        lea rdi, [s_root]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov [cur_ino], eax
        lea rdi, [cur_path]
        lea rsi, [s_root]
        call copy_str
        jmp epilogue

ev_key:
        mov eax, [r13+16]
        cmp eax, 27                        ; ESC volta
        jne .out
        call go_up
.out:
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

ev_mouse:
        mov eax, [r13+32]
        test eax, 1
        jz .out
        mov ebx, [r13+16]                  ; x
        mov ebp, [r13+24]                  ; y
        cmp dword [mode], 1
        je .view_click
        ; clique em uma linha?
        mov eax, ebp
        sub eax, LIST_Y
        jl .out
        xor edx, edx
        mov ecx, ROW_H
        div ecx
        cmp eax, MAX_ROWS
        jae .out
        ; linha 0 = ".."
        test eax, eax
        jz .up
        ; índice real = eax - 1
        dec eax
        mov [sel_idx], eax
        ; busca o tipo da entrada
        mov edi, [cur_ino]
        mov esi, eax
        lea rdx, [namebuf]
        mov rax, [r12 + 8*API_FSLIST]
        call rax
        cmp eax, 0
        jle .out
        cmp eax, 2
        je .dir
        ; arquivo: abre e lê
        call build_sel_path
        lea rdi, [sel_path]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        cmp eax, -1
        je .out
        mov edi, eax
        lea rsi, [view_buf]
        mov edx, 3800
        mov rax, [r12 + 8*API_FSREAD]
        call rax
        mov [view_len], eax
        mov dword [mode], 1
        jmp .out
.dir:
        call build_sel_path
        lea rdi, [sel_path]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        cmp eax, -1
        je .out
        mov [cur_ino], eax
        lea rdi, [cur_path]
        lea rsi, [sel_path]
        call copy_str
        jmp .out
.up:
        call go_up
        jmp .out
.view_click:
        ; botão Voltar
        cmp ebx, 12
        jl .out
        cmp ebx, 132
        jg .out
        cmp ebp, 12
        jl .out
        cmp ebp, 40
        jg .out
        mov dword [mode], 0
.out:
        jmp epilogue

; ---- helpers ----------------------------------------------------------------
copy_str:                       ; rdi=dst rsi=src
.l:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .d
        inc rsi
        inc rdi
        jmp .l
.d:
        ret

slen:                           ; rdi=str -> eax
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

; append: rdi=dst(str) rsi=src — concatena no fim
append_str:
        push rdi
.l:
        cmp byte [rdi], 0
        je .at
        inc rdi
        jmp .l
.at:
        pop rax                 ; descarta; rdi já avançado
.c:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .d
        inc rsi
        inc rdi
        jmp .c
.d:
        ret

; build_sel_path: cur_path + "/" + namebuf -> sel_path
build_sel_path:
        push rdi
        push rsi
        lea rdi, [sel_path]
        lea rsi, [cur_path]
        call copy_str
        ; se não é a raiz, separa com '/'
        lea rdi, [sel_path]
        cmp byte [cur_path + 1], 0          ; "/" tem comprimento 1
        jne .sep
        cmp byte [cur_path], '/'
        jne .sep
        jmp .nos
.sep:
        lea rdi, [sel_path]
        lea rsi, [s_slash]
        call append_str
.nos:
        lea rdi, [sel_path]
        lea rsi, [namebuf]
        call append_str
        pop rsi
        pop rdi
        ret

; go_up: remove o último componente de cur_path e reabre
go_up:
        cmp byte [cur_path + 1], 0
        jne .go
        ret                                  ; já na raiz
.go:
        lea rdi, [cur_path]
        call slen
        lea rdi, [cur_path]
        add rdi, rax
.back:
        cmp rdi, cur_path + 1
        jbe .cut
        dec rdi
        cmp byte [rdi], '/'
        jne .back
.cut:
        cmp rdi, cur_path + 1
        ja .store
        lea rdi, [cur_path + 1]
.store:
        mov byte [rdi], 0
        ; se ficou só "" vira "/"
        cmp byte [cur_path], 0
        jne .open
        mov byte [cur_path], '/'
        mov byte [cur_path + 1], 0
.open:
        lea rdi, [cur_path]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        cmp eax, -1
        je .bad
        mov [cur_ino], eax
.bad:
        ret

; ---- render -----------------------------------------------------------------
render:
        push rbx
        cmp dword [mode], 1
        je render_view
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0D1524
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; barra de caminho
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, LIST_Y
        mov r8d, 0x16233C
        mov r9d, 0x0D1524
        mov rax, [r12 + 8*22]               ; grad
        call rax
        mov edi, 12
        mov esi, 14
        lea rdx, [cur_path]
        mov r8d, 0x7FD8FF
        call text_at
        ; linha ".."
        mov edi, 12
        mov esi, LIST_Y + 4
        lea rdx, [s_updir]
        mov r8d, 0x9FB4D8
        call text_at
        ; entradas
        xor ebx, ebx                        ; índice
.rows:
        mov edi, [cur_ino]
        mov esi, ebx
        lea rdx, [namebuf]
        mov rax, [r12 + 8*API_FSLIST]
        call rax
        cmp eax, 0
        jle .rows_end
        mov [ent_type], eax
        ; y da linha
        mov eax, ebx
        inc eax
        imul eax, ROW_H
        add eax, LIST_Y + 4
        mov esi, eax
        mov edi, 34
        lea rdx, [namebuf]
        mov r8d, 0xE8ECF4
        cmp dword [ent_type], 2
        jne .pt
        mov r8d, 0x7FD8FF
.pt:
        call text_at
        ; marcador
        mov eax, ebx
        inc eax
        imul eax, ROW_H
        add eax, LIST_Y + 4
        mov esi, eax
        mov edi, 14
        lea rdx, [s_fmark]
        cmp dword [ent_type], 2
        jne .mk
        lea rdx, [s_dmark]
.mk:
        mov r8d, 0xF5A86B
        call text_at
        inc ebx
        cmp ebx, MAX_ROWS
        jb .rows
.rows_end:
        pop rbx
        ret

render_view:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x101826
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; botão Voltar
        mov edi, 12
        mov esi, 12
        mov edx, 120
        mov ecx, 28
        mov r8d, 7
        mov r9d, 0xFF1C3B72
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 34
        mov esi, 20
        lea rdx, [s_back]
        mov r8d, 0xF2F5FA
        call text_at
        ; nome do arquivo
        mov edi, 150
        mov esi, 20
        lea rdx, [namebuf]
        mov r8d, 0x7FD8FF
        call text_at
        ; conteúdo: 16 linhas de 90 chars
        xor ebx, ebx                        ; linha
        lea r14, [view_buf]
        mov r15d, [view_len]
.lines:
        cmp ebx, 16
        jae .ld
        ; fim do buffer?
        cmp r14, view_buf
        jb .ld
        call view_next_line                 ; rax = comprimento ou -1
        cmp eax, -1
        je .ld
        ; desenha
        mov ecx, eax
        mov edi, 14
        mov esi, ebx
        imul esi, 20
        add esi, 54
        mov rdx, r14
        mov r8d, 0xD8DEEA
        mov rax, [r12 + 8*API_TEXT]
        call rax
        ; avança r14
        mov eax, ecx
        lea r14, [r14 + rax + 1]
        inc ebx
        jmp .lines
.ld:
        pop rbx
        ret

; view_next_line: r14 = pos atual, r15d = restante -> eax = comprimento (-1 fim)
view_next_line:
        xor eax, eax
.l:
        cmp eax, r15d
        jae .eob
        cmp eax, 90
        jae .full
        movzx edx, byte [r14 + rax]
        test edx, edx
        jz .eob
        cmp dl, 10
        je .full
        inc eax
        jmp .l
.eob:
        ret
.full:
        ret
.none:
        mov eax, -1
        ret

; ---- dados ------------------------------------------------------------------
tw_:    dd 460
th_:    dd 380
mode:   dd 0
cur_ino: dd 0
sel_idx: dd 0
ent_type: dd 0
view_len: dd 0

cur_path: times 64 db 0
sel_path: times 96 db 0
namebuf:  times 24 db 0
align 16
view_buf: times 4096 db 0

s_root:  db "/", 0
s_slash: db "/", 0
s_updir: db "[ .. ]", 0
s_back:  db "< Voltar", 0
s_fmark: db "TXT", 0
s_dmark: db "DIR", 0
