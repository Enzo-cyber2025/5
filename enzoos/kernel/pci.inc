; =============================================================================
;  EnzoOS — kernel/pci.inc: barramento PCI (varredura e acesso a config)
;
;  Endereço de configuração: 0x80000000 | bus<<16 | dev<<11 | fn<<8 | reg<<2
; =============================================================================
%ifndef PCI_INC
%define PCI_INC

section .ktext

; -----------------------------------------------------------------------------
; pci_read32: edi = endereço de configuração -> eax = valor
; -----------------------------------------------------------------------------
pci_read32:
        mov edx, 0xCF8
        mov eax, edi
        or eax, 0x80000000          ; bit 31 = enable (idempotente p/ diag)
        out dx, eax
        mov edx, 0xCFC
        in eax, dx
        ret

; -----------------------------------------------------------------------------
; pci_write32: edi = endereço, esi = valor
; -----------------------------------------------------------------------------
pci_write32:
        mov edx, 0xCF8
        mov eax, edi
        or eax, 0x80000000          ; bit 31 = enable
        out dx, eax
        mov edx, 0xCFC
        mov eax, esi
        out dx, eax
        ret

; -----------------------------------------------------------------------------
; pci_io_enable: edi = endereço (dispositivo) — liga MMIO/IO e bus master
; -----------------------------------------------------------------------------
pci_io_enable:
        mov eax, edi
        and eax, 0xFFFFFF00         ; registro 4 (command)
        or eax, 4
        push rdi
        mov edi, eax
        call pci_read32
        pop rdi
        or eax, 7                   ; IO + MMIO + bus master
        mov esi, eax
        mov eax, edi
        and eax, 0xFFFFFF00
        or eax, 4
        mov edi, eax
        call pci_write32
        ret

; -----------------------------------------------------------------------------
; pci_find_class: edi = classe<<16 | subclass<<8 | progif (progif 0xFF ignora)
;                -> rax = endereço do dispositivo ou -1
; -----------------------------------------------------------------------------
pci_find_class:
        push rbx
        push r12
        push r13
        push r14
        mov r12d, edi               ; classe procurada
        xor r13d, r13d              ; bus
.bus:
        xor r14d, r14d              ; dev
.dev:
        xor ebx, ebx                ; fn
.fn:
        ; endereço base do dispositivo (registro 0)
        mov edi, r13d
        shl edi, 16
        mov eax, r14d
        shl eax, 11
        or edi, eax
        mov eax, ebx
        shl eax, 8
        or edi, eax
        or edi, 0x80000000
        mov r8d, edi                ; salva base
        call pci_read32
        cmp eax, 0xFFFF
        je .next_fn
        cmp eax, 0
        je .next_fn
        ; lê classe (registro 8: [rev][progif][subclass][class])
        mov edi, r8d
        or edi, 8
        call pci_read32
        shr eax, 8                  ; eax = class:subclass:progif (24 bits)
        mov ecx, r12d
        cmp cl, 0xFF                ; progif 0xFF = qualquer
        jne .exact
        and eax, 0xFFFF00
        and ecx, 0xFFFF00
.exact:
        cmp eax, ecx
        je .found
.next_fn:
        inc ebx
        cmp ebx, 8
        jb .fn
.next_dev:
        inc r14d
        cmp r14d, 32
        jb .dev
.next_bus:
        inc r13d
        cmp r13d, 256
        jb .bus
        mov rax, -1
        jmp .done
.found:
        mov eax, r8d
        and eax, 0x7FFFFF00         ; endereço base (sem bit enable/reg)
.done:
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

section .kdata

%endif
