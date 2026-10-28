; =============================================================================
;  EnzoOS — kernel/net.inc: pilha de rede (ARP, IPv4, UDP/DHCP, TCP, HTTP)
;  Cliente simples: uma conexão TCP por vez (suficiente para HTTP).
;
;  Convenção: endereços IP ficam no "formato do fio" (u32 lido direto dos
;  bytes big-endian) — comparações e escritas em cabeçalhos são diretas.
; =============================================================================
%ifndef NET_INC
%define NET_INC

%define TCP_RBUF 32768

section .ktext

; -----------------------------------------------------------------------------
; k_net_init — DHCP na rede
; -----------------------------------------------------------------------------
k_net_init:
        cmp dword [e1000_ok], 0
        je .off
        call net_dhcp
        cmp dword [net_ip], 0
        je .noip
        mov rdi, s_net_ok
        call k_log
        ret
.noip:
        mov rdi, s_net_nodhcp
        call k_log
        ret
.off:
        mov rdi, s_net_none
        call k_log
        ret

; -----------------------------------------------------------------------------
; cksum_buf: rdi = dados, esi = bytes -> ax (checksum BE, soma por pares)
; -----------------------------------------------------------------------------
cksum_buf:
        push rbx
        push r12
        push r13
        mov rbx, rdi
        mov r12d, esi
        xor eax, eax
        xor ecx, ecx
.l:
        cmp ecx, r12d
        jae .fold
        movzx edx, byte [rbx + rcx]
        test cl, 1
        jnz .odd
        shl edx, 8
.odd:
        add eax, edx
        inc ecx
        jmp .l
.fold:
        mov ecx, eax
        shr ecx, 16
        and eax, 0xFFFF
        add eax, ecx
        mov ecx, eax
        shr ecx, 16
        and eax, 0xFFFF
        add eax, ecx
        not eax
        and eax, 0xFFFF
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; eth_tx: rdi = MAC destino, esi = ethertype, rdx = payload, ecx = len
; -----------------------------------------------------------------------------
eth_tx:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdx
        mov r13d, ecx
        mov r14d, esi
        mov r15, rdi
        mov rax, net_txbuf
        mov rcx, 6
.cd:
        mov dl, [r15]
        mov [rax], dl
        inc r15
        inc rax
        dec ecx
        jnz .cd
        mov rsi, net_mac
        mov ecx, 6
.cs:
        mov dl, [rsi]
        mov [rax], dl
        inc rsi
        inc rax
        dec ecx
        jnz .cs
        ; ethertype: BE (byte alto primeiro)
        mov edx, r14d
        shr edx, 8
        mov [rax], dl
        mov [rax + 1], r14b
        add rax, 2
        mov rdi, rax
        mov rsi, r12
        mov rdx, r13
        call k_memcpy
        mov edi, net_txbuf
        lea esi, [r13 + 14]
        call e1000_tx
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; net_input: rdi = quadro, esi = len
; -----------------------------------------------------------------------------
net_input:
        push rbx
        mov rbx, rdi
        movzx eax, word [rbx + 12]
        rol ax, 8
        cmp eax, 0x0806
        je .arp
        cmp eax, 0x0800
        je .ip
        pop rbx
        ret
.arp:
        mov rdi, rbx
        call arp_input
        pop rbx
        ret
.ip:
        mov rsi, r12
        mov rdi, rbx
        pop rbx
        jmp ip_input

