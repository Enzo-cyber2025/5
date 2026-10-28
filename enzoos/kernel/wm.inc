; =============================================================================
;  EnzoOS — kernel/wm.inc: gerenciador de janelas, barra de tarefas, menu
;  Iniciar, ícones da área de trabalho, caixas modais e loop de eventos.
; =============================================================================
%ifndef WM_INC
%define WM_INC

section .ktext

; -----------------------------------------------------------------------------
k_wm_init:
        mov dword [wnd_count], 0
        mov qword [wnd_top], 0
        mov qword [wnd_bottom], 0
        mov dword [menu_open], 0
        mov dword [menu_sel], -1
        mov dword [drag_wnd], 0
        mov dword [modal_active], 0
        call clock_update
        ret

; -----------------------------------------------------------------------------
; wnd_find_free -> rax = ptr (0 se cheio)
; -----------------------------------------------------------------------------
wnd_find_free:
        lea rax, [wnd_array]
        xor ecx, ecx
.loop:
        cmp ecx, MAX_WND
        jae .none
        cmp dword [rax + 0], 0        ; W_NEXT==0 e usado? — campo "used" no início
        ; usa flag: bit31 de W_APP? — melhor: W_PREV==0 && W_NEXT==0 && top!=this
        ; padrão simples: campo dedicado W_USED?? — W_NEXT offset 0 serve:
        ; janelas na lista têm NEXT ou PREV != 0; a primeira pode ter ambos 0...
        ; — usa contagem: varre e checa W_H == 0
        cmp dword [rax + W_H], 0
        je .found
        add rax, W_SIZE
        inc ecx
        jmp .loop
.found:
        ret
.none:
        xor rax, rax
        ret

; -----------------------------------------------------------------------------
; wnd_create: edi=x, esi=y, edx=w, ecx=h, r8=title, r9d=app_slot (-1 = sem)
;             -> rax = janela (0 = falhou)
; -----------------------------------------------------------------------------
wnd_create:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        mov r13d, esi
        mov r14d, edx
        mov r15d, ecx
        call wnd_find_free
        test rax, rax
        jz .fail
        mov rbx, rax
        ; buffer da janela
        mov rdi, r14
        imul rdi, r15
        shl rdi, 2
        call k_alloc
        test rax, rax
        jz .fail
        mov [rbx + W_BUF], rax
        mov [rbx + W_X], r12d
        mov [rbx + W_Y], r13d
        mov [rbx + W_W], r14d
        mov [rbx + W_H], r15d
        mov dword [rbx + W_FLAGS], 0
        ; título
        xor ecx, ecx
.tcopy:
        cmp ecx, 31
        jae .tdone
        mov al, [r8 + rcx]
        mov [rbx + W_TITLE + rcx], al
        test al, al
        jz .tdone
        inc ecx
        jmp .tcopy
.tdone:
        mov byte [rbx + W_TITLE + 31], 0
        mov [rbx + W_APP], r9d
        ; insere no topo da z-list
        mov rax, [wnd_top]
        mov [rbx + W_NEXT], rax
        mov qword [rbx + W_PREV], 0
        test rax, rax
        jz .first
        mov [rax + W_PREV], rbx
        jmp .linked
.first:
        mov [wnd_bottom], rbx
.linked:
        mov [wnd_top], rbx
        inc dword [wnd_count]
        ; diag: janela criada (titulo, total)
        push rax
        push rdi
        push rsi
        push rcx
        push rdx
        push r8
        push r9
        push r10
        push r11
        mov rdi, s_wnd_diag
        call k_log
        lea rdi, [rbx + W_TITLE]
        call k_log
        mov edi, [wnd_count]
        call k_log_hex
        pop r11
        pop r10
        pop r9
        pop r8
        pop rdx
        pop rcx
        pop rsi
        pop rdi
        pop rax
        call wnd_render_chrome
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        call damage_add
        mov rax, rbx
        jmp .done
.fail:
        xor rax, rax
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; wnd_unlink: rbx = janela (remove da z-list)
; -----------------------------------------------------------------------------
wnd_unlink:
        mov rax, [rbx + W_NEXT]
        mov rdx, [rbx + W_PREV]
        test rdx, rdx
        jz .no_prev
        mov [rdx + W_NEXT], rax
        jmp .chk_next
.no_prev:
        mov [wnd_top], rax
.chk_next:
        test rax, rax
        jz .no_next
        mov [rax + W_PREV], rdx
        ret
.no_next:
        mov [wnd_bottom], rdx
        ret

