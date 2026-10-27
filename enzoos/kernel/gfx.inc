; =============================================================================
;  EnzoOS — kernel/gfx.inc: framebuffer, superfícies, fonte, compositor com
;  controle de dano (damage tracking) e tela de pânico.
;
;  Convenção: a "superfície ativa" é global (gsurf_*). As funções:
;    surf_set(rdi=ptr, esi=w, edx=h, ecx=stride)
;    surf_fill(edi=x, esi=y, edx=w, ecx=h, r14d=cor)
;    surf_char(edi=x, esi=y, ecx=código, r13d=cor)
;    surf_text(edi=x, esi=y, rdx=str, ecx=len, r13d=cor)   [UTF-8→Latin-1]
;    surf_blit(edi=x, esi=y, edx=w, ecx=h, r12=src, r14d=src_stride)
; =============================================================================
%ifndef GFX_INC
%define GFX_INC

section .ktext

; -----------------------------------------------------------------------------
k_gfx_init:
        mov eax, [boot_params + BP_W]
        mov [screen_w], eax
        mov eax, [boot_params + BP_H]
        mov [screen_h], eax
        mov eax, [boot_params + BP_PITCH]
        mov [screen_pitch], eax
        mov eax, [boot_params + BP_LFB]   ; dword!
        mov [lfb], rax
        ; sombra (composição) e fundo da área de trabalho
        mov edi, [screen_w]           ; dword! (evita ler screen_h junto)
        imul edi, [screen_h]
        shl rdi, 2
        call k_alloc
        test rax, rax
        jz .fail
        mov [shadow], rax
        mov edi, [screen_w]
        imul edi, [screen_h]
        shl rdi, 2
        call k_alloc
        test rax, rax
        jz .fail
        mov [desktop_bg], rax
        call render_desktop
        call damage_all
        ret
.fail:
        mov rdi, msg_nofb
        call k_log
        ; diag: por que a alocação falhou?
        mov edi, [screen_w]
        call k_log_hex
        mov edi, [screen_h]
        call k_log_hex
        mov rdi, [heap_pages]
        call k_log_hex
        mov rdi, [bitmap_pages]
        call k_log_hex
        mov rdi, [lfb]
        call k_log_hex
.hang:
        hlt
        jmp .hang

; -----------------------------------------------------------------------------
surf_set:                          ; rdi=ptr, esi=w, edx=h, ecx=stride
        mov [gsurf_ptr], rdi
        mov [gsurf_w], esi
        mov [gsurf_h], edx
        mov [gsurf_stride], ecx
        ret

surf_use_shadow:
        mov rdi, [shadow]
        mov esi, [screen_w]
        mov edx, [screen_h]
        mov ecx, [screen_pitch]
        jmp surf_set

surf_use_desktop:
        mov rdi, [desktop_bg]
        mov esi, [screen_w]
        mov edx, [screen_h]
        mov ecx, [screen_pitch]
        jmp surf_set

; -----------------------------------------------------------------------------
surf_fill:                         ; edi=x, esi=y, edx=w, ecx=h, r14d=cor
        push rbx
        push r12
        push r13
        cmp edi, 0
        jge .x1
        add edx, edi
        xor edi, edi
.x1:
        cmp esi, 0
        jge .y1
        add ecx, esi
        xor esi, esi
.y1:
        mov eax, edi
        add eax, edx
        cmp eax, [gsurf_w]
        jbe .x2
        mov edx, [gsurf_w]
        sub edx, edi
.x2:
        mov eax, esi
        add eax, ecx
        cmp eax, [gsurf_h]
        jbe .y2
        mov ecx, [gsurf_h]
        sub ecx, esi
.y2:
        cmp edx, 0
        jle .done
        cmp ecx, 0
        jle .done
        mov r13d, edx                ; w
        mov rbx, [gsurf_ptr]
        mov eax, esi
        imul eax, [gsurf_stride]
        add rbx, rax
        mov eax, edi
        shl eax, 2
        add rbx, rax
        xor r12d, r12d