; -----------------------------------------------------------------------------
; arp_input: rdi = quadro ARP
; -----------------------------------------------------------------------------
arp_input:
        push rbx
        mov rbx, rdi
        movzx eax, word [rbx + 20]
        rol ax, 8
        cmp eax, 2                       ; resposta
        je .reply
        cmp eax, 1                       ; pedido
        jne .out
        ; pediram nosso IP?
        mov eax, [rbx + 38]
        cmp eax, [net_ip]
        jne .out
        ; monta resposta no mesmo buffer
        mov word [rbx + 20], 0x0200        ; oper=2 (reply, BE)
        mov eax, [net_mac]
        mov edx, [rbx + 22]
        mov [rbx + 32], edx              ; THA <- SHA antigo
        mov [rbx + 22], eax              ; SHA <- nosso
        mov eax, [net_mac + 4]
        mov edx, [rbx + 26]
        mov [rbx + 36], edx
        mov [rbx + 26], eax
        mov eax, [rbx + 38]
        mov edx, [rbx + 28]
        mov [rbx + 28], eax              ; SPA <- TPA
        mov [rbx + 38], edx              ; TPA <- SPA
        mov rdi, rbx
        mov esi, 0x0806
        lea rdx, [rbx + 14]
        mov ecx, 28
        call eth_tx
        jmp .out
.reply:
        ; cacheia
        mov eax, [rbx + 28]
        mov [arp_ip], eax
        mov eax, [rbx + 22]
        mov [arp_mac], eax
        mov eax, [rbx + 26]
        mov [arp_mac + 4], eax
        mov dword [arp_valid], 1
.out:
        pop rbx
        ret

; -----------------------------------------------------------------------------
; arp_resolve: edi = IP (fio) -> rax = MAC em cache ou 0
; -----------------------------------------------------------------------------
arp_resolve:
        push rbx
        push r12
        push r13
        mov r12d, edi
        cmp dword [arp_valid], 0
        je .ask
        mov eax, [arp_ip]
        cmp eax, r12d
        je .have
.ask:
        mov r13d, 3
.try:
        lea rdi, [net_arppkt]
        mov dword [rdi], 0x00080100       ; htype=1, ptype=0x0800 (bytes 00 01 08 00)
        mov word [rdi + 4], 0x0406        ; hlen=6, plen=4
        mov word [rdi + 6], 0x0100        ; oper=1 (request)
        mov eax, [net_mac]
        mov [rdi + 8], eax                ; SHA
        mov eax, [net_mac + 4]
        mov [rdi + 12], eax
        mov eax, [net_ip]
        mov [rdi + 14], eax               ; SPA
        mov dword [rdi + 18], 0xFFFFFFFF  ; THA (broadcast)
        mov word [rdi + 22], 0xFFFF
        mov [rdi + 24], r12d              ; TPA
        mov rdi, net_bcast
        mov esi, 0x0806
        lea rdx, [net_arppkt]
        mov ecx, 28
        call eth_tx
        mov ebx, [uptime_ms]
        add ebx, 400
.wait:
        call e1000_rx_poll
        cmp dword [arp_valid], 0
        je .chk
        mov eax, [arp_ip]
        cmp eax, r12d
        je .have
.chk:
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .wait
        dec r13d
        jnz .try
        xor rax, rax
        jmp .out
.have:
        lea rax, [arp_mac]
.out:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; ip_send: edi = IP destino (fio), esi = proto, rdx = payload, ecx = len
; -----------------------------------------------------------------------------
ip_send:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        mov r13d, esi
        mov r14, rdx
        mov r15d, ecx
        ; broadcast: MAC ff:ff:ff:ff:ff:ff direto (ARP nao se aplica)
        cmp r12d, 0xFFFFFFFF
        jne .arp
        mov rbx, net_bcast
        jmp .have_mac
.arp:
        mov edi, [net_gw]
        test edi, edi
        jnz .gw
        mov edi, r12d
.gw:
        call arp_resolve
        test rax, rax
        jz .out
        mov rbx, rax
