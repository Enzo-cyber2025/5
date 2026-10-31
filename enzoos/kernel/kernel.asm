; =============================================================================
;  EnzoOS — kernel/kernel.asm: núcleo do sistema
;   * carregado em 0x100000 pelo stage1 (cabeçalho 'CE01', entry RVA em +8)
;   * monta com: nasm -f bin -o obj/kernel.bin kernel/kernel.asm
; =============================================================================
BITS 64
org 0x100000
default abs

%include "k.inc"

; =============================================================================
section .cehdr
; =============================================================================
        db "CE01"                       ; +0  magic
        dw CE_HDRSZ                     ; +4  tamanho do cabeçalho
        dw 0                            ; +6  flags
        dd k_main - $$                  ; +8  entry RVA
        dd 0                            ; +12 tamanho da imagem (via CEFS)
        dd 1                            ; +16 versão da API
        dw 0                            ; +20 win_w
        dw 0                            ; +22 win_h
        dd 0                            ; +24 reservado
        db "KERNEL", 0                  ; +28 nome
        times 64-($-$$) db 0

; =============================================================================
; módulos (reabrem .ktext/.kdata; o NASM anexa ao que já existe)
; =============================================================================
%include "serial.inc"
%include "lib.inc"
%include "cpu.inc"
%include "mm.inc"
%include "intr.inc"
%include "ps2.inc"
%include "gfx.inc"
%include "gfx2.inc"
%include "wm.inc"
%include "cefs.inc"
%include "exec.inc"
%include "inflate.inc"
%include "zip.inc"
%include "pe.inc"
%include "elf.inc"
%include "pci.inc"
%include "ahci.inc"
%include "hpet.inc"
%include "enzfs.inc"
%include "swap.inc"
%include "enz.inc"
%include "e1000.inc"
%include "net.inc"
%include "hda.inc"

; =============================================================================
section .ktext
; =============================================================================
k_main:
        cli
        cld
        mov rsp, 0x8F000
        xor ebp, ebp
        call k_serial_init
        mov rdi, s_banner
        call k_log
        call k_cpu_init
        mov rdi, s_b_cpu
        call k_log
        mov rdi, s_b_cpu2
        call k_log
        mov rdi, s_b_cpu3
        call k_log
        call k_mm_init
        mov rdi, s_b_mm
        call k_log
        call k_intr_init
        sti
        call k_ps2_init
        mov rdi, s_b_ps2
        call k_log
        call k_gfx_init
        mov rdi, s_b_gfx
        call k_log
        call k_cefs_init
        mov rdi, s_b_cefs
        call k_log
        call k_wm_init
        mov rdi, s_b_wm
        call k_log
        call k_hpet_init
        mov rdi, s_b_hpet
        call k_log
        call k_ahci_init
        mov rdi, s_b_ahci
        call k_log
        call k_enzfs_mount
        mov rdi, s_b_enzfs
        call k_log
        call k_swap_init
        mov rdi, s_b_swap
        call k_log
        call k_e1000_init
        mov rdi, s_b_e1000
        call k_log
        call k_net_init
        mov rdi, s_b_net
        call k_log
        call k_hda_init
        mov rdi, s_b_hda
        call k_log
        call k_rtc_read
        mov rdi, s_b_rtc
        call k_log
        ; diag PCI: leituras cruas do config space (q35: 00:1f.2 = AHCI)
        mov edi, 0x80000000 | (0 << 16) | (31 << 11) | (2 << 8)
        call pci_read32
        mov rdi, rax
        call k_log_hex
        mov edi, 0x80000000 | (0 << 16) | (0 << 11) | (0 << 8)
        call pci_read32
        mov rdi, rax
        call k_log_hex
        mov edi, 0x80000000 | (0 << 16) | (2 << 11) | (0 << 8)
        call pci_read32
        mov rdi, rax
        call k_log_hex
        mov edi, 0x80000000 | (0 << 16) | (1 << 11) | (0 << 8)
        call pci_read32
        mov rdi, rax
        call k_log_hex
        call clock_update
        ; semente aleatória
        mov eax, [rtc_sec]
        imul eax, eax, 91
        add eax, [uptime_ms]
        mov [rand_seed], eax
        ; aplicativos iniciais
        mov rdi, s_app1
        call app_launch
        mov rdi, s_app2
        call app_launch
        mov rdi, s_app3
        call app_launch
        ; laço principal
