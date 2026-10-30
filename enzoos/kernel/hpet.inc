; =============================================================================
;  EnzoOS — kernel/hpet.inc: timer de alta precisão HPET
;  (endereço padrão Intel 0xFED00000 — Apollo Lake e QEMU/q35)
; =============================================================================
%ifndef HPET_INC
%define HPET_INC

section .ktext

; -----------------------------------------------------------------------------
; k_hpet_init — valida e habilita o contador
; -----------------------------------------------------------------------------
k_hpet_init:
        mov rax, 0xFED00000
        mov ecx, [rax]              ; GCAP_ID
        test ecx, ecx
        jz .none
        mov edx, [rax + 4]          ; período em femtossegundos (43..100 MHz)
        cmp edx, 0
        je .none
        cmp edx, 0x05F5E100 * 10
        ja .none                    ; mais lento que 10 MHz? inválido
        mov [hpet_period_fs], edx
        ; habilita o contador (GENERAL_CONFIG bit 0)
        mov ecx, [rax + 0x10]
        or ecx, 1
        mov [rax + 0x10], ecx
        mov dword [hpet_ok], 1
        mov rdi, s_hpet_ok
        call k_log
        ret
.none:
        mov dword [hpet_ok], 0
        mov rdi, s_hpet_none
        call k_log
        ret

; -----------------------------------------------------------------------------
; hpet_ticks -> rax = valor do contador principal (64 bits)
; -----------------------------------------------------------------------------
hpet_ticks:
        xor eax, eax
        cmp dword [hpet_ok], 0
        jne .ok
        ret
.ok:
        mov rax, 0xFED00000
        mov rax, [rax + 0xF0]
        ret

; -----------------------------------------------------------------------------
; hpet_ns -> rax = nanossegundos desde a leitura de referência
; (ticks * período_fs / 1e6; período múltiplo de 10 ns típico — exato)
; -----------------------------------------------------------------------------
hpet_ns:
        push rdx
        call hpet_ticks
        mov edx, [hpet_period_fs]
        ; ns = ticks * period_fs / 1_000_000
        mov rcx, 1000000
        imul rax, rdx
        xor edx, edx
        div rcx
        pop rdx
        ret

section .kdata
hpet_ok:        dd 0
hpet_period_fs: dd 0
s_hpet_ok:   db "[hpet] timer de alta precisao ativo", 10, 0
s_hpet_none: db "[hpet] HPET ausente", 10, 0

%endif