.have_mac:
        lea rdi, [net_iphdr]
        mov byte [rdi], 0x45
        mov byte [rdi + 1], 0
        lea eax, [r15 + 20]
        mov [rdi + 2], ah
        mov [rdi + 3], al
        inc dword [net_ipid]
        mov eax, [net_ipid]
        mov [rdi + 4], ah
        mov [rdi + 5], al
        mov byte [rdi + 6], 0x40          ; DF
        mov byte [rdi + 7], 0
        mov byte [rdi + 8], 64
        mov byte [rdi + 9], r13b
        mov word [rdi + 10], 0
        mov eax, [net_ip]
        mov [rdi + 12], eax
        mov [rdi + 16], r12d
        lea rdi, [net_iphdr]
        mov esi, 20
        call cksum_buf
        xchg al, ah                       ; checksum em BE
        mov rdi, net_iphdr
        mov [rdi + 10], ax
        lea rdi, [net_iphdr + 20]
        mov rsi, r14
        mov rdx, r15
        call k_memcpy
        mov rdi, rbx
        mov esi, 0x0800
        lea rdx, [net_iphdr]
        lea ecx, [r15 + 20]
        call eth_tx
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; ip_input: rdi = quadro, esi = len
; -----------------------------------------------------------------------------
ip_input:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov rbx, rdi
        cmp byte [rbx + 14], 0x45
        jne .out
        movzx r12d, byte [rbx + 23]
        mov r13, rbx
        add r13, 14
        movzx r14d, word [rbx + 16]
        rol r14w, 8
        sub r14d, 20
        cmp r14d, 0
        jle .out
        mov r15, r13
        add r15, 20
        cmp r12d, 17
        je .udp
        cmp r12d, 6
        je .tcp
        jmp .out
.udp:
        mov rdi, r15
        mov esi, r14d
        call udp_input
        jmp .out
.tcp:
        mov rdi, r15
        mov esi, r14d
        call tcp_input
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; udp_send: edi = IP (fio), esi = porta dst, rdx = payload, ecx = len
;           (usada só pelo DHCP: origem 68 -> destino 67)
; -----------------------------------------------------------------------------
udp_send:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        mov r14, rdx
        mov r15d, ecx
        lea rdi, [net_udphdr]
        mov byte [rdi], 0
        mov byte [rdi + 1], 68
        mov byte [rdi + 2], 0
        mov byte [rdi + 3], 67
        lea eax, [r15 + 8]
        mov [rdi + 4], ah
        mov [rdi + 5], al
        mov word [rdi + 6], 0
        lea rdi, [net_udphdr + 8]
        mov rsi, r14
        mov rdx, r15
        call k_memcpy
        mov edi, r12d
        mov esi, 17
        lea rdx, [net_udphdr]
        lea ecx, [r15 + 8]
        call ip_send
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; udp_input: rdi = payload UDP, esi = len
; -----------------------------------------------------------------------------
udp_input:
        push rbx
        push r12
        mov rbx, rdi
        mov r12d, esi
        movzx eax, word [rbx + 2]
        rol ax, 8
        cmp eax, 68
        jne .out
        add rbx, 8
        sub r12d, 8
        mov rdi, rbx
        mov esi, r12d
        call dhcp_input
.out:
        pop r12
        pop rbx
        ret

; =============================================================================
;  DHCP
; =============================================================================
net_dhcp:
        push rbx
        push r12
        push r13
        mov dword [dhcp_offer_ip], 0
        mov dword [dhcp_ack], 0
        mov dword [dhcp_gw], 0
        mov dword [dhcp_mask], 0
        mov eax, [uptime_ms]
        imul eax, eax, 2654435761
        mov [dhcp_xid], eax
        mov r13d, 4
.disc:
        mov rdi, s_dhcp_tx
        call k_log
        mov edi, 1                        ; DISCOVER
        call dhcp_xmit
        mov ebx, [uptime_ms]
        add ebx, 600
.wof:
        call e1000_rx_poll
        cmp dword [dhcp_offer_ip], 0
        jne .req
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .wof
        mov rdi, s_dhcp_to
        call k_log
        dec r13d
        jnz .disc
        jmp .out
.req:
        mov rdi, s_dhcp_off
        call k_log
        mov edi, 3                        ; REQUEST
        call dhcp_xmit
        mov ebx, [uptime_ms]
        add ebx, 900
.wack:
        call e1000_rx_poll
        cmp dword [dhcp_ack], 0
        jne .got
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .wack
        mov rdi, s_dhcp_to
        call k_log
        jmp .out