.row:
        cmp r12d, ecx
        jae .done
        push rdi
        push rsi
        push rdx
        push rcx
        mov rdi, rbx
        mov rsi, r13
        mov rdx, r14
        call k_memset32
        pop rcx
        pop rdx
        pop rsi
        pop rdi
        mov eax, [gsurf_stride]
        add rbx, rax
        inc r12d
        jmp .row
.done:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
surf_char:                         ; edi=x, esi=y, ecx=código, r13d=cor
        push rbx
        push r10
        push r11
        and rcx, 0xFF
        lea rax, [enzo_font]
        shl rcx, 3
        add rax, rcx                 ; rax = 8 linhas do glifo
        xor r10d, r10d               ; gy
.row:
        cmp r10d, 8
        jae .done
        mov ebx, esi
        add ebx, r10d
        cmp ebx, 0
        jl .next
        cmp ebx, [gsurf_h]
        jge .done
        xor r11d, r11d               ; gx
.col:
        cmp r11d, 8
        jae .next
        mov ebx, edi
        add ebx, r11d
        cmp ebx, 0
        jl .col_next
        cmp ebx, [gsurf_w]
        jge .next
        movzx edx, byte [rax]
        mov ecx, r11d
        mov r8d, 0x80
        shr r8d, cl
        test edx, r8d
        jz .col_next
        mov ebx, esi
        add ebx, r10d
        imul ebx, [gsurf_stride]
        mov ecx, edi
        add ecx, r11d
        shl ecx, 2
        add ebx, ecx
        add rbx, [gsurf_ptr]
        mov [rbx], r13d
.col_next:
        inc r11d
        jmp .col
.next:
        inc r10d
        inc rax
        jmp .row
.done:
        pop r11
        pop r10
        pop rbx
        ret

surf_text:                         ; edi=x, esi=y, rdx=str, ecx=len, r13d=cor
        push rbx
        push r12
        xor ebx, ebx                 ; bytes consumidos
.loop:
        cmp ebx, ecx
        jae .done
        push rdi
        push rsi
        push rdx
        push rcx
        push r13
        mov rdi, rdx
        add rdi, rbx
        call k_utf8_next
        mov r12, rdx                 ; bytes consumidos
        pop r13
        pop rcx
        pop rdx
        pop rsi
        pop rdi
        test rax, rax
        jz .done
        push rbx
        push rdx
        push rcx
        push r13
        mov ecx, eax                 ; código Latin-1
        call surf_char
        pop r13
        pop rcx
        pop rdx
        pop rbx
        add ebx, r12d
        add edi, 8
        jmp .loop
.done:
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
surf_blit:                         ; edi=x, esi=y, edx=w, ecx=h, r12=src, r14d=src_stride
        push rbx
        push r13
        push r15
        ; clip no destino
        cmp edi, 0
        jge .x1
        add edx, edi
        xor edi, edi
.x1:
        cmp esi, 0
        jge .y1
        add ecx, esi
        xor esi, esi
.y1:
        mov eax, edi
        add eax, edx
        cmp eax, [gsurf_w]
        jbe .x2
        mov edx, [gsurf_w]
        sub edx, edi
.x2:
        mov eax, esi
        add eax, ecx
        cmp eax, [gsurf_h]
        jbe .y2
        mov ecx, [gsurf_h]
        sub ecx, esi
.y2:
        cmp edx, 0
        jle .done
        cmp ecx, 0
        jle .done
        mov r15d, edx                ; w
        mov r13d, [gsurf_stride]
        xor ebx, ebx                 ; linha
.row:
        cmp ebx, ecx
        jae .done
        ; dst = gsurf_ptr + (esi+ebx)*stride + edi*4
        mov eax, esi
        add eax, ebx
        imul eax, r13d
        mov r9, [gsurf_ptr]
        add r9, rax
        mov eax, edi
        shl eax, 2
        add r9, rax
        ; src = r12 + ebx*src_stride + edi*4
        mov eax, ebx
        imul eax, r14d
        mov r10, r12
        add r10, rax
        mov eax, edi
        shl eax, 2
        add r10, rax
        ; copia w pixels
        push rdi
        push rsi
        push rdx
        push rcx
        push r12
        push r14
        mov rdi, r9
        mov rsi, r10
        mov rdx, r15
        shl rdx, 2
        call k_memcpy
        pop r14
        pop r12
        pop rcx
        pop rdx
        pop rsi
        pop rdi
        inc ebx
        jmp .row
