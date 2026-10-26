; =============================================================================
;  EnzoOS — kernel/cefs.inc: CEFS (sistema de arquivos da imagem de boot),
;  carregador do formato .ce (Certamente Executável) e API de aplicativos.
;
;  Cabeçalho .ce (64 bytes):
;    +0 "CE01"  +4 u16 hdrsize  +6 u16 flags  +8 u32 entry  +12 u32 image_size
;    +16 u32 api_ver  +20 u16 win_w  +22 u16 win_h  +24 u32 reservado
;    +28 nome[36]
; =============================================================================
%ifndef CEFS_INC
%define CEFS_INC

section .ktext

; -----------------------------------------------------------------------------
k_cefs_init:
        push rbx
        mov rax, [boot_params + BP_IMG]
        mov ecx, [boot_params + BP_CEFS]
        add rax, rcx
        mov [cefs_base], rax
        cmp dword [rax], 0x53464543    ; "CEFS"
        jne .bad
        movzx ecx, word [rax+6]
        cmp ecx, MAX_FILES
        jbe .cnt_ok
        mov ecx, MAX_FILES
.cnt_ok:
        mov [ce_count], ecx
        mov edx, [rax+8]               ; data_start
        mov r8, rax
        add r8, rdx
        mov [cefs_data], r8
        xor r9d, r9d                   ; índice
        lea r10, [ce_files]
.conv:
        cmp r9d, ecx
        jae .done
        mov r11, rax
        add r11, CEFS_HDR
        mov edx, r9d
        imul edx, CEFS_ENT
        add r11, rdx                   ; r11 = entrada CEFS
        ; nome (20 bytes, maiúsculas)
        mov rsi, r11
        mov edx, 19
.ncpy:
        mov al, [rsi]
        test al, al
        jz .nz
        cmp al, 'a'
        jb .n1
        cmp al, 'z'
        ja .n1
        sub al, 32
.n1:
        mov [r10], al
        inc rsi
        inc r10
        dec edx
        jnz .ncpy
.nz:
        mov byte [r10], 0
        add r10, 4                     ; pula o resto do campo nome
        ; ptr = cefs_data + offset
        mov edx, [r11 + CEN_OFF]
        mov rbx, [cefs_data]
        add rbx, rdx
        mov [r10], rbx
        add r10, 8
        ; size e flags
        mov edx, [r11 + CEN_SIZE]
        mov [r10], edx
        mov edx, [r11 + CEN_FLAGS]
        mov [r10 + 4], edx
        add r10, 8
        inc r9d
        jmp .conv
.done:
        pop rbx
        ret
.bad:
        mov dword [ce_count], 0
        mov rdi, s_cefs_bad
        call k_log
        pop rbx
        ret

; -----------------------------------------------------------------------------
; cefs_find: rdi=nome -> rax=índice ou -1 (caixa ignorada)
; -----------------------------------------------------------------------------
cefs_find:
        push rbx
        xor ecx, ecx
.loop:
        cmp ecx, [ce_count]
        jae .no
        imul rax, rcx, 40
        lea rbx, [ce_files]
        add rbx, rax
        mov rsi, rbx
        call k_strcasecmp
        test rax, rax
        jz .found
        inc ecx
        jmp .loop
.found:
        mov rax, rcx
        pop rbx
        ret
.no:
        mov rax, -1
        pop rbx
        ret

; cefs_get: rax=índice -> rax=ptr, rdx=size
cefs_get:
        imul rax, 40
        lea rcx, [ce_files]
        add rcx, rax
        mov rax, [rcx + 24]
        mov edx, [rcx + 32]
        ret

; -----------------------------------------------------------------------------
; app_launch: rdi=nome do arquivo .ce -> rax=slot ou código negativo
; -----------------------------------------------------------------------------
app_launch:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r15, rdi                    ; nome
        call cefs_find
        cmp rax, -1
        je .notfound
        mov rbx, rax
        mov rax, rbx
        call cefs_get                   ; rax=ptr, rdx=size
        mov r14, rax
        mov r13, rdx
        cmp dword [r14], CE_MAGIC
        jne .badce
        cmp dword [r14 + CE_ISIZE], 0
        je .badce
        cmp dword [r14 + CE_ISIZE], 0x400000
        ja .badce
        ; carrega no heap
        mov rdi, r13
        add rdi, 4095
        and rdi, -4096
        call k_alloc
        test rax, rax
        jz .nomem
        mov [img_ptr], rax
        mov rdi, rax
        mov rsi, r14
        mov rdx, r13
        call k_memcpy
        ; slot livre
        xor r12d, r12d