.got:
        mov rdi, s_dhcp_ok
        call k_log
        mov eax, [dhcp_offer_ip]
        mov [net_ip], eax
        mov eax, [dhcp_server]
        mov [net_srv], eax
        mov eax, [dhcp_gw]
        test eax, eax
        jnz .gwok
        mov eax, [dhcp_server]
.gwok:
        mov [net_gw], eax
        mov eax, [dhcp_mask]
        test eax, eax
        jnz .mok
        mov eax, 0x00FFFFFF
.mok:
        mov [net_mask], eax
        mov dword [arp_valid], 0
.out:
        pop r13
        pop r12
        pop rbx
        ret

; dhcp_xmit: edi = 1 (DISCOVER) ou 3 (REQUEST)
dhcp_xmit:
        push rbx
        mov ebx, edi
        lea rdi, [net_dhcppkt]
        mov esi, 300
        call k_memzero
        lea rdi, [net_dhcppkt]
        mov byte [rdi], 1
        mov byte [rdi + 1], 1
        mov byte [rdi + 2], 6
        mov eax, [dhcp_xid]
        mov [rdi + 4], eax
        mov word [rdi + 10], 0x0080       ; flags: broadcast (BE)
        mov eax, [net_mac]
        mov [rdi + 28], eax
        mov eax, [net_mac + 4]
        mov [rdi + 32], eax
        mov dword [rdi + 236], 0x63538263 ; magic cookie (fio)
        mov byte [rdi + 240], 53
        mov byte [rdi + 241], 1
        mov [rdi + 242], bl
        cmp ebx, 3
        jne .opts
        ; REQUEST: 50 (IP pedida) e 54 (servidor)
        mov byte [rdi + 243], 50
        mov byte [rdi + 244], 4
        mov eax, [dhcp_offer_ip]
        mov [rdi + 245], eax
        mov byte [rdi + 249], 54
        mov byte [rdi + 250], 4
        mov eax, [dhcp_server]
        mov [rdi + 251], eax
        mov byte [rdi + 255], 255
        jmp .send
.opts:
        mov byte [rdi + 243], 55
        mov byte [rdi + 244], 2
        mov byte [rdi + 245], 1
        mov byte [rdi + 246], 3
        mov byte [rdi + 247], 255
.send:
        mov edi, 0xFFFFFFFF
        mov esi, 67
        lea rdx, [net_dhcppkt]
        mov ecx, 300
        call udp_send
        pop rbx
        ret

; dhcp_input: rdi = pacote BOOTP, esi = len
dhcp_input:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov rbx, rdi
        mov eax, [rbx + 4]
        cmp eax, [dhcp_xid]
        jne .out
        lea r13, [rbx + 240]
        lea r14, [rbx + 300]
.opt:
        cmp r13, r14
        jae .out
        movzx eax, byte [r13]
        cmp eax, 255
        je .out
        cmp eax, 53
        je .mt
        inc r13
        movzx ecx, byte [r13]
        inc r13
        add r13, rcx
        jmp .opt
.mt:
        movzx eax, byte [r13 + 2]
        cmp eax, 2
        jne .mt2
        mov edx, [rbx + 16]
        mov [dhcp_offer_ip], edx
        jmp .out
.mt2:
        cmp eax, 5
        jne .out
        mov dword [dhcp_ack], 1
        mov edx, [rbx + 16]
        mov [dhcp_offer_ip], edx
        add r13, 3
.scan:
        cmp r13, r14
        jae .out
        movzx eax, byte [r13]
        cmp eax, 255
        je .out
        cmp eax, 1
        jne .n1
        mov edx, [r13 + 2]
        mov [dhcp_mask], edx
        jmp .skip
.n1:
        cmp eax, 3
        jne .n2
        mov edx, [r13 + 2]
        mov [dhcp_gw], edx
        jmp .skip
.n2:
        cmp eax, 54
        jne .skip
        mov edx, [r13 + 2]
        mov [dhcp_server], edx
