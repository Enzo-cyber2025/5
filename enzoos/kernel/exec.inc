; =============================================================================
;  EnzoOS — kernel/conout.inc + exec.inc: console de saída (anel 8 KiB) e
;  executor de binários estrangeiros (PE/ELF/BC) com watchdog.
; =============================================================================
%ifndef EXEC_INC
%define EXEC_INC

section .ktext

; -----------------------------------------------------------------------------
; conout: anel de saída
; -----------------------------------------------------------------------------
conout_write:                     ; rdi=str, rsi=len -> rax=len
        xor rax, rax
.loop:
        test rsi, rsi
        jz .done
        ; espaços livres?
        mov eax, [co_head]
        sub eax, [co_tail]
        and eax, 8191
        cmp eax, 8191
        jae .done                     ; cheio
        ; escreve
        mov ecx, [co_head]
        and ecx, 8191
        lea rdx, [co_buf]
        mov al, [rdi]
        mov [rdx + rcx], al
        inc dword [co_head]
        ; eco serial
        mov al, [rdi]
        cmp al, 10
        jne .ser
        mov rbx, s_nl
        call k_log_str
        jmp .next
.ser:
        mov al, [rdi]
        mov rbx, co_ch
        mov [rbx], al
        call k_log_str
.next:
        inc rdi
        dec rsi
        jmp .loop
.done:
        mov rax, rdi
        ret

conout_read:                      ; rdi=buf, rsi=max -> rax=len
        xor rax, rax
.loop:
        cmp rsi, 0
        je .done
        mov ecx, [co_head]
        sub ecx, [co_tail]
        jz .done
        mov edx, [co_tail]
        and edx, 8191
        lea rcx, [co_buf]
        mov cl, [rcx + rdx]
        mov [rdi], cl
        inc dword [co_tail]
        inc rdi
        dec rsi
        inc rax
        jmp .loop
.done:
        ret

; imprime o anel no console gráfico (janela do terminal chama a cada tick)
conout_take:                      ; rdi=buf, rsi=max -> rax=len (consome)
        jmp conout_read

; -----------------------------------------------------------------------------
; exec_foreign: rdi=entrada, rsi=pilha(0=auto), rdx=arg_rdi, rcx=arg_rsi
;               -> rax=código de retorno ou marcador 0xDEADxxxx
; -----------------------------------------------------------------------------
exec_foreign:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r10, rdi                   ; entrada
        mov r11, rsi                   ; pilha (0 = automática)
        mov r8, rdx                    ; arg1 do convidado
        mov r9, rcx                    ; arg2 do convidado
        mov eax, [fdepth]
        cmp eax, 7
        jae .fail
        lea rcx, [kern_rsp_stack]
        mov [rcx + rax*8], rsp         ; marco de unwind deste frame
        inc dword [fdepth]
        mov [kern_rsp], rsp
        mov dword [foreign_active], 1
        mov dword [foreign_quantum], 0
        mov dword [kill_pending], 0
        test r11, r11
        jnz .own_stack
        mov rax, [fstack_next]
        add rax, FSTACK_SIZE
        mov [fstack_next], rax
        mov rsp, rax
        and rsp, -16
        jmp .go
.own_stack:
        mov rsp, r11
        and rsp, -16
.go:
        mov rdi, r8
        mov rsi, r9
        call r10
        ; retorno normal
        mov [foreign_retcode], eax
        mov dword [foreign_active], 0
        mov rdx, [kern_rsp]            ; frame atual
        call foreign_fixup
        mov rsp, rdx
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        mov eax, [foreign_retcode]
        sti
        ret
.fail:
        xor eax, eax
        ret

; foreign_fixup: desce um nível de profundidade e ajusta kern_rsp
;                (rdx = rsp do frame atual, preservado)
foreign_fixup:
        push rax
        push rcx
        dec dword [fdepth]
        mov eax, [fdepth]
        test eax, eax
        jz .outer
        lea rcx, [kern_rsp_stack]
        mov rax, [rcx + rax*8]
        mov [kern_rsp], rax
        pop rcx
        pop rax
        ret
.outer:
        mov qword [kern_rsp], 0
        mov qword [fstack_next], FSTACK_BASE
        pop rcx
        pop rax
        ret

; -----------------------------------------------------------------------------
; foreign_exit: termina o convidado com código (chamado pelo próprio, via
; ExitProcess ou exit) — roda na pilha estrangeira.
;   edi = código de saída
; -----------------------------------------------------------------------------
foreign_exit:
        mov [foreign_retcode], edi
        mov dword [foreign_active], 0
        mov rdx, [kern_rsp]
        dec dword [fdepth]
        mov eax, [fdepth]
        lea rcx, [kern_rsp_stack]
        mov rax, [rcx + rax*8]
        mov [kern_rsp], rax
        mov rsp, rdx
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        mov eax, [foreign_retcode]
        sti
        ret