.mainloop:
        call evt_poll
        call compose_if_dirty
        hlt
        jmp .mainloop

; =============================================================================
; evt_poll: teclado, mouse e tique de 50 ms
; =============================================================================
evt_poll:
        push rbx
        push r12
        push r13
        push r14
        push r15
; ---------------- teclado ----------------
.kq:
        mov eax, [kq_head]
        cmp eax, [kq_tail]
        je .nokeys
        mov ecx, eax
        shl ecx, 4
        lea rbx, [kq_buf + rcx]
        mov r12d, [rbx]                 ; ch
        mov r13d, [rbx+4]               ; sc
        mov r14d, [rbx+8]               ; mods
        inc dword [kq_head]
        and dword [kq_head], 31         ; wrap: sem isto o head escapava do
        ; buffer de 32 entradas e o consumidor lia lixo forever (flood de eventos)
        ; modal engole tudo (enter/esc fecham)
        cmp dword [modal_active], 0
        je .not_modal
        cmp r12d, 13
        je .modal_close
        cmp r12d, SP_ESC
        je .modal_close
        jmp .kq
.modal_close:
        call modal_close
        jmp .kq
.not_modal:
        ; menu aberto
        cmp dword [menu_open], 0
        je .not_menu
        cmp r12d, SP_UP
        je .menu_up
        cmp r12d, SP_DOWN
        je .menu_down
        cmp r12d, 13
        je .menu_act
        cmp r12d, SP_ESC
        je .menu_esc
        jmp .kq
.menu_up:
        cmp dword [menu_sel], 0
        jle .kq
        dec dword [menu_sel]
        call menu_redraw
        jmp .kq
.menu_down:
        call menu_count
        cmp dword [menu_sel], eax
        jge .kq
        inc dword [menu_sel]
        call menu_redraw
        jmp .kq
.menu_act:
        mov edi, [menu_sel]
        call menu_item_activate
        jmp .kq
.menu_esc:
        mov dword [menu_open], 0
        call menu_redraw
        jmp .kq
.not_menu:
        ; atalhos globais Ctrl+Alt+X
        test r14d, 2
        jz .no_hotkey
        test r14d, 4
        jz .no_hotkey
        cmp r12d, 't'
        je .hk_term
        cmp r12d, 'i'
        je .hk_info
        cmp r12d, 'p'
        je .hk_paint
        cmp r12d, 'c'
        je .hk_calc
        cmp r12d, 'n'
        je .hk_notas
        cmp r12d, 's'
        je .hk_plasma
        cmp r12d, 'm'
        je .hk_menu
        jmp .kq
.hk_menu:
        xor dword [menu_open], 1
        mov dword [menu_sel], 0         ; 1º item pré-selecionado: N downs
        call menu_redraw                ; selecionam o item N (índices 0-based)
        jmp .kq
.hk_term:
        mov rdi, s_app1
        call app_launch
        jmp .kq
.hk_info:
        mov rdi, s_app2
        call app_launch
        jmp .kq
.hk_paint:
        mov rdi, s_app4
        call app_launch
        jmp .kq
.hk_calc:
        mov rdi, s_app5
        call app_launch
        jmp .kq
.hk_notas:
        mov rdi, s_app6
        call app_launch
        jmp .kq
.hk_plasma:
        mov rdi, s_app3
        call app_launch
        jmp .kq
.no_hotkey:
        ; janela focada recebe
        mov rbx, [wnd_top]
        test rbx, rbx
        jz .kq
        test dword [rbx + W_FLAGS], 2
        jnz .kq
        cmp dword [rbx + W_APP], -1
        je .kq
        mov edi, [rbx + W_APP]
        mov esi, EV_KEY
        mov edx, r12d
        mov ecx, r13d
        mov r8d, r14d
        xor r9d, r9d
        call app_dispatch
        jmp .kq
.nokeys:
; ---------------- mouse ----------------
        mov eax, [mouse_btns]
        cmp eax, [mouse_last_btns]
        jne .mouse
        cmp dword [mouse_moved], 0
        jne .mouse
        jmp .tick
.mouse:
        call mouse_dispatch