.skip:
        inc r13
        movzx ecx, byte [r13]
        inc r13
        add r13, rcx
        jmp .scan
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; =============================================================================
;  TCP (cliente, uma conexão por vez)
; =============================================================================

; -----------------------------------------------------------------------------
; tcp_tx: edi = flags, rsi = payload (0 = nenhum), rdx = len
; -----------------------------------------------------------------------------
tcp_tx:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi              ; flags
        mov r13, rsi               ; payload
        mov r14d, edx              ; len
        lea rdi, [net_tcphdr]
        mov ax, [tcp_lport]
        rol ax, 8
        mov [rdi], ax
        mov ax, [tcp_rport]
        rol ax, 8
        mov [rdi + 2], ax
        mov eax, [tcp_seq]
        bswap eax
        mov [rdi + 4], eax
        mov eax, [tcp_ack]
        bswap eax
        mov [rdi + 8], eax
        mov byte [rdi + 12], 0x50
        mov [rdi + 13], r12b
        mov byte [rdi + 14], 0x20
        mov byte [rdi + 15], 0x00
        mov word [rdi + 16], 0
        mov word [rdi + 18], 0
        mov dword [rdi + 20], 0
        test r13, r13
        jz .nodata
        lea rdi, [net_tcphdr + 20]
        mov rsi, r13
        mov rdx, r14
        call k_memcpy
        lea r15d, [r14 + 20]
        jmp .ck
.nodata:
        mov r15d, 20
.ck:
        ; pseudo + segmento em net_ckbuf
        lea rdi, [net_ckbuf]
        mov eax, [net_ip]
        mov [rdi], eax
        mov eax, [tcp_rip]
        mov [rdi + 4], eax
        mov byte [rdi + 8], 0
        mov byte [rdi + 9], 6
        mov eax, r15d
        shr eax, 8
        mov [rdi + 10], al                ; len TCP em BE
        mov [rdi + 11], r15b
        lea rdi, [net_ckbuf + 12]
        lea rsi, [net_tcphdr]
        mov rdx, r15
        call k_memcpy
        lea rdi, [net_ckbuf]
        lea esi, [r15 + 12]
        call cksum_buf
        xchg al, ah                       ; checksum em BE
        mov rdi, net_tcphdr
        mov [rdi + 16], ax
        ; envia
        mov edi, [tcp_rip]
        mov esi, 6
        lea rdx, [net_tcphdr]
        mov ecx, r15d
        call ip_send
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; tcp_input: rdi = segmento, esi = len
; -----------------------------------------------------------------------------
tcp_input:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov rbx, rdi
        mov r12d, esi
        movzx eax, word [rbx]
        rol ax, 8
        cmp eax, [tcp_lport]
        jne .out
        movzx eax, word [rbx + 2]
        rol ax, 8
        cmp eax, [tcp_rport]
        jne .out
        movzx r13d, byte [rbx + 13]        ; flags
        movzx eax, byte [rbx + 12]
        shr eax, 4
        shl eax, 2                          ; bytes de cabeçalho
        mov r14d, r12d
        sub r14d, eax                       ; payload
        mov eax, [rbx + 4]
        bswap eax
        mov [tcp_rseq], eax
        mov eax, [rbx + 8]
        bswap eax
        mov [tcp_rack], eax
        cmp dword [tcp_state], 1
        jne .st2
        ; SYN|ACK?
        mov eax, r13d
        and eax, 0x12
        cmp eax, 0x12
        jne .out
        mov eax, [tcp_rseq]
        inc eax
        mov [tcp_ack], eax
        mov edi, 0x10
        xor esi, esi
        xor edx, edx
        call tcp_tx
        mov dword [tcp_state], 2
        jmp .out
.st2:
        cmp dword [tcp_state], 2
        jne .out
        test r13b, 0x04                     ; RST — abandona
        jnz .rst
        cmp r14d, 0
        jg .data
        ; sem payload: FIN sozinho?
        test r13b, 0x01
        jz .out
        mov eax, [tcp_rseq]
        inc eax
        mov [tcp_ack], eax
        mov dword [tcp_state], 3
        mov edi, 0x10
        xor esi, esi
        xor edx, edx
        call tcp_tx
        jmp .out