; -----------------------------------------------------------------------------
; sys_int80: camada de syscalls Linux-básicas para binários traduzidos
;   rax = nº, rdi/rsi/rdx = args (registrador de app é salvo pelo stub)
; -----------------------------------------------------------------------------
sys_int80:
        mov r11, rax
        ; write(1/2, buf, len)
        cmp r11, 1
        je .write
        cmp r11, 2
        je .write
        ; read — stdin não implementado: EOF
        cmp r11, 0
        je .read0
        ; exit(código)
        cmp r11, 60
        je .exit
        ; getpid
        cmp r11, 39
        je .getpid
        ; time(NULL)
        cmp r11, 201
        je .time
        ; brk — retorna valor fixo
        cmp r11, 12
        je .brk
        ; uname — preenche "EnzoOS"
        cmp r11, 63
        je .uname
        mov rax, -38
        ret
.write:
        mov rdi, rsi
        mov rsi, rdx
        call conout_write
        ret
.read0:
        xor rax, rax
        ret
.exit:
        mov edi, edi
        call foreign_exit
.getpid:
        mov rax, 0x5CE
        ret
.time:
        mov rax, [uptime_ms]
        mov ecx, 1000
        xor edx, edx
        div ecx
        ret
.brk:
        mov rax, rdi
        ret
.uname:
        ; rdi = struct utsname (6×65)
        test rdi, rdi
        jz .uname_done
        push rdi
        mov ecx, 6
.uf:
        push rcx
        mov ecx, 65
.fill:
        mov byte [rdi], 0
        inc rdi
        dec ecx
        jnz .fill
        pop rcx
        dec rcx
        jnz .uf
        pop rdi
        ; "EnzoOS"
        lea rsi, [s_uname]
        mov ecx, 6
.un:
        mov al, [rsi]
        mov [rdi], al
        inc rsi
        inc rdi
        dec ecx
        jnz .un
.uname_done:
        xor rax, rax
        ret

; -----------------------------------------------------------------------------
; k_exec: dispatcher geral — rdi=nome de arquivo -> rax=status
; -----------------------------------------------------------------------------
k_exec:
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
        call cefs_get
        mov r12, rax                    ; ptr
        mov r13, rdx                    ; size
        ; .ce?
        mov rdi, r15
        call k_strlen
        mov rcx, rax
        cmp rcx, 4
        jb .auto_detect
        lea rdi, [r15]
        add rdi, rcx
        sub rdi, 3
        lea rsi, [s_ext_ce2]
        call k_strcasecmp
        test rax, rax
        jz .do_ce
        ; por magia do conteúdo
.auto_detect:
        mov eax, [r12]
        cmp eax, CE_MAGIC
        je .do_ce
        cmp eax, 0x00905A4D             ; "MZ" + padding
        jne .chk_pe2
        jmp .do_pe
.chk_pe2:
        cmp ax, 0x5A4D
        je .do_pe
        cmp eax, 0x464C457F             ; "\x7FELF"
        je .do_elf
        ; shell? "#!"
        cmp word [r12], 0x2123
        je .do_sh
        ; zip/apk (PK\x03\x04)
        cmp dword [r12], 0x04034B50
        je .do_zip
        ; texto?
        mov rdi, r12
        call k_strlen
        test rax, rax
        jz .unknown
        jmp .do_txt
.do_ce:
        mov rdi, r15
        call app_launch
        jmp .done
.do_pe:
        mov rdi, r12
        mov rsi, r13
        mov rdx, r15
        call pe_run
        jmp .report
.do_elf:
        mov rdi, r12
        mov rsi, r13
        mov rdx, r15
        call elf_run
        jmp .report
.do_sh:
        mov rdi, r12
        mov rsi, r13
        mov rdx, r15
        call sh_run
        jmp .report
.do_zip:
        mov rdi, r12
        mov rsi, r13
        mov rdx, r15
        call apk_run
        jmp .report
.do_txt:
        mov rdi, r12
        mov rsi, r13
        mov rdx, r15
        call txt_run
        jmp .report
.unknown:
        mov rdi, r15
        call k_log
        mov rax, -9
        jmp .done
.notfound:
        mov rax, -1
        jmp .done
.report:
        ; rax = status; imprime mensagem se for código de saída
        mov r14, rax
        mov rdi, r15
        call k_log
        mov rdi, s_exec_exit
        call k_log
        mov edi, r14d
        call exec_report_hex
        mov rax, r14
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; exec_report_hex: edi=valor — imprime no console serial e gráfico
exec_report_hex:
        push rbx
        mov ebx, edi
        lea rsi, [numbuf2]
        mov edx, 16
        mov edi, ebx
        call k_utoa
        ; eco no conout
        mov rsi, rax
        lea rdi, [numbuf2]
        call conout_write
        ; fim de linha
        lea rdi, [s_eolb]
        mov esi, 1
        call conout_write
        pop rbx
        ret

section .kdata
co_head:  dd 0
co_tail:  dd 0
co_buf:  times 8192 db 0
co_ch:   db 0, 0

fdepth:  dd 0
kern_rsp_stack: times 8 dq 0
fstack_next: dq FSTACK_BASE

s_eol:   db 10, 0
s_eolb:  db 10
s_uname: db "EnzoOS"
s_ext_ce2: db ".CE", 0
s_exec_exit: db " -> saida 0x", 0
numbuf2: times 40 db 0

%endif