.slot:
        cmp r12d, MAX_APPS
        jae .noslot
        lea rax, [app_slots]
        imul rax, r12, A_SIZEOF
        cmp dword [rax + A_USED], 0
        je .slot_found
        inc r12
        jmp .slot
.slot_found:
        imul rbx, r12, A_SIZEOF
        lea rax, [app_slots]
        add rbx, rax                   ; rbx = slot
        mov dword [rbx + A_USED], 1
        mov rax, [img_ptr]
        mov [rbx + A_IMG], rax
        mov [rbx + A_SIZE], r13
        mov edx, [rax + CE_ENTRY]
        add rax, rdx
        mov [rbx + A_ENTRY], rax
        ; nome do app (header +28)
        lea rdi, [rbx + A_NAME]
        mov rsi, [img_ptr]
        add rsi, 28
        mov r8d, 19
.nc:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .ncd
        inc rsi
        inc rdi
        dec r8d
        jnz .nc
.ncd:
        mov byte [rbx + A_NAME + 19], 0
        ; dimensões da janela
        mov rax, [img_ptr]
        movzx edx, word [rax + 20]
        cmp edx, 160
        jae .w_ok
        mov edx, 480
.w_ok:
        mov [tmp_w], edx
        mov rax, [img_ptr]
        movzx edx, word [rax + 22]
        cmp edx, 120
        jae .h_ok
        mov edx, 320
.h_ok:
        mov [tmp_h], edx
        ; posição em cascata
        mov eax, [wnd_count]
        and eax, 7
        imul eax, 30
        add eax, 120
        mov edi, eax
        mov eax, [wnd_count]
        and eax, 7
        imul eax, 26
        add eax, 48
        mov esi, eax
        mov edx, [tmp_w]
        mov ecx, [tmp_h]
        mov r8, r15                     ; título = nome do arquivo
        mov r9d, r12d
        call wnd_create
        test rax, rax
        jz .nowin
        mov [rbx + A_WND], rax
        mov [tmp_wnd], rax
        ; INIT com as dimensões do conteúdo
        mov rdx, rax
        mov edx, [rdx + W_W]
        sub edx, 2
        mov rcx, [tmp_wnd]
        mov ecx, [rcx + W_H]
        sub ecx, TITLE_H
        sub ecx, 1
        mov edi, r12d
        mov esi, EV_INIT
        xor r8d, r8d
        xor r9d, r9d
        call app_dispatch
        mov edi, r12d
        mov esi, EV_PAINT
        xor edx, edx
        xor ecx, ecx
        xor r8d, r8d
        xor r9d, r9d
        call app_dispatch
        call wm_menu_refresh
        mov rax, r12
        jmp .done
.notfound:
        mov rax, -1
        jmp .done
.badce:
        mov rax, -2
        jmp .done
.nomem:
        mov rax, -3
        jmp .done
.noslot:
        mov rdi, [img_ptr]
        mov rsi, r13
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
        mov rax, -4
        jmp .done
.nowin:
        mov dword [rbx + A_USED], 0
        mov rdi, [img_ptr]
        mov rsi, r13
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
        mov rax, -5
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; app_dispatch: edi=slot, esi=tipo, rdx..r9 = a,b,c,d
; -----------------------------------------------------------------------------
app_dispatch:
        push rbx
        sub rsp, 48
        mov [rsp], rsi
        mov [rsp+16], rdx
        mov [rsp+24], rcx
        mov [rsp+32], r8
        mov [rsp+40], r9
        mov rax, [cur_slot]
        push rax
        mov [cur_slot], edi
        imul rbx, rdi, A_SIZEOF
        lea rax, [app_slots]
        add rbx, rax
        mov rbx, [rbx + A_ENTRY]
        test rbx, rbx
        jz .skip
        lea rdi, [api_table]
        mov rsi, rsp
        call rbx
.skip:
        pop rax
        mov [cur_slot], rax
        add rsp, 48
        pop rbx
        ret

; -----------------------------------------------------------------------------
; wm_menu_refresh: lista os .ce do CEFS no menu Iniciar
; -----------------------------------------------------------------------------
wm_menu_refresh:
        xor r9d, r9d                   ; índice fonte
        xor edx, edx                   ; destino
.loop:
        cmp r9d, [ce_count]
        jae .done
        imul rax, r9, 40
        lea r8, [ce_files]
        add r8, rax
        lea rdi, [r8]
        call k_strlen
        cmp rax, 4
        jb .next
        lea rdi, [r8]
        add rdi, rax
        sub rdi, 3
        lea rsi, [s_ext_ce]
        call k_strcasecmp
        test rax, rax
        jnz .next
        cmp edx, 16
        jae .done
        lea rdi, [menu_names]
        imul rax, rdx, 24
        add rdi, rax
        mov rsi, r8
        mov ecx, 23