; -----------------------------------------------------------------------------
; wnd_focus: rbx = janela -> topo da z-list
; -----------------------------------------------------------------------------
wnd_focus:
        cmp rbx, [wnd_top]
        je .already
        mov r12, [wnd_top]            ; antiga topo
        push rbx
        call wnd_unlink
        mov rax, [wnd_top]
        mov [rbx + W_NEXT], rax
        mov qword [rbx + W_PREV], 0
        test rax, rax
        jz .first
        mov [rax + W_PREV], rbx
        jmp .linked
.first:
        mov [wnd_bottom], rbx
.linked:
        mov [wnd_top], rbx
        ; re-render dos chromes afetados
        mov rbx, r12
        test rbx, rbx
        jz .no_old
        call wnd_render_chrome
        call wnd_damage
.no_old:
        pop rbx
        call wnd_render_chrome
        call wnd_damage
.already:
        ret

; -----------------------------------------------------------------------------
; wnd_damage: rbx = janela -> marca a região como suja
; -----------------------------------------------------------------------------
wnd_damage:
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        jmp damage_add

; -----------------------------------------------------------------------------
; wnd_destroy: rbx = janela
; -----------------------------------------------------------------------------
wnd_destroy:
        push rbx
        call wnd_unlink
        dec dword [wnd_count]
        push rax
        push rdi
        push rsi
        push rcx
        push rdx
        mov rdi, s_wnd_diag2
        call k_log
        mov edi, [wnd_count]
        call k_log_hex
        pop rdx
        pop rcx
        pop rsi
        pop rdi
        pop rax
        ; buffer
        mov rdi, [rbx + W_BUF]
        mov esi, [rbx + W_W]           ; dword!
        imul esi, [rbx + W_H]
        shl rsi, 2
        call k_free_bytes
        call wnd_damage
        mov dword [rbx + W_H], 0
        mov qword [rbx + W_BUF], 0
        mov qword [rbx + W_NEXT], 0
        mov qword [rbx + W_PREV], 0
        pop rbx
        ret

; -----------------------------------------------------------------------------
; wnd_render_chrome: rbx = janela — pinta estrutura na própria janela
; -----------------------------------------------------------------------------
wnd_render_chrome:
        push rbx
        push r12
        push r13
        push r14
        push r15
        ; superfície = buffer da janela
        mov rdi, [rbx + W_BUF]
        mov esi, [rbx + W_W]
        mov edx, [rbx + W_H]
        mov ecx, [rbx + W_W]
        shl ecx, 2
        call surf_set
        ; fundo do conteúdo
        xor edi, edi
        mov esi, TITLE_H
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        sub ecx, TITLE_H
        mov r14d, COL_PANEL
        call surf_fill
        ; barra de título em gradiente (nova renderização)
        xor edi, edi
        xor esi, esi
        mov edx, [rbx + W_W]
        mov ecx, TITLE_H
        mov r8d, 0x0E1830                     ; topo
        mov r9d, 0x13203C                     ; base
        cmp rbx, [wnd_top]
        jne .dim
        mov r8d, 0x1C3B72                     ; janela ativa
        mov r9d, 0x142A50
.dim:
        call g2_grad
        ; filete accent no topo
        xor edi, edi
        xor esi, esi
        mov edx, [rbx + W_W]
        mov ecx, 2
        mov r8d, COL_ACCENT
        mov r9d, 0x2D9CDB
        call g2_grad
        ; título
        mov edi, 10
        mov esi, 10
        lea rdx, [rbx + W_TITLE]
        call k_strlen
        mov ecx, eax
        lea rdx, [rbx + W_TITLE]
        mov r13d, COL_WHITE
        call surf_text
        ; botão fechar (arredondado)
        mov edi, [rbx + W_W]
        sub edi, 22
        mov esi, 6
        mov edx, 16
        mov ecx, 16
        mov r8d, 5
        mov r9d, 0xFF7A2E38
        cmp [hover_close], rbx
        jne .nohover
        mov r9d, 0xFFB54552
.nohover:
        call g2_round_blend
        ; "x"
        mov edi, [rbx + W_W]
        sub edi, 18
        mov esi, 10
        mov ecx, 'x'
        mov r13d, COL_WHITE
        call surf_char
        ; borda
        mov edi, 0
        mov esi, TITLE_H - 1
        mov edx, [rbx + W_W]
        mov ecx, 1
        mov r14d, 0x2A3B57
        call surf_fill
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; ícones da área de trabalho
; -----------------------------------------------------------------------------
%define ICON_COUNT 6