.tick:
; ---------------- tique de 50 ms ----------------
        mov eax, [uptime_ms]
        sub eax, [last_dispatch_ms]
        cmp eax, TICK_MS
        jb .done
        mov eax, [uptime_ms]
        mov [last_dispatch_ms], eax
        ; relógio
        call clock_update
        mov eax, [uptime_ms]
        xor edx, edx
        mov ecx, 1000
        div ecx
        cmp eax, [last_sec]
        je .no_clock
        mov [last_sec], eax
        call damage_taskbar
.no_clock:
        ; EV_TICK para cada app
        xor ebx, ebx
.tkloop:
        cmp ebx, MAX_APPS
        jae .tkdone
        lea rax, [app_slots]
        imul rax, rbx, A_SIZEOF
        cmp dword [rax + A_USED], 0
        je .tknext
        mov edi, ebx
        mov esi, EV_TICK
        xor edx, edx
        xor ecx, ecx
        xor r8d, r8d
        xor r9d, r9d
        call app_dispatch
.tknext:
        inc ebx
        jmp .tkloop
.tkdone:
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; =============================================================================
; mouse_dispatch
; =============================================================================
mouse_dispatch:
        push rbx
        push r12
        push r13
        push r14
        push r15
        ; posição antiga do cursor
        mov r12d, [mouse_x]
        mov r13d, [mouse_y]
        ; press/release
        mov eax, [mouse_btns]
        mov ecx, [mouse_last_btns]
        mov edx, eax
        not edx
        and edx, ecx                    ; release = novo&~antigo... (~novo & antigo)
        ; — release correto: ~new & old
        mov edx, eax
        not edx
        and edx, ecx
        mov [m_release], edx
        mov edx, eax
        not ecx
        and edx, ecx                    ; press = new & ~old
        mov [m_press], edx
        mov [mouse_last_btns], eax
        mov dword [mouse_moved], 0
        ; dano do cursor (união antiga + nova)
        mov edi, r12d
        mov esi, r13d
        mov edx, cursor_w
        mov ecx, cursor_h
        call damage_add
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        mov edx, cursor_w
        mov ecx, cursor_h
        call damage_add
        ; ---- modal ----
        cmp dword [modal_active], 0
        je .not_modal
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call modal_ok_contains
        cmp eax, [modal_ok_hover]
        je .mnohov
        mov [modal_ok_hover], eax
        call modal_damage
.mnohov:
        cmp dword [m_press], 1
        jne .out
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call modal_ok_contains
        test eax, eax
        jz .out
        call modal_close
        jmp .out
.not_modal:
        ; ---- arraste de janela ----
        cmp qword [drag_wnd], 0
        je .no_drag
        mov rbx, [drag_wnd]
        mov eax, [mouse_btns]
        test eax, 1
        jz .end_drag
        ; move
        mov edi, [mouse_x]
        sub edi, [rbx + W_DRAGDX]
        cmp edi, 0
        jge .dx_ok
        xor edi, edi
.dx_ok:
        mov eax, [screen_w]
        sub eax, 40
        cmp edi, eax
        jle .dx_ok2
        mov edi, eax
.dx_ok2:
        mov [rbx + W_X], edi
        mov esi, [mouse_y]
        sub esi, [rbx + W_DRAGDY]
        cmp esi, 0
        jge .dy_ok
        xor esi, esi
.dy_ok:
        mov eax, [screen_h]
        sub eax, 24
        cmp esi, eax
        jle .dy_ok2
        mov esi, eax
.dy_ok2:
        mov [rbx + W_Y], esi
        call wnd_damage
        jmp .out
.end_drag:
        mov qword [drag_wnd], 0
.no_drag:
        ; ---- menu aberto ----
        cmp dword [menu_open], 0
        je .not_menu
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call menu_item_at
        cmp eax, [menu_sel]
        je .menu_nohov
        mov [menu_sel], eax
        call menu_redraw
.menu_nohov:
        cmp dword [m_press], 1
        jne .out
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call menu_item_at
        cmp eax, -1
        je .menu_close_m
        mov edi, eax
        call menu_item_activate
        jmp .out
.menu_close_m:
        mov dword [menu_open], 0
        call menu_redraw
        jmp .out