.rst:
        mov dword [tcp_state], 0
        jmp .out
.data:
        ; copia o payload para o anel
        xor ecx, ecx
.put:
        cmp ecx, r14d
        jae .putd
        mov eax, [tcp_rhead]
        sub eax, [tcp_rtail]
        cmp eax, TCP_RBUF
        jae .putd
        mov edx, [tcp_rhead]
        and edx, TCP_RBUF - 1
        mov r8d, r12d
        sub r8d, r14d
        add r8d, ecx
        movzx r9d, byte [rbx + r8]
        mov [tcp_rbuf + rdx], r9b
        inc dword [tcp_rhead]
        inc ecx
        jmp .put
.putd:
        mov eax, [tcp_rseq]
        add eax, r14d
        mov [tcp_ack], eax
        test r13b, 0x01                     ; FIN no mesmo segmento
        jz .dack
        inc dword [tcp_ack]                 ; o FIN consome 1 de seq
        mov dword [tcp_state], 3
.dack:
        mov edi, 0x10
        xor esi, esi
        xor edx, edx
        call tcp_tx
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; tcp_rx_read: rdi = destino, esi = máximo -> rax = bytes
; -----------------------------------------------------------------------------
tcp_rx_read:
        push rbx
        push r12
        push r13
        mov rbx, rdi
        mov r12d, esi
        xor r13d, r13d
.l:
        mov eax, [tcp_rtail]
        cmp eax, [tcp_rhead]
        jae .done
        cmp r13d, r12d
        jae .done
        mov edx, [tcp_rtail]
        and edx, TCP_RBUF - 1
        movzx eax, byte [tcp_rbuf + rdx]
        mov [rbx + r13], al
        inc dword [tcp_rtail]
        inc r13d
        jmp .l
.done:
        mov eax, r13d
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; tcp_connect: edi = IP (fio), esi = porta -> rax = 0/-1
; -----------------------------------------------------------------------------
tcp_connect:
        push rbx
        push r12
        push r13
        mov r12d, edi
        mov r13d, esi
        mov dword [tcp_rhead], 0
        mov dword [tcp_rtail], 0
        mov [tcp_rip], r12d
        mov [tcp_rport], r13w
        mov eax, [uptime_ms]
        and eax, 0x3FFF
        or eax, 0x4000
        mov [tcp_lport], ax
        mov eax, [uptime_ms]
        imul eax, eax, 2246822519
        add eax, [rand_seed]
        mov [tcp_seq], eax
        xor eax, eax
        mov [tcp_ack], eax
        mov dword [tcp_state], 1
        mov edi, 0x02
        xor esi, esi
        xor edx, edx
        call tcp_tx
        inc dword [tcp_seq]                ; o SYN consome 1 de seq
        mov ebx, [uptime_ms]
        add ebx, 1500
.w:
        call e1000_rx_poll
        cmp dword [tcp_state], 2
        je .ok
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .w
        mov dword [tcp_state], 0
        mov eax, -1
        jmp .out
.ok:
        xor eax, eax
.out:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; tcp_send: rdi = dados, esi = len -> rax = 0/-1
; -----------------------------------------------------------------------------
tcp_send:
        push rbx
        push r12
        push r13
        mov rbx, rdi
        mov r12d, esi
        cmp dword [tcp_state], 2
        jne .err
        mov edi, 0x18
        mov rsi, rbx
        mov edx, r12d
        call tcp_tx
        mov eax, [tcp_seq]
        add eax, r12d
        mov [tcp_seq], eax
        mov r13d, 2
.try:
        mov ebx, [uptime_ms]
        add ebx, 1200
