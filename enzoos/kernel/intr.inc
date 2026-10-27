; =============================================================================
;  EnzoOS — kernel/intr.inc: IDT, PIC, PIT, exceções, syscall int 0x80,
;  watchdog de processos estrangeiros, beep e RTC.
; =============================================================================
%ifndef INTR_INC
%define INTR_INC

section .ktext

; -----------------------------------------------------------------------------
; macros de stub
; -----------------------------------------------------------------------------
%macro PUSHAQ 0
        push rax
        push rbx
        push rcx
        push rdx
        push rsi
        push rdi
        push r8
        push r9
        push r10
        push r11
        push r12
        push r13
        push r14
        push r15
%endmacro

%macro POPAQ 0
        pop r15
        pop r14
        pop r13
        pop r12
        pop r11
        pop r10
        pop r9
        pop r8
        pop rdi
        pop rsi
        pop rdx
        pop rcx
        pop rbx
        pop rax
%endmacro

%macro EXC_NOERR 1
exc_%1:
        push qword 0
        push qword %1
        jmp exc_common
%endmacro

%macro EXC_ERR 1
exc_%1:
        push qword %1
        jmp exc_common
%endmacro

%macro IRQ_STUB 1
irq_%1:
        push qword 0
        push qword %1 + 32
        jmp irq_common
%endmacro

EXC_NOERR 0
EXC_NOERR 1
EXC_NOERR 2
EXC_NOERR 3
EXC_NOERR 4
EXC_NOERR 5
EXC_NOERR 6
EXC_NOERR 7
EXC_ERR    8
EXC_NOERR 9
EXC_ERR    10
EXC_ERR    11
EXC_ERR    12
EXC_ERR    13
EXC_ERR    14
EXC_NOERR 15
EXC_NOERR 16
EXC_ERR    17
EXC_NOERR 18
EXC_NOERR 19
EXC_NOERR 20
EXC_NOERR 21
EXC_NOERR 22
EXC_NOERR 23
EXC_NOERR 24
EXC_NOERR 25
EXC_NOERR 26
EXC_NOERR 27
EXC_NOERR 28
EXC_NOERR 29
EXC_NOERR 30
EXC_NOERR 31

IRQ_STUB 0
IRQ_STUB 1
IRQ_STUB 2
IRQ_STUB 3
IRQ_STUB 4
IRQ_STUB 5
IRQ_STUB 6
IRQ_STUB 7
IRQ_STUB 8
IRQ_STUB 9
IRQ_STUB 10
IRQ_STUB 11
IRQ_STUB 12
IRQ_STUB 13
IRQ_STUB 14
IRQ_STUB 15

int80_stub:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        cld
        call sys_int80
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        iretq

isr_ignore:
        iretq

; frame: [14 regs][vec][err][rip][cs][rflags][rsp][ss]
exc_common:
        mov [exc_rsp0], rsp          ; rsp do momento da excecao
        mov rsp, 0x8C000             ; pilha de emergencia (dump/panic)
        PUSHAQ
        mov rdi, rsp
        cld
        call exc_handler
        POPAQ
        mov rsp, [exc_rsp0]
        add rsp, 16
        iretq

section .kdata
exc_rsp0: dq 0
section .ktext

irq_common:
        PUSHAQ
        mov rdi, rsp
        cld
        call irq_handler
        cmp dword [foreign_active], 0
        je .no_kill
        cmp dword [kill_pending], 0
        je .no_kill
        ; watchdog / Ctrl+C: abandona o frame e devolve o controle ao tradutor
        mov edx, [kill_pending]
        mov dword [kill_pending], 0
        mov dword [foreign_active], 0
        mov [foreign_retcode], edx
        mov rdx, [kern_rsp]
        call foreign_fixup
        mov rsp, rdx
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        mov eax, [foreign_retcode]
        mov edx, 0xDEAD0000
        or rax, rdx
        sti
        ret
.no_kill:
        POPAQ
        add rsp, 16
        iretq