.done:
        pop r15
        pop r13
        pop rbx
        ret

; -----------------------------------------------------------------------------
; render_desktop: gradiente + logotipo + marca
; -----------------------------------------------------------------------------
render_desktop:
        mov r8, [desktop_bg]
        xor r12d, r12d               ; y
.row:
        cmp r12d, [screen_h]
        jae .rows_done
        mov eax, r12d
        shl eax, 8
        xor edx, edx
        div dword [screen_h]         ; eax = t (0..255)
        mov ecx, eax                 ; t
        imul eax, ecx, (0x0E - 0x0A)
        add eax, 127
        sar eax, 8
        add eax, 0x0A
        mov r9d, eax                 ; r
        imul eax, ecx, (0x2A - 0x16)
        add eax, 127
        sar eax, 8
        add eax, 0x16
        shl eax, 8
        or r9d, eax                  ; g
        imul eax, ecx, (0x4C - 0x26)
        add eax, 127
        sar eax, 8
        add eax, 0x26
        or r9d, eax                  ; b
        push r12
        push rcx
        mov rdi, r8
        mov esi, [screen_w]           ; dword! (uma linha = screen_w dwords)
        mov edx, r9d
        call k_memset32
        pop rcx
        pop r12
        mov eax, [screen_pitch]
        add r8, rax
        inc r12d
        jmp .row
.rows_done:
        ; logotipo 64x64 escalado 3x no canto inferior direito
        mov eax, [screen_w]
        sub eax, 240
        mov [logo_x], eax
        mov eax, [screen_h]
        sub eax, TASKBAR_H + 60
        mov [logo_y], eax
        mov edi, [logo_x]
        mov esi, [logo_y]
        mov edx, 3
        call draw_logo_scaled
        ; marca
        call surf_use_desktop
        mov edi, 24
        mov esi, 24
        lea rdx, [brand_str]
        call k_strlen
        mov ecx, eax
        lea rdx, [brand_str]
        mov r13d, 0x35507E
        call surf_text
        mov edi, 24
        mov esi, 36
        lea rdx, [brand_str2]
        call k_strlen
        mov ecx, eax
        lea rdx, [brand_str2]
        mov r13d, 0x2C4670
        call surf_text
        ; ---- aurora (círculos suaves com alpha) ----
        mov edi, -180
        mov esi, 520
        mov edx, 620
        mov ecx, 0x14325A08
        call g2_circle
        mov edi, -60
        mov esi, 640
        mov edx, 460
        mov ecx, 0x1E6B4FA0
        call g2_circle
        mov edi, 1024
        mov esi, -220
        mov edx, 700
        mov ecx, 0x122D6BA8
        call g2_circle
        mov edi, 1180
        mov esi, -120
        mov edx, 520
        mov ecx, 0x1660C8A8
        call g2_circle
        ret

; draw_logo_scaled: rdi=x, rsi=y, edx=escala — desenha no desktop_bg
draw_logo_scaled:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        mov r13d, esi
        mov r14d, edx
        xor ecx, ecx                 ; ly
.ly:
        cmp ecx, 64
        jae .done
        xor esi, esi                 ; lx
.lx:
        cmp esi, 64
        jae .next
        lea rax, [logo_img]
        mov r9, rcx
        shl r9, 8                    ; ly*64*4
        mov r10, rsi
        shl r10, 2                   ; lx*4
        add r9, r10
        mov eax, [rax + r9]
        test eax, eax
        jz .skip
        mov [tmp_color], eax
        ; bloco escala×escala
        mov eax, r12d
        mov ebx, esi
        imul ebx, r14d
        add eax, ebx
        mov [tmp_x], eax
        mov eax, r13d
        mov ebx, ecx
        imul ebx, r14d
        add eax, ebx
        mov [tmp_y], eax
        xor r8d, r8d
.bly:
        cmp r8d, r14d
        jae .skip
        xor r9d, r9d
.blx:
        cmp r9d, r14d
        jae .bly_next
        mov edi, [tmp_x]
        add edi, r9d
        mov esi, [tmp_y]
        add esi, r8d
        mov eax, [tmp_color]
        call px_desktop
        inc r9d
        jmp .blx
