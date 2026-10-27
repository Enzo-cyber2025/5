; =============================================================================
;  EnzoOS — kernel/hda.inc: áudio Intel HDA (ICH9/Apollo Lake — q35 e N5030)
;
;  CORB/RIRB (256 entradas: CORB 32 bits, RIRB 64 bits) + stream de saída
;  SD4 (primeiro de saída) a 48 kHz/16 bits/estéreo com BDL de 2 buffers.
;  Tons: onda triangular gerada por fase de 16 bits.
;  Sem controladora (ou sem init): tom cai para o PC speaker.
;
;  Verbs usados (Cad=0):
;    NID 2 verb 0x706 payload 0x10  — liga o conversor ao stream 1
;    NID 2 verb 0x002 payload 0x11  — formato 48 kHz, 16 bits, 2 canais
;    NID 3 verb 0x707 payload 0x40  — pino de saída habilitado
;    NID 3 verb 0x708 payload 0xB0  — amplificador de saída ligado
; =============================================================================
%ifndef HDA_INC
%define HDA_INC

section .ktext

; -----------------------------------------------------------------------------
; k_hda_init
; -----------------------------------------------------------------------------
k_hda_init:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov edi, 0x040300                 ; classe 04 subclass 03 (HDA)
        call pci_find_class
        cmp rax, -1
        jne .found
        mov edi, 0x040380                 ; variante: programação específica
        call pci_find_class
        cmp rax, -1
        jne .found
        mov dword [hda_ok], 0
        mov rdi, s_hda_none
        call k_log
        jmp .done
.found:
        mov r12, rax
        mov edi, r12d
        call pci_io_enable
        mov edi, r12d
        call pci_read32                   ; BAR0 (MMIO)
        and eax, 0xFFFFFFF0
        mov eax, eax
        mov [hda_base], rax
        mov rbx, rax
        ; versão
        movzx eax, word [rbx]
        test eax, eax
        jz .fail
        ; para os anéis
        mov byte [rbx + 0x4C], 0
        mov byte [rbx + 0x5C], 0
        ; reset dos ponteiros
        mov word [rbx + 0x4A], 0x8000
        mov word [rbx + 0x4A], 0
        mov word [rbx + 0x58], 0x8000
        mov word [rbx + 0x58], 0
        ; CORB: base + 256 entradas
        mov rax, hda_corb
        mov [rbx + 0x40], eax
        mov dword [rbx + 0x44], 0
        mov word [rbx + 0x4E], 0x0002
        ; RIRB: base + 256 entradas de 8 bytes
        mov rax, hda_rirb
        mov [rbx + 0x50], eax
        mov dword [rbx + 0x54], 0
        mov word [rbx + 0x5E], 0x0002
        mov word [rbx + 0x5C], 0          ; INTENT count 0 (sem interrupção)
        ; liga os anéis
        mov byte [rbx + 0x4C], 2          ; CORBRUN
        mov byte [rbx + 0x5C], 1          ; RIRBRUN
        ; codec presente no Cad 0?
        movzx eax, word [rbx + 0x0E]      ; STATESTS
        test eax, 1
        jz .fail
        ; ---- programa o codec ----
        ; conversor (NID 2): stream 1 canal 0
        mov edi, (0 << 28) | (2 << 20) | (0x706 << 8) | 0x10
        call hda_verb
        test eax, eax
        jnz .fail
        ; conversor: 48 kHz 16 bits 2 canais
        mov edi, (0 << 28) | (2 << 20) | (0x002 << 8) | 0x11
        call hda_verb
        test eax, eax
        jnz .fail
        ; pino de saída (NID 3): OUT enable
        mov edi, (0 << 28) | (3 << 20) | (0x707 << 8) | 0x40
        call hda_verb
        ; amplificador de saída
        mov edi, (0 << 28) | (3 << 20) | (0x708 << 8) | 0xB0
        call hda_verb
        ; ---- stream de saída SD4 (offset 0x80 + 4*0x20) ----
        mov r13, rbx
        add r13, 0x100
        mov dword [r13], 0                ; desligado
        mov rax, hda_bdl
        mov [r13 + 0x18], eax
        mov dword [r13 + 0x1C], 0
        mov dword [r13 + 0x08], 19200     ; CBL: 2 buffers x 9600 B
        mov word [r13 + 0x0C], 2          ; LVI: 2 entradas
        mov word [r13 + 0x12], 0x0011     ; FMT: 48 kHz 16 bits 2ch
        mov [hda_sd], r13
        mov dword [hda_ok], 1
        mov rdi, s_hda_ok
        call k_log
        jmp .done
