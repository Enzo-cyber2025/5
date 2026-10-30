; =============================================================================
;  EnzoOS — kernel/serial.inc: log de depuração pela UART 16550 (COM1)
; =============================================================================
%ifndef SERIAL_INC
%define SERIAL_INC

section .kdata
serial_ready: dd 0

; -----------------------------------------------------------------------------
k_serial_init:
        mov dx, 0x3F9
        xor al, al
        out dx, al
        mov dx, 0x3FB
        mov al, 0x80
        out dx, al
        mov dx, 0x3F8
        mov al, 1
        out dx, al
        mov dx, 0x3F9
        xor al, al
        out dx, al
        mov dx, 0x3FB
        mov al, 0x03
        out dx, al
        mov dx, 0x3FA
        mov al, 0xC7
        out dx, al
        mov dx, 0x3FC
        mov al, 0x0B
        out dx, al
        mov dword [serial_ready], 1
        ret

; rdi = string NUL
k_log:
        push rbx
        mov rbx, rdi
        call k_log_str
        lea rbx, [rel s_nl]
        call k_log_str
        pop rbx
        ret

; rbx = string NUL
k_log_str:
        cmp dword [serial_ready], 1
        jne .done
.next:
        mov al, [rbx]
        test al, al
        jz .done
        mov ah, al
        mov dx, 0x3FD
.wait:
        in al, dx
        test al, 0x20
        jz .wait
        mov al, ah
        mov dx, 0x3F8
        out dx, al
        inc rbx
        jmp .next
.done:
        ret

; rdi = valor 64 bits -> hex
k_log_hex:
        push rbx
        mov rbx, rdi
        lea rdi, [rel s_hex0x]
        mov rax, rdi
        push rbx
        mov rbx, rdi
        call k_log_str
        pop rbx
        mov rcx, 16
.digit:
        rol rbx, 4
        mov rax, rbx
        and al, 0x0F
        cmp al, 10
        jb .dec
        add al, 'A' - 10 - '0'
.dec:
        add al, '0'
        mov [rel hexbuf], al
        push rbx
        push rcx
        lea rbx, [rel hexbuf]
        call k_log_str
        pop rcx
        pop rbx
        dec rcx
        jnz .digit
        lea rbx, [rel s_nl]
        call k_log_str
        pop rbx
        ret

section .kdata
s_nl:   db 13, 10, 0
s_hex0x: db "0x", 0
hexbuf: db 0, 0

%endif
