; =============================================================================
;  EnzoOS — kernel/ps2.inc: controlador i8042 — teclado (IRQ1) e mouse (IRQ12)
;
;  Teclado: aceita tanto scancode set 1 (com tradução do i8042, o usual após
;  o BIOS) quanto set 2 puro. Mouse: protocolo PS/2 padrão de 3 bytes.
; =============================================================================
%ifndef PS2_INC
%define PS2_INC

section .ktext

; -----------------------------------------------------------------------------
; espera o buffer de entrada do controlador esvaziar (com timeout por tiques)
; -----------------------------------------------------------------------------
ps2_wait_in:
        mov eax, [uptime_ms]
        add eax, 100
.l:
        mov dx, 0x64
        in al, dx
        test al, 2
        jz .ok
        cmp eax, [uptime_ms]
        ja .l
        stc
        ret
.ok:
        clc
        ret

; espera um byte no buffer de saída (timeout por tiques)
; retorna al = byte, CF set em timeout
ps2_wait_out:
        mov r8d, [uptime_ms]
        add r8d, 150
.l:
        mov dx, 0x64
        in al, dx
        test al, 1
        jnz .ok
        cmp [uptime_ms], r8d
        jb .l
        stc
        ret
.ok:
        mov dx, 0x60
        in al, dx
        clc
        ret

; envia um comando ao controlador (0x64)
; edi = comando
ps2_ctrl_cmd:
        call ps2_wait_in
        jc .fail
        mov dx, 0x64
        mov eax, edi
        out dx, al
        clc
        ret
.fail:
        stc
        ret

; envia um byte para o mouse (0xD4 + byte), espera ACK
; edi = byte
ps2_aux_send:
        mov r9d, edi
        call ps2_wait_in
        jc .fail
        mov dx, 0x64
        mov al, 0xD4
        out dx, al
        call ps2_wait_in
        jc .fail
        mov dx, 0x60
        mov eax, r9d
        out dx, al
        ; espera ACK
        call ps2_wait_out
        jc .fail
        cmp al, 0xFA
        jne .fail
        clc
        ret
.fail:
        stc
        ret

; -----------------------------------------------------------------------------
k_ps2_init:
        ; esvazia o buffer de saída
        mov ecx, 64
.flush:
        mov dx, 0x64
        in al, dx
        test al, 1
        jz .flushed
        mov dx, 0x60
        in al, dx
        dec ecx
        jnz .flush
.flushed:
        ; modo de inicialização: IRQs descartam bytes de resposta
        mov dword [ps2_init_mode], 1
        ; lê a configuração do controlador
        mov edi, 0x20
        call ps2_ctrl_cmd
        call ps2_wait_out                 ; espera o byte de configuração
        mov [ps2_cfg], al
        ; set de scancode: bit 6 = tradução ativa (set 1)
        mov bl, al
        and bl, 0x40
        shr bl, 6
        mov [kbd_set1], bl
        ; habilita portas e IRQs, mantém a tradução como está
        mov al, [ps2_cfg]
        or al, 0x03                   ; IRQ1 + IRQ12
        and al, 0xCF                  ; clocks dos dois portos ligados
        mov [ps2_cfg], al
        mov edi, 0x60
        call ps2_ctrl_cmd
        call ps2_wait_in                  ; espera o buffer esvaziar
        mov dx, 0x60
        mov al, [ps2_cfg]
        out dx, al
        ; habilita a porta auxiliar (mouse)
        mov edi, 0xA8
        call ps2_ctrl_cmd
        ; mouse: defaults + resolução + streaming
        mov edi, 0xF6
        call ps2_aux_send
        ; resolução 3 (8 contagens/mm)
        mov edi, 0xE8
        call ps2_aux_send
        mov edi, 0x03
        call ps2_aux_send
        mov edi, 0xF4
        call ps2_aux_send
        ; teclado: liga a varredura (ignora falha)
        call ps2_wait_in
        mov dx, 0x60
        mov al, 0xF4
        out dx, al
        ; termina o modo de inicialização
        mov dword [ps2_init_mode], 0
        ; posição inicial do cursor: centro da tela
        mov eax, [screen_w]
        shr eax, 1
        mov [mouse_x], eax
        mov eax, [screen_h]
        shr eax, 1
        mov [mouse_y], eax
        mov dword [mouse_btns], 0
        ret

