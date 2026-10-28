; =============================================================================
;  EnzoOS — kernel/ahci.inc: driver AHCI (SATA, controladoras Intel —
;  ICH9/Apollo Lake). Leitura e escrita de setores por DMA com polling.
;
;  Alvo: porta 0..5, slot 0. Compatível com QEMU q35 (ich9-ahci) e com a
;  controladora SATA AHCI do Aspire 3 N5030 (Apollo Lake).
; =============================================================================
%ifndef AHCI_INC
%define AHCI_INC

section .ktext

; -----------------------------------------------------------------------------
; k_ahci_init — acha a controladora, prepara a porta e faz IDENTIFY
; -----------------------------------------------------------------------------
k_ahci_init:
        push rbx
        push r12
        push r13
        push r14
        push r15
        ; classe 0x01 (mass storage), 0x06 (SATA), 0x01 (AHCI)
        mov edi, 0x010601
        call pci_find_class
        cmp rax, -1
        jne .found
        ; alguns chipsetes reportam prog-if 0 — aceita 0x0106FF
        mov edi, 0x0106FF
        call pci_find_class
        cmp rax, -1
        jne .found
        mov rdi, s_ahci_none
        call k_log
        xor eax, eax
        mov [ahci_ok], eax
        jmp .done
.found:
        mov r12, rax                ; r12 = endereço base do dispositivo PCI
        ; liga o dispositivo
        mov edi, r12d
        call pci_io_enable
        ; BAR5 = ABAR (registro 0x24)
        mov edi, r12d
        add edi, 0x24
        call pci_read32
        and eax, 0xFFFFFFF0
        mov eax, eax
        mov [ahci_abar], rax
        ; porta implementada (registro PI @+0x0C)
        mov rbx, rax
        ; GHC.AE = bit 31 (bit 0 seria HR = hard reset!); limpa IS
        or dword [rbx + 0x04], 0x80000000
        mov dword [rbx + 0x08], 0xFFFFFFFF
        mov edx, [rbx + 0x0C]
        mov [ahci_pi], edx
        ; procura a primeira porta com disco
        xor r13d, r13d              ; porta
.port:
        cmp r13d, 6
        jae .noport
        mov eax, r13d
        shl eax, 7                  ; porta * 0x80
        add rax, rbx
        mov r14, rax                ; r14 = regs da porta
        bt edx, r13d                ; porta implementada?
        jnc .next_port
        mov eax, [r14 + 0x28]       ; PxSSTS
        and eax, 0x0F
        cmp eax, 3                  ; DET = dispositivo presente
        jne .next_port
        mov eax, [r14 + 0x24]       ; PxSIG: EB140101 = ATAPI (CD)
        cmp eax, 0xEB140101
        je .next_port
        jmp .port_ok
.next_port:
        inc r13d
        jmp .port
.noport:
        mov rdi, s_ahci_nodisk
        call k_log
        xor eax, eax
        mov [ahci_ok], eax
        jmp .done
.port_ok:
        mov [ahci_port], r14
        mov dword [ahci_ok], 1       ; porta valida: do_cmd pode rodar
        ; guarda a assinatura (PxSIG)
        mov eax, [r14 + 0x24]
        mov [ahci_sig], eax
        ; limpa erros da porta (SERR: escreve 1s) e IRQ pendente
        mov dword [r14 + 0x30], 0xFFFFFFFF
        ; para o motor antes de trocar os descritores
        mov edi, 100
        call ahci_stop
        ; lista de comandos (1 KB alinhada) e FIS de recebimento (256 B)
        mov rax, ahci_clb
        mov [r14 + 0x00], eax       ; PxCLB (baixo)
        mov dword [r14 + 0x04], 0   ; PxCLB (alto)
        mov rax, ahci_rfis
        mov [r14 + 0x08], eax       ; PxFB
        mov dword [r14 + 0x0C], 0
        ; liga FIS receive + start
        mov eax, [r14 + 0x18]       ; PxCMD
        or eax, 0x0011              ; FRE | ST
        mov [r14 + 0x18], eax
        ; limpa erros
        mov dword [r14 + 0x30], 0xFFFFFFFF
        ; IDENTIFY DEVICE
        mov edi, 0xEC
        xor esi, esi                ; LBA 0
        mov edx, 1
        mov rcx, ahci_ident
        xor r8d, r8d                ; leitura
        call ahci_do_cmd
        test eax, eax
        jnz .ident_fail
        ; capacidade LBA48: words 200..203 (endereço 400..407)
        movzx eax, word [ahci_ident + 400]
        movzx ecx, word [ahci_ident + 402]
        shl rcx, 16
        or rax, rcx
        movzx ecx, word [ahci_ident + 404]
        shl rcx, 32
        or rax, rcx
        movzx ecx, word [ahci_ident + 406]
        shl rcx, 48
        or rax, rcx
        test rax, rax
        jnz .have_cap
        ; fallback: words 60..61 (LBA28)
        movzx eax, word [ahci_ident + 120]
        movzx ecx, word [ahci_ident + 122]
        shl rcx, 16
        or rax, rcx
