; =============================================================================
;  EnzoOS — apps/loja.asm: LOJA.ENZ — loja/launcher dos apps do ENZFS
;  Lista o diretório /APPS lendo o inode do diretório INTEIRO com fs_read
;  (uma leitura só — e_list é O(n^2) e travava com 1000+ entradas),
;  navega com setas/PageUp/PageDown, clica ou Enter para executar.
;  App .ENZ cru (org 0) — cabeçalho via tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_RECT    1
%define API_TEXT    2
%define API_TITLE   4
%define API_EXEC    9
%define API_INVAL   12
%define API_ALLOC   13
%define API_FSOPEN  25
%define API_FSREAD  27

%define LIST_Y      64
%define ROW_H       18
%define SCROLL_W    14
%define HDR_H       30

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

; ---------------------------------------------------------------- init ------
ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        lea rdi, [s_title]
        mov rax, [r12 + 8*API_TITLE]
        call rax
        ; abre /APPS
        lea rdi, [s_apps]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        cmp eax, -1
        je .noapps
        mov [apps_ino], eax
        ; buffer de dirents (40 KB ~ 1280 entradas)
        mov edi, 40960
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        test rax, rax
        jz .noapps
        mov [dirbuf], rax
        ; lê o diretório INTEIRO de uma vez (fs_read no ino do dir)
        mov edi, [apps_ino]
        mov rsi, rax
        mov edx, 40960
        mov rax, [r12 + 8*API_FSREAD]
        call rax
        cmp eax, 32
        jb .noapps
        mov [dirbytes], eax
        ; conta entradas válidas
        mov rbx, rax                   ; bytes
        xor ecx, ecx                   ; offset
        xor edx, edx                   ; count
.cnt:
        cmp ecx, ebx
        jae .cntd
        mov r8, [dirbuf]
        add r8, rcx
        cmp byte [r8], 0
        je .cntn
        cmp dword [r8 + 24], 0         ; ino
        je .cntn
        inc edx
.cntn:
        add ecx, 32
        jmp .cnt
.cntd:
        mov [app_total], edx
        ; cursor no topo
        mov dword [scroll], 0
        mov dword [sel], 0
        jmp epilogue
.noapps:
        mov dword [app_total], 0
        mov dword [dirbytes], 0
        jmp epilogue

; ---------------------------------------------------------------- key -------
ev_key:
        mov eax, [r13+16]
        cmp eax, 0x86                  ; SP_UP — seta cima
        je k_up
        cmp eax, 0x87                  ; SP_DOWN — seta baixo
        je k_down
        cmp eax, 0x8C                  ; SP_PGUP
        je k_pgup
        cmp eax, 0x8D                  ; SP_PGDN
        je k_pgdn
        cmp eax, 0x8A                  ; SP_HOME
        je k_home
        cmp eax, 0x8B                  ; SP_END
        je k_end
        cmp eax, 13                    ; Enter
        je k_enter
        jmp epilogue
k_up:
        cmp dword [sel], 0
        je .out
        dec dword [sel]
        call fix_scroll
.out:   call invalidate
        jmp epilogue
k_down:
        mov eax, [sel]
        inc eax
        cmp eax, [app_total]
        jae .out
        mov [sel], eax
        call fix_scroll
.out:   call invalidate
        jmp epilogue
k_pgup:
        sub dword [scroll], 14
        cmp dword [scroll], 0
        jge .a
        mov dword [scroll], 0
.a:     mov eax, [scroll]
        mov [sel], eax
        call invalidate
        jmp epilogue
k_pgdn:
        add dword [scroll], 14
        call clamp_scroll
        mov eax, [scroll]
        add eax, 13
        cmp eax, [app_total]
        jb .b
        mov eax, [app_total]
        test eax, eax
        jz .b
        dec eax
.b:     mov [sel], eax
        call invalidate
        jmp epilogue
k_home:
        mov dword [sel], 0
        mov dword [scroll], 0
        call invalidate
        jmp epilogue
k_end:
        mov eax, [app_total]
        test eax, eax
        jz .out
        dec eax
        mov [sel], eax
        call fix_scroll
.out:   call invalidate
        jmp epilogue
k_enter:
        call launch_sel
        jmp epilogue