.cp:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .cpd
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
.cpd:
        mov byte [rdi], 0
        inc edx
.next:
        inc r9d
        jmp .loop
.done:
        mov [menu_app_count], edx
        ret

; -----------------------------------------------------------------------------
; API de aplicativos
; -----------------------------------------------------------------------------
api_rect:                         ; edi=x, esi=y, edx=w, ecx=h, r8d=cor
        call api_use_win
        test rax, rax
        jz .done
        add edi, 1
        add esi, TITLE_H
        ; clipe no conteúdo da janela
        mov r9d, [api_cw]
        sub r9d, edi
        cmp edx, r9d
        jle .w_ok
        mov edx, r9d
.w_ok:
        mov r9d, [api_ch]
        sub r9d, esi
        cmp ecx, r9d
        jle .h_ok
        mov ecx, r9d
.h_ok:
        mov r14d, r8d
        call surf_fill
.done:
        ret

api_use_win:
        ; rax = janela do app atual; prepara gsurf e api_cw/api_ch
        push rbx
        mov eax, [cur_slot]
        cmp eax, 0
        jl .none
        cmp eax, MAX_APPS
        jge .none
        imul rbx, rax, A_SIZEOF
        lea rax, [app_slots]
        add rbx, rax
        mov rax, [rbx + A_WND]
        test rax, rax
        jz .none
        mov rbx, rax
        mov rdi, [rbx + W_BUF]
        mov esi, [rbx + W_W]
        mov edx, [rbx + W_H]
        mov ecx, [rbx + W_W]
        shl ecx, 2
        call surf_set
        ; limites do conteúdo (em coords da janela)
        mov eax, [rbx + W_W]
        dec eax
        mov [api_cw], eax
        mov eax, [rbx + W_H]
        dec eax
        mov [api_ch], eax
        mov rax, rbx
        pop rbx
        ret
.none:
        xor rax, rax
        pop rbx
        ret

api_text:                         ; edi=x, esi=y, rdx=str, ecx=len, r8d=cor
        call api_use_win
        test rax, rax
        jz .done
        add edi, 1
        add esi, TITLE_H
        mov r13d, r8d
        call surf_text
.done:
        ret

api_blit:                         ; edi=x, esi=y, edx=w, ecx=h, r8=src, r9d=stride
        call api_use_win
        test rax, rax
        jz .done
        add edi, 1
        add esi, TITLE_H
        mov r12, r8
        mov r14d, r9d
        call surf_blit
.done:
        ret

api_title:                        ; rdi=str
        call api_use_win
        test rax, rax
        jz .done
        mov rbx, rax
        xor ecx, ecx
.cp:
        cmp ecx, 31
        jae .cd
        mov al, [rdi + rcx]
        mov [rbx + W_TITLE + rcx], al
        test al, al
        jz .cd
        inc ecx
        jmp .cp
.cd:
        mov byte [rbx + W_TITLE + 31], 0
        call wnd_render_chrome
        call wnd_damage
.done:
        ret

api_uptime:
        mov eax, [uptime_ms]
        ret

api_file_open:                    ; rdi=nome -> rax=ptr, rdx=size
        call cefs_find
        cmp rax, -1
        je .no
        call cefs_get
        ret
.no:
        xor rax, rax
        xor edx, edx
        ret

api_files_count:
        mov eax, [ce_count]
        ret

api_file_name:                    ; edi=índice, rsi=buf -> rax=len
        cmp edi, [ce_count]
        jae .no
        imul rax, rdi, 40
        lea rdx, [ce_files]
        add rdx, rax
        xor ecx, ecx
.cp:
        mov al, [rdx + rcx]
        mov [rsi + rcx], al
        test al, al
        jz .cd
        inc ecx
        cmp ecx, 23
        jb .cp
.cd:
        mov byte [rsi + rcx], 0
        mov rax, rcx
        ret
.no:
        xor rax, rax
        ret

api_exec:                         ; rdi=nome -> rax=status
        jmp k_exec

api_conout_read:                  ; rdi=buf, rsi=max -> rax=len
        jmp conout_read

api_rand:
        mov eax, [rand_seed]
        imul eax, eax, 1664525
        add eax, 1013904223
        mov [rand_seed], eax
        ret

api_invalidate:
        call api_use_win
        test rax, rax
        jz .done
        mov rbx, rax
        call wnd_damage
.done:
        ret

api_alloc:                        ; rdi=bytes -> rax=ptr
        jmp k_alloc