.fail:
        mov dword [hda_ok], 0
        mov rdi, s_hda_fail
        call k_log
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; hda_verb: edi = verb (Cad/NID/verb/payload) -> eax = 0 ok / -1 timeout
; -----------------------------------------------------------------------------
hda_verb:
        push rbx
        push r12
        mov rbx, [hda_base]
        mov eax, [hda_wi]
        inc eax
        and eax, 0xFF
        mov [hda_wi], eax
        mov ecx, eax
        mov [hda_corb + rcx*4], edi
        ; publica no CORBWP
        mov [rbx + 0x48], ax
        ; espera o RIRBWP alcançar
        mov r12d, 2000000
.wait:
        movzx eax, word [rbx + 0x58]
        cmp eax, [hda_wi]
        jae .got
        dec r12d
        jnz .wait
        mov eax, -1
        jmp .out
.got:
        mov ecx, [hda_wi]
        mov eax, [hda_rirb + rcx*8]       ; resposta (32 bits)
        test eax, eax                     ; 0 = aceito (sem erro)
.out:
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; k_hda_tone: edi = freq (Hz), esi = duração (ms)
; -----------------------------------------------------------------------------
k_hda_tone:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [hda_ok], 0
        je .fallback
        mov r12d, edi                     ; freq
        mov r13d, esi                     ; ms
        ; incremento de fase por amostra: freq * 65536 / 48000
        mov eax, r12d
        mov ecx, 65536
        imul eax, ecx
        mov ecx, 48000
        xor edx, edx
        div ecx
        mov r14d, eax
        ; preenche 9600 amostras (100 ms: 2 x 50 ms, L e R intercalados)
        xor ecx, ecx
        xor r15d, r15d                    ; fase 16 bits
.fill:
        cmp ecx, 9600
        jae .filled
        ; triângulo: t = fase<0x8000 ? fase : 0xFFFF-fase; amostra = t*2-0x8000
        mov eax, r15d
        and eax, 0xFFFF
        cmp eax, 0x8000
        jb .rise
        mov edx, 0xFFFF
        sub edx, eax
        mov eax, edx
.rise:
        shl eax, 1
        sub eax, 0x8000
        sar eax, 4                        ; ~±2048
        mov [hda_pcm + rcx*2], ax
        add r15d, r14d
        inc ecx
        jmp .fill
.filled:
        ; BDL: 2 entradas de 9600 bytes (IOC desligado)
        lea rdi, [hda_bdl]
        mov rax, hda_pcm
        mov [rdi], rax
        mov dword [rdi + 8], 9600
        mov dword [rdi + 12], 0
        mov rax, hda_pcm + 9600
        mov [rdi + 16], rax
        mov dword [rdi + 24], 9600
        mov dword [rdi + 28], 0
        ; liga o stream (RUN + stream 1)
        mov rbx, [hda_sd]
        mov dword [rbx], 0x00010002
        ; espera a duração (voltas de 100 ms)
        mov eax, r13d
        add eax, 99
        xor edx, edx
        mov ecx, 100
        div ecx
        mov r13d, eax
        inc r13d
.wait:
        mov ebx, [uptime_ms]
        add ebx, 100
.w2:
        mov eax, [uptime_ms]
        cmp eax, ebx
        jb .w2
        dec r13d
        jnz .wait
        ; desliga
        mov rbx, [hda_sd]
        mov dword [rbx], 0
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret
.fallback:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        jmp k_beep

section .kdata
hda_base: dq 0
hda_sd:   dq 0
hda_ok:   dd 0
hda_wi:   dd 0
align 128
hda_corb: times 1024 db 0        ; 256 x dword
align 128
hda_rirb: times 2048 db 0        ; 256 x qword
align 128
hda_bdl:  times 128 db 0
align 4096
hda_pcm:  times 19200 db 0       ; 2 buffers de 9600 B

s_hda_none: db "[hda] sem controladora de audio — tom via PC speaker", 10, 0
s_hda_fail: db "[hda] init falhou — tom via PC speaker", 10, 0
s_hda_ok:   db "[hda] Intel HDA pronto (48 kHz, stream SD4)", 10, 0

%endif