; ---------------------------------------------------------------- mouse -----
ev_mouse:
        mov eax, [r13+32]
        test eax, 1                    ; clique (botão)
        jz .out
        mov ebx, [r13+16]              ; x
        mov ebp, [r13+24]              ; y
        ; clique na área da lista?
        mov eax, ebp
        sub eax, LIST_Y
        jl .out
        xor edx, edx
        mov ecx, ROW_H
        div ecx
        cmp eax, [visible]
        jae .out
        ; linha = scroll + eax
        add eax, [scroll]
        cmp eax, [app_total]
        jae .out
        mov [sel], eax
        call launch_sel
.out:
        jmp epilogue

; ---------------------------------------------------------------- paint -----
ev_paint:
        call render
        jmp epilogue

; ================================================================ helpers ===

invalidate:
        mov rax, [r12 + 8*API_INVAL]
        call rax
        ret

clamp_scroll:
        mov eax, [app_total]
        sub eax, [visible]
        cmp dword [scroll], eax
        jle .ok
        mov [scroll], eax
.ok:    cmp dword [scroll], 0
        jge .ok2
        mov dword [scroll], 0
.ok2:   ret

fix_scroll:
        mov eax, [sel]
        cmp eax, [scroll]
        jge .below
        mov [scroll], eax
        ret
.below:
        mov ecx, [scroll]
        add ecx, [visible]
        dec ecx
        cmp eax, ecx
        jle .ok3
        mov [scroll], eax
        sub eax, [visible]
        inc eax
        mov [scroll], eax
.ok3:   ret

; launch_sel: executa APPS/<nome da entrada sel>
launch_sel:
        mov eax, [sel]
        cmp eax, [app_total]
        jae .out
        ; offset da dirent
        shl eax, 5
        add eax, [dirbytes]
        sub eax, 32                    ; sanity: offset < dirbytes
        jae .ok
        ret
.ok:
        mov eax, [sel]
        shl eax, 5
        mov rcx, [dirbuf]
        add rcx, rax
        ; monta "APPS/" + nome
        lea rdi, [pathbuf]
        lea rsi, [s_prefix]
.cp1:
        mov al, [rsi]
        test al, al
        jz .cp1d
        mov [rdi], al
        inc rsi
        inc rdi
        jmp .cp1
.cp1d:
        ; nome (até 23 chars)
        mov edx, 23
.cp2:
        mov al, [rcx]
        test al, al
        jz .cp2d
        mov [rdi], al
        inc rcx
        inc rdi
        dec edx
        jnz .cp2
.cp2d:
        mov byte [rdi], 0
        lea rdi, [pathbuf]
        mov rax, [r12 + 8*API_EXEC]
        call rax
.out:
        ret

; ---------------------------------------------------------------- render ----
render:
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0D1524
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; cabeçalho com gradiente
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, HDR_H
        mov r8d, 0x1B7FC4
        mov r9d, 0x0D1524
        mov rax, [r12 + 8*22]          ; grad
        call rax
        ; título
        mov edi, 12
        mov esi, 9
        lea rdx, [s_hdr]
        mov r8d, 0xFFFFFF
        call text_at
        ; contador à direita do cabeçalho
        mov edi, [tw_]
        sub edi, 120
        mov esi, 9
        lea rdx, [s_count]
        mov r8d, 0xBFE3FF
        call text_at
        ; separador
        mov edi, 0
        mov esi, HDR_H
        mov edx, [tw_]
        mov ecx, 2
        mov r8d, 0x24406B
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; colunas visíveis
        mov eax, [th_]
        sub eax, LIST_Y
        sub eax, 8
        xor edx, edx
        mov ecx, ROW_H
        div ecx
        mov [visible], eax
        call clamp_scroll
        ; entradas
        xor ebx, ebx                   ; linha na tela
.rows:
        mov eax, [scroll]
        add eax, ebx
        cmp eax, [app_total]
        jae .rowsd
        ; realça a seleção
        mov edi, 4
        mov esi, LIST_Y
        mov eax, ebx
        imul eax, ROW_H
        add esi, eax
        mov edx, [tw_]
        sub edx, SCROLL_W + 8
        mov ecx, ROW_H
        mov eax, [scroll]
        add eax, ebx
        cmp eax, [sel]
        jne .nohl
        mov r8d, 0x24406B
        jmp .fill