.not_menu:
        ; captura ativa e soltou o botão? limpa
        mov rbx, [wnd_top]
        test rbx, rbx
        jz .no_capture_rel
        test dword [rbx + W_FLAGS], 4
        jz .no_capture_rel
        cmp dword [m_release], 1
        jne .no_capture_rel
        and dword [rbx + W_FLAGS], -5
        call wnd_damage
.no_capture_rel:
        cmp dword [m_press], 1
        je .click
        ; ---- hovers / movimento ----
        call wm_update_hovers
        ; captura ativa? envia à janela capturada
        mov rbx, [wnd_top]
        test rbx, rbx
        jz .hover_evt
        test dword [rbx + W_FLAGS], 4
        jz .hover_evt
        cmp dword [rbx + W_APP], -1
        je .out
        mov edi, [rbx + W_APP]
        mov esi, EV_MOUSE
        mov edx, [mouse_x]
        sub edx, [rbx + W_X]
        dec edx
        mov ecx, [mouse_y]
        sub ecx, [rbx + W_Y]
        sub ecx, TITLE_H
        mov r8d, [mouse_btns]
        xor r9d, r9d
        call app_dispatch
        jmp .out
.hover_evt:
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call wnd_at
        test rax, rax
        jz .out
        mov rbx, rax
        cmp dword [rbx + W_APP], -1
        je .out
        mov edi, [rbx + W_APP]
        mov esi, EV_MOUSE
        mov edx, [mouse_x]
        sub edx, [rbx + W_X]
        dec edx
        mov ecx, [mouse_y]
        sub ecx, [rbx + W_Y]
        sub ecx, TITLE_H
        mov r8d, [mouse_btns]
        xor r9d, r9d
        call app_dispatch
        jmp .out
.click:
        ; ---- clique ----
        ; barra de tarefas?
        mov eax, [screen_h]
        sub eax, TASKBAR_H
        cmp [mouse_y], eax
        jl .not_task
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call taskbar_start_contains
        test eax, eax
        jnz .toggle_menu
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call taskbar_btn_at
        cmp eax, -1
        je .not_task
        mov edi, eax
        call taskbar_wnd_by_idx
        test rax, rax
        jz .not_task
        mov rbx, rax
        test dword [rbx + W_FLAGS], 2
        jnz .restore_w
        cmp rbx, [wnd_top]
        je .minimize_w
        call wnd_focus
        call wnd_damage
        jmp .out
.restore_w:
        and dword [rbx + W_FLAGS], -3
        call wnd_focus
        call wnd_damage
        jmp .out
.minimize_w:
        or dword [rbx + W_FLAGS], 2
        call wnd_damage
        call damage_taskbar
        jmp .out
.toggle_menu:
        xor dword [menu_open], 1
        mov dword [menu_sel], 0         ; mesmo comportamento do atalho ctrl-alt-m
        call menu_redraw
        jmp .out
.not_task:
        ; ícones?
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call icon_at
        cmp eax, -1
        je .not_icon
        lea rdx, [icon_file_table]
        mov rdi, [rdx + rax*8]
        call k_exec
        jmp .out
.not_icon:
        ; janelas
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call wnd_at
        test rax, rax
        jz .out
        mov rbx, rax
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        mov rdx, rbx
        call wnd_close_contains
        test eax, eax
        jnz .close_wnd
        mov eax, [mouse_y]
        sub eax, [rbx + W_Y]
        cmp eax, TITLE_H
        jl .start_drag
        ; conteúdo: foca + captura + evento
        call wnd_focus
        or dword [rbx + W_FLAGS], 4
        cmp dword [rbx + W_APP], -1
        je .out
        mov edi, [rbx + W_APP]
        mov esi, EV_MOUSE
        mov edx, [mouse_x]
        sub edx, [rbx + W_X]
        dec edx
        mov ecx, [mouse_y]
        sub ecx, [rbx + W_Y]
        sub ecx, TITLE_H
        mov r8d, [mouse_btns]
        mov r9d, 1
        call app_dispatch
        jmp .out
.start_drag:
        call wnd_focus
        mov [drag_wnd], rbx
        mov eax, [mouse_x]
        sub eax, [rbx + W_X]
        mov [rbx + W_DRAGDX], eax
        mov eax, [mouse_y]
        sub eax, [rbx + W_Y]
        mov [rbx + W_DRAGDY], eax
        jmp .out