draw_icons:
        ; desenha todos os ícones na sombra (durante o compose é chamada por região)
        xor r12d, r12d
.loop:
        cmp r12d, ICON_COUNT
        jae .done
        mov edi, [icon_x]
        mov esi, [icon_y]
        mov eax, r12d
        imul eax, 104
        add esi, eax
        ; guarda origem
        mov [tmp_x], edi
        mov [tmp_y], esi
        ; arte 32x32
        lea rax, [icon_art_table]
        mov rax, [rax + r12*8]
        mov [tmp_src], rax
        mov r13d, r12d
        cmp r13d, [hover_icon]
        jne .no_hover
        ; realce: fundo
        call surf_use_shadow
        mov edi, [tmp_x]
        sub edi, 6
        mov esi, [tmp_y]
        sub esi, 6
        mov edx, 44
        mov ecx, 44
        mov r14d, 0x1B3050
        call surf_fill
.no_hover:
        call surf_use_shadow
        xor r10d, r10d
.row:
        cmp r10d, 32
        jae .label
        xor r11d, r11d
.col:
        cmp r11d, 32
        jae .row_next
        mov rax, [tmp_src]
        mov r9d, r10d
        shl r9d, 5
        add r9d, r11d
        shl r9d, 2
        mov eax, [rax + r9]
        test eax, eax
        jz .skip
        mov [tmp_color], eax
        push rdi
        push rsi
        mov edi, [tmp_x]
        add edi, r11d
        mov esi, [tmp_y]
        add esi, r10d
        mov eax, [tmp_color]
        call px_screen
        pop rsi
        pop rdi
.skip:
        inc r11d
        jmp .col
.row_next:
        inc r10d
.label:
        ; rótulo
        lea rax, [icon_name_table]
        mov rdx, [rax + r12*8]
        push rdx
        call k_strlen
        mov ecx, eax
        pop rdx
        ; centraliza sob o ícone (32 px de largura)
        mov edi, [tmp_x]
        add edi, 16
        mov eax, ecx
        shl eax, 3
        shr eax, 1
        sub edi, eax
        mov esi, [tmp_y]
        add esi, 36
        mov r13d, COL_GRAY
        call surf_text
        inc r12d
        jmp .loop
.done:
        ret

; -----------------------------------------------------------------------------
; barra de tarefas (desenha apenas na interseção com o dano)
; -----------------------------------------------------------------------------
draw_taskbar:
        ; interseção do dano com a barra
        mov eax, [screen_h]
        sub eax, TASKBAR_H
        mov [tb_y], eax
        ; o dano intersecta?
        mov eax, [dam_y]
        add eax, [dam_h]
        cmp eax, [tb_y]
        jbe .skip
        call surf_use_shadow
        ; fundo translúcido (deixa ver o que está atrás)
        mov edi, 0
        mov esi, [tb_y]
        mov edx, [screen_w]
        mov ecx, TASKBAR_H
        mov r8d, 0xD60D1524
        call g2_blend_fill
        ; linha accent em gradiente no topo
        mov edi, 0
        mov esi, [tb_y]
        mov edx, [screen_w]
        mov ecx, 2
        mov r8d, COL_ACCENT
        mov r9d, 0x2D9CDB
        call g2_grad
        ; botão Início
        mov edi, 8
        mov esi, [tb_y]
        add esi, 6
        mov [tmp_x], edi
        mov [tmp_y], esi
        mov edx, 108
        mov ecx, 32
        mov r8d, 9
        mov r9d, 0xFF18233B
        cmp dword [hover_start], 0
        je .st
        mov r9d, 0xFF24365C
.st:
        cmp dword [menu_open], 0
        je .st2
        mov r9d, 0xFF2D4570
.st2:
        call g2_round_blend
        ; quadradinho accent
        mov edi, [tmp_x]
        add edi, 8
        mov esi, [tmp_y]
        add esi, 9
        mov edx, 14
        mov ecx, 14
        mov r14d, COL_ACCENT
        call surf_fill
        mov edi, [tmp_x]
        add edi, 11
        mov esi, [tmp_y]
        add esi, 11
        mov edx, 8
        mov ecx, 10
        mov r14d, 0x0D1524
        call surf_fill
        ; texto "Início"
        mov edi, [tmp_x]
        add edi, 30
        mov esi, [tmp_y]
        add esi, 12
        lea rdx, [s_inicio]
        mov ecx, s_inicio_len
        mov r13d, COL_WHITE
        call surf_text
        ; botões das janelas
        xor r12d, r12d                ; índice do botão
        mov rbx, [wnd_bottom]