.bly_next:
        inc r8d
        jmp .bly
.skip:
        inc esi
        jmp .lx
.next:
        inc ecx
        jmp .ly
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; px_desktop: edi=x, esi=y, eax=cor
px_desktop:
        cmp edi, 0
        jl .no
        cmp esi, 0
        jl .no
        cmp edi, [screen_w]
        jge .no
        cmp esi, [screen_h]
        jge .no
        mov ecx, esi
        imul ecx, [screen_pitch]
        add ecx, edi
        shl ecx, 2
        add rcx, [desktop_bg]
        mov [rcx], eax
.no:
        ret

; px_screen: edi=x, esi=y, eax=cor (na sombra)
px_screen:
        cmp edi, 0
        jl .no
        cmp esi, 0
        jl .no
        cmp edi, [screen_w]
        jge .no
        cmp esi, [screen_h]
        jge .no
        mov ecx, esi
        imul ecx, [screen_pitch]
        add ecx, edi
        shl ecx, 2
        add rcx, [shadow]
        mov [rcx], eax
.no:
        ret

; -----------------------------------------------------------------------------
; dano
; -----------------------------------------------------------------------------
damage_all:
        mov dword [dam_x], 0
        mov dword [dam_y], 0
        mov eax, [screen_w]
        mov [dam_w], eax
        mov eax, [screen_h]
        mov [dam_h], eax
        ret

damage_add:                       ; edi=x, esi=y, edx=w, ecx=h
        test edx, edx
        jle .skip
        test ecx, ecx
        jle .skip
        cmp edi, 0
        jge .x_ok
        add edx, edi
        xor edi, edi
.x_ok:
        cmp esi, 0
        jge .y_ok
        add ecx, esi
        xor esi, esi
.y_ok:
        mov eax, edi
        add eax, edx
        cmp eax, [screen_w]
        jbe .w_ok
        mov eax, [screen_w]
        sub eax, edi
        mov edx, eax
.w_ok:
        mov eax, esi
        add eax, ecx
        cmp eax, [screen_h]
        jbe .h_ok
        mov eax, [screen_h]
        sub eax, esi
        mov ecx, eax
.h_ok:
        cmp edx, 0
        jle .skip
        cmp ecx, 0
        jle .skip
        cmp dword [dam_w], 0
        jne .merge
        mov [dam_x], edi
        mov [dam_y], esi
        mov [dam_w], edx
        mov [dam_h], ecx
        ret
.merge:
        mov eax, [dam_x]
        add eax, [dam_w]
        mov r8d, edi
        add r8d, edx
        cmp eax, r8d
        jae .keep_x1
        mov r8d, eax
.keep_x1:
        mov eax, [dam_y]
        add eax, [dam_h]
        mov r9d, esi
        add r9d, ecx
        cmp eax, r9d
        jae .keep_y1
        mov r9d, eax
.keep_y1:
        cmp edi, [dam_x]
        jbe .x_min
        mov edi, [dam_x]
.x_min:
        cmp esi, [dam_y]
        jbe .y_min
        mov esi, [dam_y]
.y_min:
        mov [dam_x], edi
        mov [dam_y], esi
        sub r8d, edi
        mov [dam_w], r8d
        sub r9d, esi
        mov [dam_h], r9d
.skip:
        ret

; -----------------------------------------------------------------------------
; composição
; -----------------------------------------------------------------------------
compose_if_dirty:
        cmp dword [dam_w], 0
        je .done
        cmp dword [dam_h], 0
        je .done
        push rbx
        push r12
        push r13
        push r14
        push r15
        ; 1. fundo
        mov edi, [dam_x]
        mov esi, [dam_y]
        mov edx, [dam_w]
        mov ecx, [dam_h]
        call copy_region_desktop
        ; 1.5 ícones da área de trabalho
        call draw_icons
        ; 2. janelas (de baixo para cima)
        mov rbx, [wnd_bottom]