; -----------------------------------------------------------------------------
; kbd_irq
; -----------------------------------------------------------------------------
kbd_irq:
        in al, 0x60
        cmp dword [ps2_init_mode], 0
        jne .done                     ; respostas de comando durante init
        movzx r8d, al
        ; prefixo E0
        cmp r8d, 0xE0
        jne .not_e0
        mov dword [kbd_e0], 1
        ret
.not_e0:
        ; set 2: prefixo de break 0xF0
        cmp byte [kbd_set1], 0
        jne .set1
        cmp r8d, 0xF0
        jne .s2_make
        mov dword [kbd_break], 1
        ret
.s2_make:
        mov r9d, 1                    ; make
        cmp dword [kbd_break], 0
        jne .s2_brk
        jmp .have
.s2_brk:
        xor r9d, r9d                  ; break
        mov dword [kbd_break], 0
        jmp .have
.set1:
        mov r9d, r8d
        and r9d, 0x80                 ; bit 7 = break
        and r8d, 0x7F                 ; código de make
.have:
        ; r8d = código, r9d = make(1)/break(0)
        mov r10d, r8d
        call kbd_modifiers
        test eax, eax
        jz .done                      ; modificador (consumido)
        test r9d, r9d
        jz .done                      ; break de tecla comum: ignora
        call kbd_translate
        test eax, eax
        jz .done
        ; Ctrl+C mata processo estrangeiro
        cmp eax, 'c'
        jne .not_cc
        test dword [kbd_mods], 2
        jz .not_cc
        cmp dword [foreign_active], 0
        je .not_cc
        mov dword [kill_pending], 0x11
        jmp .done
.not_cc:
        call kq_push
.done:
        ret

kbd_modifiers:
        push rbx
        push r12
        mov r12d, r9d                 ; make
        xor ebx, ebx
        cmp byte [kbd_set1], 0
        je .s2
        cmp r10d, 0x2A
        je .lshift
        cmp r10d, 0x36
        je .lshift
        cmp r10d, 0x1D
        je .ctrl
        cmp r10d, 0x38
        je .alt
        cmp r10d, 0x3A
        je .caps
        jmp .common
.s2:
        cmp r10d, 0x12
        je .lshift
        cmp r10d, 0x59
        je .lshift
        cmp r10d, 0x14
        je .ctrl
        cmp r10d, 0x11
        je .alt
        cmp r10d, 0x58
        je .caps
        jmp .common
.lshift:
        mov ebx, 1
        jmp .mod
.ctrl:
        mov ebx, 2
        jmp .mod
.alt:
        mov ebx, 4
        jmp .mod
.caps:
        test r12d, r12d
        jz .consumed
        xor dword [kbd_mods], 8
        jmp .consumed
.mod:
        test r12d, r12d
        jz .clear
        or dword [kbd_mods], ebx
        jmp .consumed
.clear:
        not ebx
        and dword [kbd_mods], ebx
.consumed:
        mov dword [kbd_e0], 0
        xor eax, eax
        pop r12
        pop rbx
        ret
.common:
        mov eax, 1
        pop r12
        pop rbx
        ret

; kbd_translate: r10d=código, [kbd_e0] -> eax=char (0 se nada)
kbd_translate:
        push rbx
        xor eax, eax
        cmp dword [kbd_e0], 0
        je .base
        ; tabela estendida
        lea rbx, [kbd_ext1]
        cmp byte [kbd_set1], 0
        jne .ext_go
        lea rbx, [kbd_ext2]
.ext_go:
        mov ecx, [rbx]
        add rbx, 4
.ext_loop:
        test ecx, ecx
        jz .ext_none
        movzx edx, byte [rbx]
        cmp edx, r10d
        je .ext_found
        add rbx, 2
        dec ecx
        jmp .ext_loop
.ext_found:
        movzx eax, byte [rbx+1]
.ext_none:
        mov dword [kbd_e0], 0
        pop rbx
        ret