.wloop:
        test rbx, rbx
        jz .wdone
        mov edi, 128
        mov eax, r12d
        imul eax, 168
        add edi, eax
        cmp edi, [screen_w]
        jae .wdone
        mov esi, [tb_y]
        add esi, 6
        mov [tmp_x], edi
        mov [tmp_y], esi
        mov edx, 160
        mov ecx, 32
        mov r14d, 0x161F33
        cmp dword [hover_task], 0
        je .wt
        cmp r12d, [hover_task_idx]
        jne .wt
        mov r14d, 0x24365C
.wt:
        cmp rbx, [wnd_top]
        jne .wt2
        mov r14d, 0x27395F
.wt2:
        call surf_fill
        ; indicador da focada
        cmp rbx, [wnd_top]
        jne .noind
        mov edi, [tmp_x]
        mov esi, [tmp_y]
        add esi, 30
        mov edx, 160
        mov ecx, 2
        mov r14d, COL_ACCENT
        call surf_fill
.noind:
        ; título truncado (18 chars)
        mov edi, [tmp_x]
        add edi, 8
        mov esi, [tmp_y]
        add esi, 12
        lea rdx, [rbx + W_TITLE]
        mov ecx, 18
        mov r13d, COL_GRAY
        cmp rbx, [wnd_top]
        jne .tcol
        mov r13d, COL_WHITE
.tcol:
        call surf_text
        inc r12d
        mov rbx, [rbx + W_NEXT]
        jmp .wloop
.wdone:
        ; relógio
        mov edi, [screen_w]
        sub edi, 190
        mov esi, [tb_y]
        add esi, 12
        lea rdx, [clock_str]
        mov ecx, 19
        mov r13d, COL_WHITE
        call surf_text
.skip:
        ret

; -----------------------------------------------------------------------------
; menu Iniciar
; -----------------------------------------------------------------------------
menu_count:
        ; nº de apps .ce + 2 (Reiniciar, Desligar)
        mov eax, [menu_app_count]
        add eax, 2
        ret

menu_height:
        call menu_count
        imul eax, 26
        add eax, 30
        ret

draw_menu:
        cmp dword [menu_open], 0
        je .skip
        call surf_use_shadow
        ; interseção com o dano
        call menu_height
        mov [menu_h], eax
        mov eax, [screen_h]
        sub eax, TASKBAR_H
        sub eax, 8
        sub eax, [menu_h]
        mov [menu_y], eax
        ; sombra do menu
        mov edi, 8
        mov esi, [menu_y]
        mov edx, 268
        mov ecx, [menu_h]
        call g2_shadow
        ; painel com cantos arredondados
        mov edi, 8
        mov esi, [menu_y]
        mov edx, 268
        mov ecx, [menu_h]
        mov r8d, 12
        mov r9d, 0xF2121B2E
        call g2_round_blend
        ; filete accent
        mov edi, 24
        mov esi, [menu_y]
        add esi, 4
        mov edx, 4
        mov ecx, [menu_h]
        sub ecx, 8
        mov r8d, COL_ACCENT
        mov r9d, 0x2D9CDB
        call g2_grad
        ; rodapé translúcido
        mov edi, 12
        mov esi, [menu_y]
        add esi, [menu_h]
        sub esi, 24
        mov edx, 260
        mov ecx, 20
        mov r8d, 0x600D1422
        call g2_blend_fill
        mov edi, 20
        mov esi, [menu_y]
        add esi, [menu_h]
        sub esi, 16
        lea rdx, [s_menufoot]
        mov ecx, s_menufoot_len
        mov r13d, COL_DGRAY
        call surf_text
        ; itens
        xor r12d, r12d
.mitem:
        call menu_count
        cmp r12d, eax
        jae .skip
        ; item = app? (r12d < menu_app_count)
        mov edi, 8
        mov esi, [menu_y]
        add esi, 6
        mov eax, r12d
        imul eax, 26
        add esi, eax
        mov [tmp_x], edi
        mov [tmp_y], esi
        mov edx, 268
        mov ecx, 26
        mov r14d, 0x121B2E
        cmp r12d, [menu_sel]
        jne .nohl
        mov r14d, 0x24406B