.close_wnd:
        mov edi, [rbx + W_APP]
        cmp edi, -1
        je .destroy_only
        call app_close
        jmp .out
.destroy_only:
        call wnd_destroy
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; =============================================================================
; auxiliares de hit-test
; =============================================================================

; wnd_at: edi=x, esi=y -> rax = janela do topo sob o ponto (0 se nenhuma)
wnd_at:
        mov rbx, [wnd_top]
.loop:
        test rbx, rbx
        jz .no
        test dword [rbx + W_FLAGS], 2
        jnz .next
        mov eax, [rbx + W_X]
        cmp edi, eax
        jl .next
        mov eax, [rbx + W_X]
        add eax, [rbx + W_W]
        cmp edi, eax
        jge .next
        mov eax, [rbx + W_Y]
        cmp esi, eax
        jl .next
        mov eax, [rbx + W_Y]
        add eax, [rbx + W_H]
        cmp esi, eax
        jge .next
        mov rax, rbx
        ret
.next:
        mov rbx, [rbx + W_NEXT]
        jmp .loop
.no:
        xor rax, rax
        ret

; wnd_close_contains: edi=x, esi=y, rdx=wnd -> eax=1 no botão fechar
wnd_close_contains:
        push rbx
        mov rbx, rdx
        xor eax, eax
        mov ecx, [rbx + W_X]
        add ecx, [rbx + W_W]
        sub ecx, 22
        cmp edi, ecx
        jl .no
        mov ecx, [rbx + W_X]
        add ecx, [rbx + W_W]
        sub ecx, 6
        cmp edi, ecx
        jge .no
        mov ecx, [rbx + W_Y]
        add ecx, 6
        cmp esi, ecx
        jl .no
        mov ecx, [rbx + W_Y]
        add ecx, 22
        cmp esi, ecx
        jge .no
        mov eax, 1
.no:
        pop rbx
        ret

; taskbar_start_contains: edi=x, esi=y -> eax=1 no botão Início
taskbar_start_contains:
        xor eax, eax
        mov ecx, [screen_h]
        sub ecx, TASKBAR_H
        add ecx, 6
        cmp esi, ecx
        jl .no
        mov ecx, [screen_h]
        sub ecx, 6
        cmp esi, ecx
        jge .no
        cmp edi, 8
        jl .no
        cmp edi, 116
        jge .no
        mov eax, 1
.no:
        ret

; taskbar_btn_at: edi=x, esi=y -> eax=índice do botão ou -1
taskbar_btn_at:
        xor eax, eax
        mov ecx, [screen_h]
        sub ecx, TASKBAR_H
        add ecx, 6
        cmp esi, ecx
        jl .no
        mov ecx, [screen_h]
        sub ecx, 6
        cmp esi, ecx
        jge .no
        cmp edi, 128
        jl .no
        sub edi, 128
        mov eax, edi
        xor edx, edx
        mov ecx, 168
        div ecx                        ; eax = idx, edx = resto
        cmp edx, 160
        jb .ok
.no:
        mov eax, -1
.ok:
        ret

; taskbar_wnd_by_idx: edi=índice -> rax=janela (ordem = taskbar: fundo -> topo via W_PREV)
taskbar_wnd_by_idx:
        mov rbx, [wnd_bottom]
        xor esi, esi
.loop:
        test rbx, rbx
        jz .no
        cmp esi, edi
        je .found
        inc esi
        mov rbx, [rbx + W_PREV]
        jmp .loop
.found:
        mov rax, rbx
        ret
.no:
        xor rax, rax
        ret

; icon_at: edi=x, esi=y -> eax=índice ou -1
icon_at:
        mov eax, -1
        xor ecx, ecx
.loop:
        cmp ecx, ICON_COUNT
        jae .no
        mov edx, [icon_y]
        mov r8d, ecx
        imul r8d, 104
        add edx, r8d
        sub edx, 6
        cmp esi, edx
        jl .next
        add edx, 72
        cmp esi, edx
        jge .next
        mov edx, [icon_x]
        sub edx, 6
        cmp edi, edx
        jl .next
        add edx, 44
        cmp edi, edx
        jge .next
        mov eax, ecx
        ret