.w:
        call e1000_rx_poll
        mov eax, [tcp_rack]
        cmp eax, [tcp_seq]
        jae .ok
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .w
        mov edi, 0x18
        mov rsi, rbx
        mov edx, r12d
        call tcp_tx
        dec r13d
        jnz .try
        jmp .err
.ok:
        xor eax, eax
        jmp .out
.err:
        mov eax, -1
.out:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; tcp_close
; -----------------------------------------------------------------------------
tcp_close:
        push rbx
        cmp dword [tcp_state], 2
        jne .out
        mov edi, 0x11
        xor esi, esi
        xor edx, edx
        call tcp_tx
        inc dword [tcp_seq]
        mov ebx, [uptime_ms]
        add ebx, 600
.w:
        call e1000_rx_poll
        cmp dword [tcp_state], 3
        je .out
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .w
.out:
        mov dword [tcp_state], 0
        pop rbx
        ret

; -----------------------------------------------------------------------------
; http_app: rdi = destino (no fim), rsi = ASCIZ -> rdi avançado
; -----------------------------------------------------------------------------
http_app:
.l:
        mov al, [rsi]
        test al, al
        jz .d
        mov [rdi], al
        inc rsi
        inc rdi
        jmp .l
.d:
        ret

; -----------------------------------------------------------------------------
; http_get: rdi = url "http://IP:PORTA/caminho", rsi = destino, rdx = máx
;           -> rax = bytes (com cabeçalho) ou erro negativo
; -----------------------------------------------------------------------------
http_get:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r15, rsi
        mov r14d, edx
        mov rbx, rdi
        cmp dword [e1000_ok], 0
        je .err_nic
        cmp dword [net_ip], 0
        je .err_nic
        add rbx, 7                           ; pula "http://"
        xor r8d, r8d                         ; IP lógico
        mov r9d, 4
.oct:
        xor eax, eax
.dig:
        movzx edx, byte [rbx]
        cmp dl, '.'
        je .oct_end
        cmp dl, ':'
        je .oct_end
        cmp dl, '/'
        je .oct_end
        test dl, dl
        jz .oct_end
        sub dl, '0'
        jb .err_url
        cmp dl, 9
        ja .err_url
        imul eax, eax, 10
        add eax, edx
        inc rbx
        jmp .dig
.oct_end:
        shl r8d, 8
        or r8d, eax
        inc rbx
        dec r9d
        jnz .oct
        cmp byte [rbx - 1], ':'
        jne .port_def
        xor eax, eax
.pd:
        movzx edx, byte [rbx]
        cmp dl, '/'
        je .port_ok
        test dl, dl
        jz .port_ok
        sub dl, '0'
        jb .err_url
        imul eax, eax, 10
        add eax, edx
        inc rbx
        jmp .pd
.port_def:
        mov eax, 80
.port_ok:
        mov [http_port], eax
        cmp byte [rbx], '/'
        je .path_ok
        mov byte [rbx], '/'
.path_ok:
        ; conecta (IP lógico -> formato do fio)
        bswap r8d
        mov edi, r8d
        mov esi, [http_port]
        call tcp_connect
        test eax, eax
        jnz .err_conn
        ; monta o pedido
        lea rdi, [net_httpreq]
        lea rsi, [s_http_get]
        call http_app
        mov rsi, rbx
        call http_app
        lea rsi, [s_http_host]
        call http_app
        mov eax, [tcp_rip]
        bswap eax
        call http_dec3
        mov byte [rdi], '.'
        inc rdi
        mov eax, [tcp_rip]
        bswap eax
        shr eax, 8
        call http_dec3
        mov byte [rdi], '.'
        inc rdi
        mov eax, [tcp_rip]
        bswap eax
        shr eax, 16
        call http_dec3
        mov byte [rdi], '.'
        inc rdi
        mov eax, [tcp_rip]
        bswap eax
        shr eax, 24
        call http_dec3
        lea rsi, [s_http_tail]
        call http_app
        ; envia
        lea rdi, [net_httpreq]
        call k_strlen
        mov esi, eax
        lea rdi, [net_httpreq]
        call tcp_send
        test eax, eax
        jnz .err_send
        ; recebe
        xor r12d, r12d
        mov r13d, [uptime_ms]
        add r13d, 8000