.base:
        ; tabela base: words [sc] = (normal, shift)
        cmp r10d, 128
        jae .none
        lea rbx, [kbd_map_set1]
        cmp byte [kbd_set1], 0
        jne .base_go
        lea rbx, [kbd_map_set2]
.base_go:
        movzx eax, word [rbx + r10*2]
        test dword [kbd_mods], 1      ; shift
        jz .noshift
        shr eax, 8
.noshift:
        ; caps lock inverte letras
        test dword [kbd_mods], 8
        jz .nocaps
        cmp eax, 'a'
        jb .nocaps
        cmp eax, 'z'
        ja .up
        sub eax, 32
        jmp .nocaps
.up:
        cmp eax, 'A'
        jb .nocaps
        cmp eax, 'Z'
        ja .nocaps
        add eax, 32
.nocaps:
        test eax, eax
        jz .none
        pop rbx
        ret
.none:
        xor eax, eax
        pop rbx
        ret

kq_push:                       ; eax=char, r10d=scancode
        mov edx, [kq_tail]
        mov ecx, edx
        inc ecx
        and ecx, 31
        cmp ecx, [kq_head]
        je .full
        push rdx
        shl edx, 4
        lea rdx, [kq_buf + rdx]
        mov [rdx], eax
        mov [rdx+4], r10d
        mov eax, [kbd_mods]
        mov [rdx+8], eax
        mov dword [rdx+12], 0
        pop rdx
        inc edx
        and edx, 31
        mov [kq_tail], edx
.full:
        ret

; -----------------------------------------------------------------------------
; mouse_irq
; -----------------------------------------------------------------------------
mouse_irq:
        in al, 0x60
        cmp dword [ps2_init_mode], 0
        jne .done
        movzx r8d, al
        mov ecx, [mouse_state]
        cmp ecx, 0
        jne .byte1
        ; byte 0: precisa do bit 3
        test r8d, 8
        jz .done
        ; overflow? descarta o pacote
        test r8d, 0xC0
        jnz .done
        mov [mouse_pkt], r8d
        mov dword [mouse_state], 1
        ret
.byte1:
        cmp ecx, 1
        jne .byte2
        mov [mouse_pkt+4], r8d
        mov dword [mouse_state], 2
        ret
.byte2:
        mov dword [mouse_state], 0
        ; aplica o delta
        mov eax, [mouse_pkt]          ; byte 0
        movzx ecx, byte [mouse_pkt+4] ; dx
        test eax, 0x10                ; sinal de dx
        jz .dx_pos
        or ecx, 0xFFFFFF00
.dx_pos:
        add [mouse_x], ecx
        mov ecx, [mouse_x]
        cmp ecx, 0
        jge .dx_ok
        mov dword [mouse_x], 0
.dx_ok:
        cmp ecx, [screen_w]
        jl .dx_ok2
        mov eax, [screen_w]
        dec eax
        mov [mouse_x], eax
.dx_ok2:
        movzx ecx, r8b                ; dy
        test eax, 0x20                ; sinal de dy
        jz .dy_pos
        or ecx, 0xFFFFFF00
.dy_pos:
        neg ecx                       ; para cima = positivo
        add [mouse_y], ecx
        mov ecx, [mouse_y]
        cmp ecx, 0
        jge .dy_ok
        mov dword [mouse_y], 0
.dy_ok:
        cmp ecx, [screen_h]
        jl .dy_ok2
        mov eax, [screen_h]
        dec eax
        mov [mouse_y], eax
.dy_ok2:
        ; botões
        mov eax, [mouse_pkt]
        and eax, 7
        mov [mouse_btns], eax
        mov dword [mouse_moved], 1
.done:
        ret

section .kdata
ps2_init_mode: dd 0
ps2_cfg:       db 0
               align 4
kbd_set1:      dd 1
kbd_e0:        dd 0
kbd_break:     dd 0
kbd_mods:      dd 0

kq_head: dd 0
kq_tail: dd 0
kq_buf:  times 32*16 db 0

mouse_state: dd 0
mouse_pkt:   dd 0, 0, 0
mouse_x:     dd 0
mouse_y:     dd 0
mouse_btns:  dd 0
mouse_moved: dd 0

%include "../obj/keymap.inc"

%endif