.next:
        inc ecx
        jmp .loop
.no:
        ret

; modal_ok_contains: edi=x, esi=y -> eax=1 se sobre o botão OK
modal_ok_contains:
        xor eax, eax
        mov ecx, [modal_x]
        add ecx, 190
        cmp edi, ecx
        jl .no
        mov ecx, [modal_x]
        add ecx, 270
        cmp edi, ecx
        jge .no
        mov ecx, [modal_y]
        add ecx, 130
        cmp esi, ecx
        jl .no
        mov ecx, [modal_y]
        add ecx, 160
        cmp esi, ecx
        jge .no
        mov eax, 1
.no:
        ret

; menu_item_at: edi=x, esi=y -> eax=índice do item ou -1
menu_item_at:
        mov eax, -1
        call menu_height
        mov r8d, eax
        mov r9d, [screen_h]
        sub r9d, TASKBAR_H
        sub r9d, 8
        sub r9d, r8d
        cmp edi, 8
        jl .no
        cmp edi, 276
        jge .no
        cmp esi, r9d
        jl .no
        mov eax, esi
        sub eax, r9d
        sub eax, 6
        cmp eax, 0
        jl .no
        xor edx, edx
        mov ecx, 26
        div ecx
        push rax
        call menu_count
        mov ecx, eax
        pop rax
        cmp eax, ecx
        jb .ok
        mov eax, -1
.no:
        ret
.ok:
        ret

; modal_damage
modal_damage:
        mov edi, [modal_x]
        mov esi, [modal_y]
        mov edx, 460
        mov ecx, 180
        jmp damage_add

; menu_redraw: marca a região do menu + barra
menu_redraw:
        call menu_height
        mov ecx, eax
        mov eax, [screen_h]
        sub eax, TASKBAR_H
        sub eax, 8
        sub eax, ecx
        mov esi, eax
        cmp esi, 0
        jge .y_ok
        xor esi, esi
.y_ok:
        mov edi, 0
        mov edx, 300
        add ecx, TASKBAR_H
        add ecx, 24
        jmp damage_add

; wnd_title_damage: rbx = janela
wnd_title_damage:
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, TITLE_H
        jmp damage_add

; damage_taskbar
damage_taskbar:
        mov edi, 0
        mov esi, [screen_h]
        sub esi, TASKBAR_H
        mov edx, [screen_w]
        mov ecx, TASKBAR_H
        jmp damage_add

; wm_update_hovers: recalcula realces e marca dano quando muda
wm_update_hovers:
        push rbx
        ; ---- Início ----
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call taskbar_start_contains
        mov ecx, eax
        cmp ecx, [hover_start]
        je .st_same
        mov [hover_start], ecx
        call damage_taskbar
.st_same:
        ; ---- botão fechar da janela sob o cursor ----
        mov r8, [hover_close]
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call wnd_at
        mov rbx, rax
        test rbx, rbx
        jz .cl_none
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        mov rdx, rbx
        call wnd_close_contains
        test eax, eax
        jz .cl_none
        mov [hover_close], rbx
        jmp .cl_chk
.cl_none:
        mov qword [hover_close], 0
.cl_chk:
        mov rax, [hover_close]
        cmp rax, r8
        je .tb_start
        test rax, rax
        jz .cl_old
        push rax
        mov rbx, rax
        call wnd_title_damage
        pop rax
.cl_old:
        test r8, r8
        jz .tb_start
        mov rbx, r8
        call wnd_title_damage
.tb_start:
        ; ---- botões da barra ----
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call taskbar_btn_at
        mov ecx, eax
        cmp ecx, [hover_task_idx]
        je .ic_start
        mov [hover_task_idx], ecx
        call damage_taskbar
.ic_start:
        ; ---- ícones ----
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        call icon_at
        mov ecx, eax
        cmp ecx, [hover_icon]
        je .ic_same
        cmp dword [hover_icon], -1
        je .ic_new
        mov edi, [icon_x]
        sub edi, 8
        mov esi, [icon_y]
        mov eax, [hover_icon]
        imul eax, 104
        add esi, eax
        sub esi, 8
        mov edx, 56
        mov ecx, 84
        call damage_add