.have_cap:
        mov [ahci_sectors], rax
        mov rbx, rax                ; salva capacidade (k_log clobbera rax)
        mov dword [ahci_ok], 1
        mov rdi, s_ahci_ok
        call k_log
        mov rdi, s_ahci_sectors
        call k_log
        ; diag: word0 do IDENTIFY + capacidade + PRDBC do IDENTIFY
        mov edi, [ahci_ident]
        call k_log_hex
        mov rdi, rbx
        call k_log_hex
        mov edi, [ahci_clb + 4]
        call k_log_hex
        jmp .done
.ident_fail:
        mov rdi, s_ahci_ident_fail
        call k_log
        mov edi, [ahci_fail_at]
        call k_log_hex
        ; diag da porta: PxCMD, PxCI, PxTFD, PxSERR, PxSSTS, PxIS
        mov rax, [ahci_port]
        mov rdi, [rax + 0x18]
        call k_log_hex
        mov rdi, [rax + 0x38]
        call k_log_hex
        mov rdi, [rax + 0x20]
        call k_log_hex
        mov rdi, [rax + 0x30]
        call k_log_hex
        mov rdi, [rax + 0x28]
        call k_log_hex
        mov rdi, [rax + 0x10]
        call k_log_hex
        xor eax, eax
        mov [ahci_ok], eax
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; ahci_stop — para o motor da porta (edi = timeout em unidades de laço)
; -----------------------------------------------------------------------------
ahci_stop:
        mov rax, [ahci_port]
        mov edx, [rax + 0x18]       ; PxCMD
        and edx, 0xFFFFFFEE         ; ST = 0 e FRE = 0
        mov [rax + 0x18], edx
.wait_cr:
        mov edx, [rax + 0x18]
        test edx, 0xC000            ; CR | FR
        jz .ok
        dec edi
        jnz .wait_cr
.ok:
        ret

; -----------------------------------------------------------------------------
; ahci_do_cmd — executa um comando ATA no slot 0
;   edi = opcode, esi = LBA, edx = contagem de setores,
;   rcx = buffer, r8d = 1 (escrita) / 0 (leitura)
;   -> rax = 0 ok, -1 timeout, -2 sem AHCI
; -----------------------------------------------------------------------------
ahci_do_cmd:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [ahci_ok], 0
        je .nohci
        cmp dword [ahci_ident_done], 0
        jne .skip_ident_guard
.skip_ident_guard:
        mov r12, [ahci_port]        ; porta
        ; espera o slot 0 livre (PxCI bit 0)
        mov ebx, 4000000
.wait_ci:
        mov eax, [r12 + 0x38]       ; PxCI
        test eax, 1
        jz .ci_free
        dec ebx
        jnz .wait_ci
        mov dword [ahci_fail_at], 1 ; esperando CI livre
        mov eax, -1
        jmp .ret
.ci_free:
        ; ---- cabeçalho do comando (slot 0, 32 bytes) ----
        ; layout AHCICmdHdr: opts(0-1) PRDTL(2-3) PRDBC(4-7) CTBA(8-15)
        mov eax, 0x0005 | 0x0080
        test r8d, r8d
        jz .ro
        or eax, 0x0040
.ro:
        or eax, 0x00010000            ; PRDTL = 1
        mov [ahci_clb], eax
        mov dword [ahci_clb + 4], 0   ; PRDBC
        mov eax, ahci_ct
        mov [ahci_clb + 8], eax       ; CTBA (baixo)
        mov dword [ahci_clb + 12], 0  ; CTBA (alto)
        ; ---- CFIS (H2D register) ----
        mov r13, ahci_ct
        ; zera os 128 primeiros bytes (CFIS + ACMD)
        xor ecx, ecx
        xor eax, eax