; -----------------------------------------------------------------------------
; irq_handler — rdi = frame
; -----------------------------------------------------------------------------
irq_handler:
        push rbx
        mov rbx, [rdi + 14*8]         ; vec
        cmp rbx, 32
        jb .done
        cmp rbx, 47
        ja .done
        cmp rbx, 40
        jb .eoi_master
        mov al, 0x20
        out 0xA0, al
.eoi_master:
        mov al, 0x20
        out 0x20, al
        cmp rbx, 32
        jne .not_pit
        call pit_irq
        jmp .done
.not_pit:
        cmp rbx, 33
        jne .not_kbd
        call kbd_irq
        jmp .done
.not_kbd:
        cmp rbx, 44
        jne .done
        call mouse_irq
.done:
        pop rbx
        ret

; -----------------------------------------------------------------------------
; exc_handler — rdi = frame
; -----------------------------------------------------------------------------
exc_handler:
        mov rax, [rdi + 14*8]         ; vec
        cmp rax, 14
        jne .no_pf
        ; página ausente: tenta paginação por demanda (swap)
        mov rax, cr2
        push rdi
        push rdx
        push rbx
        call sw_fault
        pop rbx
        pop rdx
        pop rdi
        test eax, eax
        jz .no_pf
        ret                            ; página restaurada — retoma
.no_pf:
        mov rdx, [rdi + 16*8]         ; rip
        mov rbx, [rdi + 14*8]         ; vec
        cmp dword [foreign_active], 0
        je .kernel_panic
        ; processo estrangeiro gerou exceção: mata e volta ao tradutor
        or ebx, 0xE0                     ; motivo 0xE0|nº da exceção
        mov [kill_pending], ebx
        mov [foreign_retcode], ebx
        mov dword [foreign_active], 0
        mov rdx, [kern_rsp]
        call foreign_fixup
        mov rsp, rdx
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        mov eax, [foreign_retcode]
        mov dword [kill_pending], 0
        mov edx, 0xDEAD0000
        or rax, rdx
        sti
        ret
.kernel_panic:
        mov rdi, rbx
        mov rsi, rdx
        call k_panic
.hang:
        hlt
        jmp .hang

; -----------------------------------------------------------------------------
; k_intr_init
; -----------------------------------------------------------------------------
k_intr_init:
        lea rdi, [idt_table]
        xor rcx, rcx
.fill:
        mov rax, isr_ignore
        cmp rcx, 32
        jae .maybe_irq
        lea rdx, [exc_table]
        mov rax, [rdx + rcx*8]
        jmp .set
.maybe_irq:
        cmp rcx, 48
        jae .maybe80
        lea rdx, [irq_table]
        mov rax, [rdx + (rcx-32)*8]
        jmp .set
.maybe80:
        cmp rcx, 0x80
        jne .set
        mov rax, int80_stub
.set:
        mov word [rdi], ax
        mov word [rdi+2], 0x18
        mov byte [rdi+4], 0
        mov byte [rdi+5], 0x8E
        shr rax, 16
        mov word [rdi+6], ax
        shr rax, 16
        mov dword [rdi+8], eax
        mov dword [rdi+12], 0
        add rdi, 16
        inc rcx
        cmp rcx, 256
        jb .fill
        lidt [idtr]

        ; PIC: remapeia IRQs para 0x20..0x2F (ICWs por controlador, em ordem)
        mov al, 0x11
        out 0x20, al
        out 0x80, al
        mov al, 0x20                  ; ICW2 master: base = vetor 32
        out 0x21, al
        out 0x80, al
        mov al, 4                     ; ICW3 master: slave na IRQ2
        out 0x21, al
        out 0x80, al
        mov al, 1                     ; ICW4: modo 8086
        out 0x21, al
        out 0x80, al
        mov al, 0x11
        out 0xA0, al
        out 0x80, al
        mov al, 0x28                  ; ICW2 slave: base = vetor 40
        out 0xA1, al
        out 0x80, al
        mov al, 2                     ; ICW3 slave: identidade 2
        out 0xA1, al
        out 0x80, al
        mov al, 1                     ; ICW4: modo 8086
        out 0xA1, al
        out 0x80, al
        ; máscara: habilita IRQ0 (PIT), IRQ1 (teclado), IRQ2 (cascata)
        mov al, 0xF8
        out 0x21, al
        ; habilita IRQ12 (mouse) no slave
        mov al, 0xEF
        out 0xA1, al

        ; PIT: 100 Hz
        mov al, 0x36
        out 0x43, al
        mov ax, 11932
        out 0x40, al
        mov al, ah
        out 0x40, al
        ret

