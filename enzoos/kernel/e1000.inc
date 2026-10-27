; =============================================================================
;  EnzoOS — kernel/e1000.inc: driver de rede Intel e1000 (PCI)
;  Compatível com o QEMU (-device e1000) — transmit/receive por polling.
; =============================================================================
%ifndef E1000_INC
%define E1000_INC

%define E1000_NDESC 32

section .ktext

; -----------------------------------------------------------------------------
; k_e1000_init — acha a NIC, reseta anéis e configura RX/TX
; -----------------------------------------------------------------------------
k_e1000_init:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov edi, 0x020000                 ; classe: ethernet
        call pci_find_class
        cmp rax, -1
        jne .found
        mov rdi, s_e1000_none
        call k_log
        xor eax, eax
        mov [e1000_ok], eax
        jmp .done
.found:
        mov r12, rax
        mov edi, r12d
        call pci_io_enable
        ; BAR0 = MMIO
        mov edi, r12d
        call pci_read32                   ; registro 0 = BAR0
        mov rdi, rax
        call k_log_hex
        mov edi, r12d
        add edi, 4
        call pci_read32                   ; registro 1 = BAR0 high
        mov rdi, rax
        call k_log_hex
        mov edi, r12d
        call pci_read32
        and eax, 0xFFFFFFF0
        mov eax, eax
        mov [e1000_base], rax
        mov rdi, rax
        call k_log_hex
        mov rbx, rax
        ; máscara todas as interrupções (trabalhamos com polling)
        mov dword [rbx + 0x00F8*1], 0xFFFFFFFF
        ; pega o MAC (RAL/RAH)
        mov eax, [rbx + 0x5400]
        mov [net_mac], eax
        mov eax, [rbx + 0x5408]
        and eax, 0xFFFF
        mov [net_mac + 4], eax
        ; ---- RX ----
        ; zera os descritores e monta o anel
        lea rdi, [e1000_rxdesc]
        mov esi, E1000_NDESC * 16
        call k_memzero
        xor ecx, ecx
.rx_fill:
        cmp ecx, E1000_NDESC
        jae .rx_done
        mov eax, ecx
        imul eax, 16
        lea rdx, [e1000_rxdesc]
        add rdx, rax
        ; endereço do buffer
        mov rax, e1000_rxbuf
        mov r8d, ecx
        imul r8d, r8d, 1600
        add rax, r8
        mov [rdx], rax
        mov dword [rdx + 8], 0
        mov dword [rdx + 12], 0
        inc ecx
        jmp .rx_fill
.rx_done:
        mov rax, e1000_rxdesc
        mov [rbx + 0x2800], eax            ; RDBAL
        mov dword [rbx + 0x2804], 0        ; RDBAH
        mov dword [rbx + 0x2808], E1000_NDESC * 16   ; RDLEN
        mov dword [rbx + 0x2810], 0        ; RDH (leitura)
        mov dword [rbx + 0x2828], E1000_NDESC - 1    ; RDT
        mov dword [rbx + 0x0100], 0x8002   ; RCTL: EN | BAM
        ; ---- TX ----
        lea rdi, [e1000_txdesc]
        mov esi, E1000_NDESC * 16
        call k_memzero
        mov rax, e1000_txdesc
        mov [rbx + 0x3800], eax            ; TDBAL
        mov dword [rbx + 0x3804], 0
        mov dword [rbx + 0x3808], E1000_NDESC * 16   ; TDLEN
        mov dword [rbx + 0x3810], 0        ; TDH
        mov dword [rbx + 0x3818], 0        ; TDT
        mov dword [rbx + 0x0400], 0x4010A  ; TCTL: EN|PSP|CT|COLD
        mov dword [rbx + 0x0410], 0x60200A ; TIPG
        mov dword [e1000_rx_next], 0
        mov dword [e1000_tx_next], 0
        mov dword [e1000_ok], 1
        mov dword [net_pkts_rx], 0
        mov dword [net_pkts_tx], 0
        mov rdi, s_e1000_ok
        call k_log
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e1000_tx: rdi = buffer, esi = comprimento -> rax = 0 ok / -1
; -----------------------------------------------------------------------------
e1000_tx:
        push rbx
        push r12
        push r13
        cmp dword [e1000_ok], 0
        je .err
        mov rbx, rdi
        mov r12d, esi
        cmp r12d, 1514
        ja .err
        ; slot TX
        mov eax, [e1000_tx_next]
        and eax, E1000_NDESC - 1
        mov r13d, eax
        ; descritor
        imul eax, r13d, 16
        lea rdx, [e1000_txdesc]
        add rdx, rax
        mov [rdx], rbx                      ; endereço
        mov [rdx + 8], r12w                 ; comprimento
        mov byte [rdx + 11], 0x0B           ; EOP | IFCS | RS
        mov byte [rdx + 12], 0
        ; TDT++
        mov rax, [e1000_base]
        mov edx, [rax + 0x3818]
        inc edx
        and edx, E1000_NDESC - 1
        mov [rax + 0x3818], edx
        ; espera concluir (status DD)
        mov edi, 2000000
.wait:
        imul eax, r13d, 16
        lea rdx, [e1000_txdesc]
        add rdx, rax
        test byte [rdx + 12], 1
        jnz .ok
        dec edi
        jnz .wait
        jmp .err2
.ok:
        mov byte [rdx + 12], 0
        inc dword [e1000_tx_next]
        inc dword [net_pkts_tx]
        xor eax, eax
        jmp .out
.err:
.err2:
        mov eax, -1
.out:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e1000_rx_poll — processa pacotes recebidos (chama net_input)
; -----------------------------------------------------------------------------
e1000_rx_poll:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [e1000_ok], 0
        je .done
.loop:
        mov rax, [e1000_base]
        mov edx, [rax + 0x2810]             ; RDH
        mov ecx, [e1000_rx_next]
        and ecx, E1000_NDESC - 1
        cmp edx, ecx
        je .done                            ; nada novo
        ; descritor
        imul eax, ecx, 16
        lea rbx, [e1000_rxdesc]
        add rbx, rax
        test byte [rbx + 12], 1             ; DD?
        jz .done
        ; pacote pronto
        movzx r13d, word [rbx + 8]          ; comprimento
        mov r14, [rbx]                      ; buffer
        ; devolve o buffer ao anel
        mov byte [rbx + 12], 0
        inc dword [e1000_rx_next]
        mov rax, [e1000_base]
        mov edx, [e1000_rx_next]
        dec edx
        and edx, E1000_NDESC - 1
        mov [rax + 0x2828], edx             ; RDT
        inc dword [net_pkts_rx]
        ; processa
        cmp r13d, 64
        jb .loop
        mov edi, r14d
        mov esi, r13d
        call net_input
        jmp .loop
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

section .kdata
align 16
e1000_rxdesc: times E1000_NDESC * 16 db 0
e1000_txdesc: times E1000_NDESC * 16 db 0
align 16
e1000_rxbuf:  times E1000_NDESC * 1600 db 0

e1000_ok:     dd 0
e1000_base:   dq 0
e1000_rx_next: dd 0
e1000_tx_next: dd 0
net_pkts_rx:  dd 0
net_pkts_tx:  dd 0

s_e1000_none: db "[e1000] nenhuma NIC encontrada", 10, 0
s_e1000_ok:   db "[e1000] rede pronta", 10, 0

%endif