.nohl:
        test ebx, 1
        jnz .odd
        mov r8d, 0x111C30
        jmp .fill
.odd:
        mov r8d, 0x0F1828
.fill:
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; nome da entrada (cor por categoria)
        mov eax, [scroll]
        add eax, ebx
        shl eax, 5
        mov rdx, [dirbuf]
        add rdx, rax                   ; rdx = direita do nome
        mov edi, 14
        mov esi, LIST_Y
        mov eax, ebx
        imul eax, ROW_H
        add esi, eax
        add esi, 3
        ; categoria pelas iniciais
        mov cl, [rdx]
        mov ch, [rdx+1]
        mov r8d, 0x9FB4D8              ; padrão
        cmp cl, 'J'
        jne .nc1
        mov r8d, 0x55D08A              ; JOGO = verde
        jmp .ncd
.nc1:   cmp cl, 'M'
        jne .nc2
        mov r8d, 0x62D0E8              ; MATH = ciano
        jmp .ncd
.nc2:   cmp cl, 'U'
        jne .nc3
        mov r8d, 0xE8C862              ; UTIL = amarelo
        jmp .ncd
.nc3:   cmp cl, 'V'
        jne .ncd
        mov r8d, 0xC77FD8              ; VISU = magenta
.ncd:
        call text_at
        inc ebx
        cmp ebx, [visible]
        jb .rows
.rowsd:
        ; scrollbar
        mov edi, [tw_]
        sub edi, SCROLL_W
        mov esi, LIST_Y
        mov edx, SCROLL_W
        mov ecx, [th_]
        sub ecx, LIST_Y
        sub ecx, 6
        mov r8d, 0x16233C
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; posição do polegar
        mov eax, [app_total]
        cmp eax, [visible]
        jbe .noscr
        ; thumb_h = visivel^2 / total (mín 20)
        mov eax, [visible]
        imul eax, eax
        xor edx, edx
        div dword [app_total]
        cmp eax, 20
        jge .th_ok
        mov eax, 20
.th_ok:
        mov [thumb_h], eax
        ; thumb_y = LIST_Y + (scroll * (h-th)) / (total-visivel)
        mov ecx, [th_]
        sub ecx, LIST_Y
        sub ecx, 6
        sub ecx, eax                    ; range
        mov eax, [scroll]
        imul eax, ecx
        mov ecx, [app_total]
        sub ecx, [visible]
        xor edx, edx
        div ecx
        add eax, LIST_Y
        mov [thumb_y], eax
        mov edi, [tw_]
        sub edi, SCROLL_W + 2
        mov esi, [thumb_y]
        mov edx, SCROLL_W - 4
        mov ecx, [thumb_h]
        mov r8d, 0x3D5A8F
        mov rax, [r12 + 8*API_RECT]
        call rax
.noscr:
        ; rodapé
        mov edi, 12
        mov esi, [th_]
        sub esi, 18
        lea rdx, [s_footer]
        mov r8d, 0x66809E
        call text_at
        ret

; text_at: edi=x esi=y rdx=str r8d=cor
text_at:
        push rdi
        push rsi
        push rdx
        push r8
        mov rdi, rdx
        call slen
        mov ecx, eax
        pop r8
        pop rdx
        pop rsi
        pop rdi
        mov rax, [r12 + 8*API_TEXT]
        jmp rax

slen:
        xor eax, eax
.loop:
        cmp byte [rdi + rax], 0
        je .done
        inc eax
        cmp eax, 40
        jb .loop
.done:
        ret

; ================================================================ dados =====
s_title:  db "Loja de Apps", 0
s_hdr:    db "LOJA DE APPS — EnzoOS", 0
s_apps:   db "APPS", 0
s_prefix: db "APPS/", 0
s_count:  db "1000+ apps", 0
s_footer: db "Setas/PgUp/PgDn navegam — clique ou Enter executa", 0

tw_:      dd 0
th_:      dd 0
apps_ino: dd 0
dirbuf:   dq 0
dirbytes: dd 0
app_total dd 0
scroll:   dd 0
sel:      dd 0
visible:  dd 16
thumb_h:  dd 20
thumb_y:  dd 0
pathbuf:  times 32 db 0