; -----------------------------------------------------------------------------
; pit_irq — tique de 10 ms
; -----------------------------------------------------------------------------
pit_irq:
        inc dword [uptime_ticks]
        add dword [uptime_ms], 10
        cmp dword [foreign_active], 0
        je .done
        cmp dword [modal_active], 0
        jne .done
        inc dword [foreign_quantum]
        cmp dword [foreign_quantum], 500
        jb .done
        mov dword [kill_pending], 0x10
.done:
        ret

; -----------------------------------------------------------------------------
; k_beep — edi=freq, esi=ms
; -----------------------------------------------------------------------------
k_beep:
        push rbx
        push r12
        cmp edi, 20
        jb .done
        cmp edi, 20000
        ja .done
        cmp esi, 500
        jbe .ms_ok
        mov esi, 500
.ms_ok:
        mov r12d, esi
        mov eax, 1193182
        xor edx, edx
        div edi
        mov ebx, eax
        mov al, 0xB6
        out 0x43, al
        mov eax, ebx
        out 0x42, al
        mov al, bh
        out 0x42, al
        in al, 0x61
        or al, 3
        out 0x61, al
        mov eax, [uptime_ms]
        add eax, r12d
        mov dword [foreign_quantum], 0
.wait:
        hlt
        cmp dword [uptime_ms], eax
        jb .wait
        in al, 0x61
        and al, 0xFC
        out 0x61, al
.done:
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; RTC — lê data/hora no boot
; -----------------------------------------------------------------------------
k_rtc_read:
        mov ecx, 100000
.wait:
        mov al, 10
        out 0x70, al
        in al, 0x71
        test al, 0x80
        jz .ready
        loop .wait
.ready:
        mov al, 11
        out 0x70, al
        in al, 0x71
        mov bl, al                      ; registro B
        mov al, 0
        out 0x70, al
        in al, 0x71
        call .bcd
        mov [rtc_sec], eax
        mov al, 2
        out 0x70, al
        in al, 0x71
        call .bcd
        mov [rtc_min], eax
        mov al, 4
        out 0x70, al
        in al, 0x71
        and al, 0x7F
        call .bcd
        mov [rtc_hour], eax
        mov al, 7
        out 0x70, al
        in al, 0x71
        call .bcd
        mov [rtc_day], eax
        mov al, 8
        out 0x70, al
        in al, 0x71
        call .bcd
        mov [rtc_month], eax
        mov al, 9
        out 0x70, al
        in al, 0x71
        call .bcd
        mov [rtc_year], eax
        ret
.bcd:
        movzx eax, al
        test bl, 4
        jnz .bin
        mov ecx, eax
        and eax, 0x0F
        shr ecx, 4
        imul ecx, ecx, 10
        add eax, ecx
.bin:
        ret

section .kdata
align 16
idt_table: times 256*16 db 0
idtr: dw 256*16-1
      dq idt_table

uptime_ticks: dd 0
uptime_ms:   dd 0

foreign_active:  dd 0
foreign_quantum: dd 0
kill_pending:    dd 0
kern_rsp:        dq 0
kern_rsp_prev:   dq 0
foreign_retcode: dd 0

modal_active:    dd 0

rtc_sec:   dd 0
rtc_min:   dd 0
rtc_hour:  dd 0
rtc_day:   dd 0
rtc_month: dd 0
rtc_year:  dd 0

align 8
exc_table:
%assign i 0
%rep 32
        dq exc_ %+ i
%assign i i+1
%endrep
irq_table:
%assign i 0
%rep 16
        dq irq_ %+ i
%assign i i+1
%endrep

%endif