api_free:                         ; rdi=ptr, rsi=bytes
        jmp k_free_bytes

api_sysinfo:                      ; rdi=buf (preenche 128 bytes)
        push rbx
        push r12
        mov rbx, rdi
        ; marca da CPU (49 bytes em +0)
        lea rsi, [cpu_brand]
        lea rdi, [rbx + 0]
        mov ecx, 48
.cp1:
        mov al, [rsi]
        mov [rdi], al
        inc rsi
        inc rdi
        dec ecx
        jnz .cp1
        mov byte [rbx + 48], 0
        ; núcleos, ram
        mov eax, [cpu_cores]
        mov [rbx + 52], eax
        mov rax, [ram_total]
        shr rax, 20
        mov [rbx + 56], eax
        ; vídeo
        mov eax, [screen_w]
        mov [rbx + 60], eax
        mov eax, [screen_h]
        mov [rbx + 64], eax
        mov eax, [boot_params + BP_BPP]
        mov [rbx + 68], eax
        mov eax, [boot_params + BP_LFB]
        mov [rbx + 72], eax
        movzx eax, word [boot_params + 0x34]
        mov [rbx + 76], eax
        ; páginas 1GB? WC?
        mov eax, [feat_edx81]
        shr eax, 26
        and eax, 1
        mov [rbx + 80], eax
        mov eax, [lfb_wc_on]
        mov [rbx + 84], eax
        ; recursos
        mov eax, [feat_edx1]
        mov [rbx + 88], eax
        mov eax, [feat_ecx1]
        mov [rbx + 92], eax
        mov eax, [feat_edx81]
        mov [rbx + 96], eax
        ; uptime
        mov eax, [uptime_ms]
        mov [rbx + 100], eax
        ; heap
        call k_free_pages_count
        mov [rbx + 104], eax
        mov rax, [heap_pages]
        mov [rbx + 108], eax
        mov eax, [wnd_count]
        mov [rbx + 112], eax
        mov eax, [ce_count]
        mov [rbx + 116], eax
        mov rax, [heap_top]
        sub rax, HEAP_START
        shr rax, 20
        mov [rbx + 120], eax
        pop r12
        pop rbx
        ret

api_time:                         ; rdi=buf (20 bytes)
        lea rsi, [clock_str]
        mov ecx, 19
.cp:
        mov al, [rsi]
        mov [rdi], al
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
        mov byte [rdi], 0
        ret

api_exit:
        push rbx
        mov eax, [cur_slot]
        mov [tmp_slot], eax
        call api_use_win
        test rax, rax
        jz .noclose
        mov rbx, rax
        mov edi, [tmp_slot]
        mov esi, EV_QUIT
        xor edx, edx
        xor ecx, ecx
        xor r8d, r8d
        xor r9d, r9d
        call app_dispatch
        call wnd_destroy
.noclose:
        lea rax, [app_slots]
        imul rax, [tmp_slot], A_SIZEOF
        mov dword [rax + A_USED], 0
        mov qword [rax + A_WND], 0
        mov qword [rax + A_ENTRY], 0
        mov rdi, [rax + A_IMG]
        mov rsi, [rax + A_SIZE]
        mov qword [rax + A_IMG], 0
        test rdi, rdi
        jz .nofree
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
.nofree:
        pop rbx
        ret

api_beep:                         ; edi=freq, esi=ms
        jmp k_beep

api_self:
        mov eax, [cur_slot]
        ret

section .kdata
cefs_base: dq 0
cefs_data: dq 0
ce_count:  dd 0
ce_files:  times MAX_FILES * 40 db 0
cur_slot:  dd -1
img_ptr:   dq 0
tmp_slot:  dd 0
api_cw:    dd 0
api_ch:    dd 0
rand_seed: dd 0x5A17C0DE
lfb_wc_on: dd 0

app_slots: times MAX_APPS * A_SIZEOF db 0

s_cefs_bad: db "CEFS: assinatura invalida", 0
s_ext_ce:   db ".CE", 0
tmp_w:    dd 480
tmp_h:    dd 320
tmp_wnd:  dq 0

align 8
api_table:
        dq 0x0000000150414543          ; "CEAP" + versão 1
        dq api_rect
        dq api_text
        dq api_blit
        dq api_title
        dq api_uptime
        dq api_file_open
        dq api_files_count
        dq api_file_name
        dq api_exec
        dq api_conout_read
        dq api_rand
        dq api_invalidate
        dq api_alloc
        dq api_free
        dq api_sysinfo
        dq api_time
        dq api_exit
        dq api_beep
        dq api_self

%endif