.win_loop:
        test rbx, rbx
        jz .win_done
        test dword [rbx + W_FLAGS], 2
        jnz .win_next
        ; janela intersecta o dano?
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        call rect_intersects_dam
        test eax, eax
        jz .win_next
        ; sombra suave sob a janela
        call surf_use_shadow
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        call g2_shadow
        ; blit com cantos arredondados
        call surf_use_shadow
        mov r12, [rbx + W_BUF]
        mov r14d, [rbx + W_W]
        shl r14d, 2
        mov edi, [rbx + W_X]
        mov esi, [rbx + W_Y]
        mov edx, [rbx + W_W]
        mov ecx, [rbx + W_H]
        mov r8, r12
        mov r9d, r14d
        call g2_win_blit
.win_next:
        mov rbx, [rbx + W_NEXT]
        jmp .win_loop
.win_done:
        ; 3. modal
        cmp dword [modal_active], 0
        je .no_modal
        call draw_modal
.no_modal:
        ; 4. barra de tarefas
        call draw_taskbar
        ; 4.5 menu Iniciar
        call draw_menu
        ; 5. cursor
        mov edi, [mouse_x]
        mov esi, [mouse_y]
        mov edx, cursor_w
        mov ecx, cursor_h
        call draw_cursor
        ; 6. sombra -> LFB
        call flush_damage
        mov dword [dam_w], 0
        mov dword [dam_h], 0
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
.done:
        ret

; rect_intersects_dam: edi=x, esi=y, edx=w, ecx=h -> eax=1 se intersecta
rect_intersects_dam:
        xor eax, eax
        cmp edx, 0
        jle .no
        cmp ecx, 0
        jle .no
        mov r8d, edi
        add r8d, edx                 ; x2
        mov r9d, esi
        add r9d, ecx                 ; y2
        mov r10d, [dam_x]
        add r10d, [dam_w]            ; dx2
        mov r11d, [dam_y]
        add r11d, [dam_h]            ; dy2
        cmp edi, r10d
        jge .no                      ; x >= dx2
        cmp r8d, [dam_x]
        jle .no                      ; x2 <= dx
        cmp esi, r11d
        jge .no
        cmp r9d, [dam_y]
        jle .no
        mov eax, 1
.no:
        ret

; copy_region_desktop: edi=x, esi=y, edx=w, ecx=h
copy_region_desktop:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r8d, edx
        mov r9d, ecx
        mov eax, edi
        add eax, r8d
        cmp eax, [screen_w]
        jbe .ok1
        mov r8d, [screen_w]
        sub r8d, edi
.ok1:
        mov eax, esi
        add eax, r9d
        cmp eax, [screen_h]
        jbe .ok2
        mov r9d, [screen_h]
        sub r9d, esi
.ok2:
        cmp r8d, 0
        jle .done
        cmp r9d, 0
        jle .done
        xor r10d, r10d
.row:
        cmp r10d, r9d
        jae .done
        mov eax, esi
        add eax, r10d
        imul eax, [screen_pitch]
        mov ecx, edi
        shl ecx, 2
        add eax, ecx
        mov r11, [desktop_bg]
        add r11, rax
        mov rbx, [shadow]
        add rbx, rax
        mov rdi, rbx
        mov rsi, r11
        mov rdx, r8
        shl rdx, 2
        call k_memcpy
        inc r10d
        jmp .row
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; flush_damage: sombra -> LFB na região do dano
flush_damage:
        push rbx
        push r12
        xor r10d, r10d
.row:
        cmp r10d, [dam_h]
        jae .done
        mov eax, [dam_y]
        add eax, r10d
        imul eax, [screen_pitch]
        mov ecx, [dam_x]
        shl ecx, 2
        add eax, ecx
        mov rsi, [shadow]
        add rsi, rax
        mov rdi, [lfb]
        add rdi, rax
        mov rdx, [dam_w]
        shl rdx, 2
        call k_memcpy
        inc r10d
        jmp .row
.done:
        pop r12
        pop rbx
        ret

draw_cursor:                       ; (edi, esi) = posição
        xor r10d, r10d
.row:
        cmp r10d, cursor_h
        jae .done
        xor r11d, r11d
.col:
        cmp r11d, cursor_w
        jae .next
        lea rax, [cursor_img]
        mov r9d, r10d
        imul r9d, cursor_w
        add r9d, r11d
        shl r9d, 2
        mov eax, [rax + r9]
        test eax, eax
        jz .skip
        mov [tmp_color], eax
        push rdi
        push rsi
        add edi, r11d
        add esi, r10d
        mov eax, [tmp_color]
        call px_screen
        pop rsi
        pop rdi