.nohl:
        ; apps têm seta
        cmp r12d, [menu_app_count]
        jae .sysitem
        call surf_fill
        mov edi, [tmp_x]
        add edi, 14
        mov esi, [tmp_y]
        add esi, 9
        mov ecx, 0x25B6                 ; ▶
        mov r13d, COL_ACCENT
        call surf_char
        mov edi, [tmp_x]
        add edi, 34
        mov esi, [tmp_y]
        add esi, 9
        lea rdx, [menu_names]
        mov eax, r12d
        imul eax, 24
        add rdx, rax
        mov ecx, 20
        mov r13d, COL_WHITE
        call surf_text
        jmp .next
.sysitem:
        call surf_fill
        mov edi, [tmp_x]
        add edi, 14
        mov esi, [tmp_y]
        add esi, 9
        mov ecx, 0x25AA                 ; ■
        mov r13d, COL_YELLOW
        call surf_char
        mov edi, [tmp_x]
        add edi, 34
        mov esi, [tmp_y]
        add esi, 9
        cmp r12d, [menu_app_count]
        jne .chk2
        lea rdx, [s_reboot]
        mov ecx, s_reboot_len
        jmp .systext
.chk2:
        lea rdx, [s_shutdown]
        mov ecx, s_shutdown_len
.systext:
        mov r13d, COL_WHITE
        call surf_text
.next:
        inc r12d
        jmp .mitem
.skip:
        ret

; -----------------------------------------------------------------------------
; modal (MessageBox)
; -----------------------------------------------------------------------------
modal_open_msg:                    ; rdx=texto, r8=título
        mov rax, rdx
        mov rdx, r8
        ; copia título
        xor ecx, ecx
.tl:
        cmp ecx, 40
        jae .td
        mov al, [rdx + rcx]
        mov [modal_title + rcx], al
        test al, al
        jz .td
        inc ecx
        jmp .tl
.td:
        mov byte [modal_title + 40], 0
        xor ecx, ecx
.ml:
        cmp ecx, 120
        jae .md
        mov al, [rax + rcx]
        mov [modal_text + rcx], al
        test al, al
        jz .md
        inc ecx
        jmp .ml
.md:
        mov byte [modal_text + 120], 0
        mov dword [modal_active], 1
        mov dword [modal_ok_hover], 0
        call damage_all
        ret

modal_close:
        mov dword [modal_active], 0
        call damage_all
        ret

draw_modal:
        call surf_use_shadow
        ; caixa central 460x180
        mov eax, [screen_w]
        sub eax, 460
        shr eax, 1
        mov [modal_x], eax
        mov eax, [screen_h]
        sub eax, 240
        shr eax, 1
        mov [modal_y], eax
        mov edi, [modal_x]
        mov esi, [modal_y]
        mov edx, 460
        mov ecx, 180
        mov r14d, 0x101B30
        call surf_fill
        mov edi, [modal_x]
        mov esi, [modal_y]
        mov edx, 460
        mov ecx, 30
        mov r14d, COL_TITLE
        call surf_fill
        mov edi, [modal_x]
        add edi, 12
        mov esi, [modal_y]
        add esi, 11
        lea rdx, [modal_title]
        call k_strlen
        mov ecx, eax
        lea rdx, [modal_title]
        mov r13d, COL_WHITE
        call surf_text
        mov edi, [modal_x]
        add edi, 12
        mov esi, [modal_y]
        add esi, 48
        lea rdx, [modal_text]
        call k_strlen
        mov ecx, eax
        lea rdx, [modal_text]
        mov r13d, COL_GRAY
        call surf_text
        ; botão OK
        mov eax, [modal_x]
        add eax, 190
        mov [tmp_x], eax
        mov eax, [modal_y]
        add eax, 130
        mov [tmp_y], eax
        mov edi, [tmp_x]
        mov esi, [tmp_y]
        mov edx, 80
        mov ecx, 30
        mov r14d, COL_ACCENT
        cmp dword [modal_ok_hover], 0
        je .okc
        mov r14d, 0x1CC68C
.okc:
        call surf_fill
        mov edi, [tmp_x]
        add edi, 28
        mov esi, [tmp_y]
        add esi, 10
        lea rdx, [s_ok]
        mov ecx, s_ok_len
        mov r13d, COL_WHITE
        call surf_text
        ret

; modal_pump: espera o usuário clicar OK (com processamento de eventos)
modal_pump:
        push rbx
.loop:
        cmp dword [modal_active], 0
        je .done
        mov dword [foreign_quantum], 0
        call evt_poll
        call compose_if_dirty
        hlt
        jmp .loop