.rx:
        call e1000_rx_poll
        mov rdi, r15
        mov rsi, r14
        call tcp_rx_read
        test eax, eax
        jz .nord
        add r15, rax
        add r12d, eax
        sub r14d, eax
        jle .full
        mov r13d, [uptime_ms]
        add r13d, 8000
.nord:
        cmp dword [tcp_state], 3
        je .full
        mov eax, [uptime_ms]
        cmp eax, r13d
        jb .rx
.full:
        call tcp_close
        ; log de uma linha: bytes HTTP recebidos (para o canário do CI)
        push rax
        mov rdi, s_http_ok
        call k_log
        mov rdi, r12
        call k_log_hex
        pop rax
        jmp .out
.err_nic:
        mov eax, -10
        jmp .out
.err_url:
        mov eax, -11
        jmp .out
.err_conn:
        mov eax, -12
        jmp .out
.err_send:
        call tcp_close
        mov eax, -13
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; http_dec3: eax = 0..999 -> 3 dígitos sem zeros à esquerda; rdi avança
http_dec3:
        push rax
        push rdx
        xor edx, edx
        mov ecx, 100
        div ecx
        test eax, eax
        jz .s10
        add al, '0'
        mov [rdi], al
        inc rdi
        jmp .tens
.s10:
        test edx, edx
        jz .s1
.tens:
        mov eax, edx
        xor edx, edx
        mov ecx, 10
        div ecx
        test eax, eax
        jz .s1
        add al, '0'
        mov [rdi], al
        inc rdi
.s1:
        add dl, '0'
        test dl, '0'
        jz .d
        mov [rdi], dl
        inc rdi
.d:
        pop rdx
        pop rax
        ret

section .kdata
net_mac:      dq 0
net_ip:       dd 0
net_gw:       dd 0
net_mask:     dd 0
net_srv:      dd 0
net_ipid:     dd 0

arp_valid:    dd 0
arp_ip:       dd 0
arp_mac:      dq 0

dhcp_xid:       dd 0
dhcp_offer_ip:  dd 0
dhcp_server:    dd 0
dhcp_gw:        dd 0
dhcp_mask:      dd 0
dhcp_ack:       dd 0

tcp_state: dd 0
tcp_rip:   dd 0
tcp_lport: dw 0
tcp_rport: dw 0
tcp_seq:   dd 0
tcp_ack:   dd 0
tcp_rseq:  dd 0
tcp_rack:  dd 0
tcp_rhead: dd 0
tcp_rtail: dd 0
http_port: dd 80

align 16
tcp_rbuf:   times 32768 db 0
net_txbuf:  times 1600 db 0
net_iphdr:  times 1600 db 0
net_udphdr: times 1600 db 0
net_tcphdr: times 1600 db 0
net_ckbuf:  times 1600 + 16 db 0
net_arppkt: times 64 db 0
net_dhcppkt: times 320 db 0
net_httpreq: times 512 db 0
net_bcast: db 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF

s_net_none:   db "[net] sem rede", 10, 0
s_net_nodhcp: db "[net] DHCP sem resposta", 10, 0
s_net_ok:     db "[net] conectado via DHCP (e1000)", 10, 0
s_http_get:   db "GET ", 0
s_http_host:  db " HTTP/1.0", 10, "Host: ", 0
s_http_tail:  db 10, "User-Agent: EnzoFox/1.0 (EnzoOS)", 10, 10, 0
s_http_ok:    db "[net] HTTP ok, bytes:", 0

%endif

section .kdata
s_dhcp_tx:    db "[net] discover enviado", 0
s_dhcp_diag:  db "[net] fim do DHCP: tx/rx:", 0
s_dhcp_off:   db "[net] oferta recebida", 0
s_dhcp_to:    db "[net] sem resposta", 0
s_dhcp_ok:    db "[net] ack recebido", 0