.skip:
        inc r11d
        jmp .col
.next:
        inc r10d
        jmp .row
.done:
        ret

; -----------------------------------------------------------------------------
; k_panic: edi=exceção, rsi=rip
; -----------------------------------------------------------------------------
k_panic:
        push rbx
        mov ebx, edi
        mov [panic_rip_val], rsi
        lea rdi, [rel panic_serial]
        call k_log
        ; diagnóstico pela serial: código da exceção e RIP
        mov edi, ebx
        call k_log_hex
        mov rdi, [panic_rip_val]
        call k_log_hex
        mov rdi, cr2
        call k_log_hex
        ; dump: 16 bytes da memória no RIP (instruções reais na RAM)
        mov rsi, [panic_rip_val]
        mov rdi, [rsi - 8]
        call k_log_hex
        mov rdi, [rsi]
        call k_log_hex
        cmp qword [shadow], 0
        je .hang
        call surf_use_shadow
        mov edi, 0
        mov esi, 0
        mov edx, [screen_w]
        mov ecx, [screen_h]
        mov r14d, 0x28101E
        call surf_fill
        call surf_use_shadow
        mov edi, 32
        mov esi, 40
        lea rdx, [rel panic_msg]
        mov ecx, panic_msg_len
        mov r13d, COL_RED
        call surf_text
        ; código da exceção
        call surf_use_shadow
        lea rsi, [numbuf]
        mov edi, ebx
        mov edx, 16
        call k_utoa
        call surf_use_shadow
        mov edi, 32
        mov esi, 60
        lea rdx, [numbuf]
        mov ecx, eax
        mov r13d, COL_WHITE
        call surf_text
        call surf_use_shadow
        mov edi, 32
        mov esi, 74
        lea rdx, [rel panic_rip]
        mov ecx, panic_rip_len
        mov r13d, COL_GRAY
        call surf_text
        ; rip
        call surf_use_shadow
        mov rdi, [panic_rip_val]
        mov edx, 16
        lea rsi, [numbuf]
        call k_utoa
        call surf_use_shadow
        mov edi, 32
        mov esi, 88
        lea rdx, [numbuf]
        mov ecx, eax
        mov r13d, COL_WHITE
        call surf_text
        ; flush tela inteira
        call damage_all
        xor r10d, r10d
.fl:
        cmp r10d, [screen_h]
        jae .hang
        mov eax, r10d
        imul eax, [screen_pitch]
        mov rsi, [shadow]
        add rsi, rax
        mov rdi, [lfb]
        add rdi, rax
        mov edx, [screen_w]           ; dword!
        shl rdx, 2
        call k_memcpy
        inc r10d
        jmp .fl
.hang:
        pop rbx
.halt:
        hlt
        jmp .halt

section .kdata
screen_w:     dd 1024
screen_h:     dd 768
screen_pitch: dd 4096
lfb:          dq 0
shadow:       dq 0
desktop_bg:   dq 0

gsurf_ptr:    dq 0
gsurf_w:      dd 0
gsurf_h:      dd 0
gsurf_stride: dd 0

dam_x: dd 0
dam_y: dd 0
dam_w: dd 0
dam_h: dd 0

logo_x:    dd 0
logo_y:    dd 0
tmp_x:     dd 0
tmp_y:     dd 0
tmp_color: dd 0
numbuf:    times 40 db 0
panic_rip_val: dq 0

msg_nofb:   db "ERRO: sem memoria para o video", 0
brand_str:  db "EnzoOS 1.0", 0
brand_str2: db "Certamente Executavel — kernel em Assembly", 0
panic_msg:  db "*** PANICO DO NUCLEO ***", 0
panic_msg_len equ $ - panic_msg - 1
panic_rip:  db "RIP:", 0
panic_rip_len equ $ - panic_rip - 1
panic_serial: db "PANICO DO NUCLEO", 0

%include "../obj/font.inc"
%include "../obj/cursor.inc"
%include "../obj/assets.inc"

%endif