.done:
        pop rbx
        ret

; -----------------------------------------------------------------------------
; clock
; -----------------------------------------------------------------------------
clock_update:
        cld
        ; hora = rtc + uptime (segundos)
        mov eax, [uptime_ms]
        mov ecx, 1000
        xor edx, edx
        div ecx                        ; eax = segundos decorridos
        add eax, [rtc_sec]
        xor edx, edx
        mov ecx, 60
        div ecx
        mov [tmp_sec], edx             ; resto = segundos
        add eax, [rtc_min]
        xor edx, edx
        div ecx
        mov [tmp_min], edx
        add eax, [rtc_hour]
        mov ecx, 24
        xor edx, edx
        div ecx
        mov [tmp_hour], edx
        ; string "DD/MM/AAAA HH:MM:SS"
        lea rdi, [clock_str]
        mov eax, [rtc_day]
        call .two
        mov al, '/'
        stosb
        mov eax, [rtc_month]
        call .two
        mov al, '/'
        stosb
        mov eax, [rtc_year]
        add eax, 2000
        push rdi
        mov rdi, rax
        lea rsi, [numbuf]
        mov edx, 10
        call k_utoa
        pop rdi
        ; copia 4 dígitos
        mov al, [numbuf]
        stosb
        mov al, [numbuf+1]
        stosb
        mov al, ' '
        stosb
        mov eax, [tmp_hour]
        call .two
        mov al, ':'
        stosb
        mov eax, [tmp_min]
        call .two
        mov al, ':'
        stosb
        mov eax, [tmp_sec]
        call .two
        mov al, 0
        stosb
        ret
.two:
        push rdx
        push rax
        xor edx, edx
        mov ecx, 10
        div ecx
        add al, '0'
        mov [rdi], al
        add dl, '0'
        mov [rdi+1], dl
        add rdi, 2
        pop rax
        pop rdx
        ret

section .kdata
wnd_top:     dq 0
wnd_bottom:  dq 0
wm_magic:    dd 0x13572468               ; assinatura p/ achar wnd_count por scan
s_wnd_diag:  db "[wm] +janela:", 0
s_wnd_diag2: db "[wm] -janela, total:", 0
wnd_count:   dd 0
wnd_array:   times MAX_WND * W_SIZE db 0

menu_open:   dd 0
menu_sel:    dd -1
menu_app_count: dd 0
menu_names:  times 16*24 db 0
menu_h:      dd 0
menu_y:      dd 0

drag_wnd:    dq 0

hover_start: dd 0
hover_task:  dd 0
hover_task_idx: dd -1
hover_icon:  dd -1
hover_close: dq 0

modal_x:     dd 0
modal_y:     dd 0
modal_ok_hover: dd 0
modal_title: times 41 db 0
modal_text:  times 121 db 0

tb_y:        dd 0
clock_str:   times 24 db 0
tmp_sec:     dd 0
tmp_min:     dd 0
tmp_hour:    dd 0

tmp_src:     dq 0

icon_x:      dd 24
icon_y:      dd 60

icon_art_table:
        dq icon_terminal, icon_paint, icon_info, icon_calc, icon_notas, icon_plasma
icon_name_table:
        dq s_ic_terminal, s_ic_paint, s_ic_info, s_ic_calc, s_ic_notas, s_ic_plasma
icon_file_table:
        dq s_if_terminal, s_if_paint, s_if_info, s_if_calc, s_if_notas, s_if_plasma

s_inicio: db "Início"
s_inicio_len equ $ - s_inicio
s_menufoot: db "EnzoOS 1.0 — Assembly puro"
s_menufoot_len equ $ - s_menufoot
s_reboot: db "Reiniciar"
s_reboot_len equ $ - s_reboot
s_shutdown: db "Desligar"
s_shutdown_len equ $ - s_shutdown
s_ok: db "OK"
s_ok_len equ $ - s_ok
s_ic_terminal: db "Terminal", 0
s_ic_paint: db "Pintura", 0
s_ic_info: db "Sistema", 0
s_ic_calc: db "Calc", 0
s_ic_notas: db "Notas", 0
s_ic_plasma: db "Plasma", 0
s_if_terminal: db "TERMINAL.CE", 0
s_if_paint: db "PAINT.CE", 0
s_if_info: db "INFO.CE", 0
s_if_calc: db "CALC.CE", 0
s_if_notas: db "NOTAS.CE", 0
s_if_plasma: db "PLASMA.CE", 0

%endif