.zc:
        mov [r13 + rcx], eax
        add ecx, 4
        cmp ecx, 128
        jb .zc
        mov byte [r13 + 0], 0x27    ; tipo FIS reg H2D
        mov byte [r13 + 1], 0x80    ; bit C
        mov [r13 + 2], dil          ; comando
        ; LBA (48 bits) — por campo
        mov eax, esi
        mov [r13 + 4], al           ; LBA 0:7
        shr eax, 8
        mov [r13 + 5], al           ; LBA 8:15
        shr eax, 8
        mov [r13 + 6], al           ; LBA 16:23
        mov rax, rsi
        shr rax, 24
        mov byte [r13 + 8], al      ; LBA 24:31
        mov rax, rsi
        shr rax, 32
        mov byte [r13 + 9], al      ; LBA 32:39
        mov rax, rsi
        shr rax, 40
        mov byte [r13 + 10], al     ; LBA 40:47
        mov byte [r13 + 7], 0x40    ; device: LBA
        mov eax, edx
        mov [r13 + 12], al          ; contagem 0:7
        mov eax, edx
        shr eax, 8
        mov [r13 + 13], al          ; contagem 8:15
        ; ---- PRDT: uma entrada, buffer inteiro ----
        mov rax, rcx                ; endereço do buffer (físico = virtual)
        mov [r13 + 128], rax        ; DBA
        mov dword [r13 + 136], 0
        mov eax, edx
        shl eax, 9                  ; setores * 512
        or eax, 0x80000000          ; interrompe ao completar (para o polling)
        mov [r13 + 140], eax
        ; ---- dispara ----
        mov eax, [r12 + 0x38]
        or eax, 1
        mov [r12 + 0x38], eax
        ; espera completar: PxCI volta a 0 e TFD sem BSY/DRQ
        mov ebx, 6000000
.wait:
        mov eax, [r12 + 0x38]
        test eax, 1
        jz .chk_tfd
        dec ebx
        jnz .wait
        mov dword [ahci_fail_at], 2 ; CI nao voltou a 0
        mov eax, -1
        jmp .ret
.chk_tfd:
        mov eax, [r12 + 0x20]       ; PxTFD
        test eax, 0x88              ; BSY | DRQ
        jz .ok
        dec ebx
        jnz .wait
        mov dword [ahci_fail_at], 3 ; TFD com BSY/DRQ
        mov eax, -1
        jmp .ret
.ok:
        xor eax, eax
.ret:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret
.nohci:
        mov eax, -2
        jmp .ret

; -----------------------------------------------------------------------------
; ahci_read: rdi = LBA, rsi = setores (1..8), rdx = buffer -> rax = 0/-1/-2
; -----------------------------------------------------------------------------
ahci_read:
        push r8
        mov rcx, rdx                ; buffer
        mov rdx, rsi                ; contagem
        mov rsi, rdi                ; LBA
        mov edi, 0x25               ; READ DMA EXT
        xor r8d, r8d
        call ahci_do_cmd
        pop r8
        ret

; -----------------------------------------------------------------------------
; ahci_write: rdi = LBA, rsi = setores, rdx = buffer -> rax
; -----------------------------------------------------------------------------
ahci_write:
        push r8
        mov rcx, rdx
        mov rdx, rsi
        mov rsi, rdi
        mov edi, 0x35               ; WRITE DMA EXT
        mov r8d, 1
        call ahci_do_cmd
        pop r8
        ret

section .kdata
align 1024
ahci_clb:   times 1024 db 0         ; lista de cabeçalhos (32 slots)
align 256
ahci_rfis:  times 256 db 0          ; FIS recebidos
align 128
ahci_ct:    times 256 db 0          ; tabela do comando 0 (CFIS+ACMD+PRDT)
align 16
ahci_ident: times 512 db 0          ; dados do IDENTIFY

ahci_ok:      dd 0
ahci_fail_at: dd 0
ahci_ident_done: dd 0
ahci_abar:    dq 0
ahci_pi:      dd 0
ahci_sig:     dd 0
ahci_sectors: dq 0
ahci_port:    dq 0

s_ahci_none:       db "[ahci] controladora AHCI nao encontrada", 10, 0
s_ahci_nodisk:     db "[ahci] sem disco na porta", 10, 0
s_ahci_ident_fail: db "[ahci] IDENTIFY falhou", 10, 0
s_ahci_ok:         db "[ahci] SATA AHCI pronto", 10, 0
s_ahci_sectors:    db "[ahci] disco detectado", 10, 0

%endif