.ic_new:
        mov [hover_icon], ecx
        cmp ecx, -1
        je .ic_same
        mov edi, [icon_x]
        sub edi, 8
        mov esi, [icon_y]
        mov eax, ecx
        imul eax, 104
        add esi, eax
        sub esi, 8
        mov edx, 56
        mov ecx, 84
        call damage_add
.ic_same:
        pop rbx
        ret

; app_close: edi=slot — encerra o app (QUIT, janela, memória)
app_close:
        push rbx
        mov [tmp_slot], edi
        lea rax, [app_slots]
        imul rax, rdi, A_SIZEOF
        mov rbx, rax
        mov edi, [tmp_slot]
        mov esi, EV_QUIT
        xor edx, edx
        xor ecx, ecx
        xor r8d, r8d
        xor r9d, r9d
        call app_dispatch
        mov rax, [rbx + A_WND]
        test rax, rax
        jz .nownd
        push rbx
        mov rbx, rax
        call wnd_destroy
        pop rbx
.nownd:
        mov dword [rbx + A_USED], 0
        mov qword [rbx + A_WND], 0
        mov qword [rbx + A_ENTRY], 0
        mov rdi, [rbx + A_IMG]
        mov rsi, [rbx + A_SIZE]
        mov qword [rbx + A_IMG], 0
        test rdi, rdi
        jz .nofree
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
.nofree:
        pop rbx
        ret

; =============================================================================
; menu_item_activate: edi=índice
; =============================================================================
menu_item_activate:
        push rbx
        mov ebx, edi
        mov dword [menu_open], 0
        call menu_redraw
        cmp ebx, 0
        jl .done
        call menu_count
        cmp ebx, eax
        jge .done
        cmp ebx, [menu_app_count]
        jae .sys_item
        lea rdi, [menu_names]
        mov eax, ebx
        imul eax, 24
        add rdi, rax
        call app_launch
        jmp .done
.sys_item:
        cmp ebx, [menu_app_count]
        jne .maybe_shutdown
        call sys_reboot
.maybe_shutdown:
        call sys_shutdown
.done:
        pop rbx
        ret

sys_reboot:
        cli
        mov al, 0xFE
        out 0x64, al
.hang:
        hlt
        jmp .hang

sys_shutdown:
        mov dx, 0x604
        mov ax, 0x2000
        out dx, ax
        mov dx, 0xB004
        mov ax, 0x2000
        out dx, ax
        mov dx, 0x4004
        mov ax, 0x3400
        out dx, ax
        mov r8, s_shutdown_title
        mov rdx, s_shutdown_msg
        call modal_open_msg
        ret

; =============================================================================
section .kdata
; =============================================================================
s_banner:  db "EnzoOS 1.0 — kernel em Assembly x86-64", 0
s_b_cpu:   db "[boot] cpu ok", 0
s_b_cpu2:  db "[boot] cpu ok 2", 0
s_b_cpu3:  db "[boot] cpu ok 3", 0
s_b_mm:    db "[boot] mm ok", 0
s_b_ps2:   db "[boot] ps2 ok", 0
s_b_gfx:   db "[boot] gfx ok", 0
s_b_cefs:  db "[boot] cefs ok", 0
s_b_wm:    db "[boot] wm ok", 0
s_b_hpet:  db "[boot] hpet ok", 0
s_b_ahci:  db "[boot] ahci ok", 0
s_b_enzfs: db "[boot] enzfs ok", 0
s_b_swap:  db "[boot] swap ok", 0
s_b_e1000: db "[boot] e1000 ok", 0
s_b_net:   db "[boot] net ok", 0
s_b_hda:   db "[boot] hda ok", 0
s_b_rtc:   db "[boot] rtc ok — laço principal", 0
s_app1:    db "TERMINAL.ENZ", 0
s_app2:    db "INFO.ENZ", 0
s_app3:    db "PLASMA.ENZ", 0
s_app4:    db "PAINT.ENZ", 0
s_app5:    db "CALC.ENZ", 0
s_app6:    db "NOTAS.ENZ", 0

mouse_last_btns: dd 0
last_dispatch_ms: dd 0
last_sec: dd -1
m_press: dd 0
m_release: dd 0

s_shutdown_title: db "Desligar", 0
s_shutdown_msg: db "Nao foi possivel desligar por software. Desligue o computador no botao.", 0
