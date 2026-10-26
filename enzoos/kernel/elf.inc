; =============================================================================
;  EnzoOS — kernel/elf.inc: tradutor ELF — .run (executáveis) e .so
;  (bibliotecas dinâmicas ET_DYN com relocações R_X86_64_RELATIVE).
; =============================================================================
%ifndef ELF_INC
%define ELF_INC

section .ktext

; -----------------------------------------------------------------------------
; elf_run: rdi=buf, rsi=size, rdx=nome -> rax=status
; -----------------------------------------------------------------------------
elf_run:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; buf
        mov r13, rsi                    ; size
        mov r14, rdx                    ; nome
        mov [elf_buf], rdi
        ; ---- identificador ----
        cmp dword [r12], 0x464C457F
        jne .not_elf
        cmp byte [r12+4], 2             ; 64 bits
        jne .not_elf
        movzx eax, word [r12+16]        ; e_type
        cmp eax, 2
        je .et_exec
        cmp eax, 3
        je .et_dyn
        jmp .bad_type
; ================== ET_EXEC: carrega nos endereços absolutos ==============
.et_exec:
        mov rax, [r12+24]
        mov [elf_entry], rax
        movzx ecx, word [r12+54]        ; e_phentsize
        mov [elf_phentsz], ecx
        movzx eax, word [r12+56]        ; e_phnum
        mov [elf_phnum], eax
        mov rax, [r12+32]               ; e_phoff
        add rax, r12
        mov [elf_ph], rax
        xor ecx, ecx
.seg:
        cmp ecx, [elf_phnum]
        jae .run_exec
        ; entrada do programa
        mov eax, ecx
        imul eax, [elf_phentsz]
        add rax, [elf_ph]
        mov rbx, rax
        cmp dword [rbx], 1              ; PT_LOAD
        jne .next_seg
        ; p_offset @+8, p_vaddr @+16, p_filesz @+32
        mov rax, [rbx+16]
        mov [elf_dst], rax
        ; zera p_memsz
        mov rdi, rax
        mov rsi, [rbx+40]               ; p_memsz
        call k_memzero
        ; copia p_filesz
        mov rdi, [elf_dst]
        mov rsi, [rbx+8]
        add rsi, r12
        mov rdx, [rbx+32]
        call k_memcpy
.next_seg:
        inc ecx
        jmp .seg
.run_exec:
        mov rdi, s_elf_running
        call co_str
        mov rdi, r14
        call co_str
        call co_nl
        mov rdi, [elf_entry]
        xor rsi, rsi
        mov edx, 1
        xor rcx, rcx
        call exec_foreign
        jmp .report
; ================== ET_DYN: biblioteca/PIE — base fixa + relocs ===========
.et_dyn:
        mov rax, [r12+24]
        mov [elf_entry], rax            ; relativo à base
        movzx ecx, word [r12+54]
        mov [elf_phentsz], ecx
        movzx eax, word [r12+56]
        mov [elf_phnum], eax
        mov rax, [r12+32]
        add rax, r12
        mov [elf_ph], rax
        ; base = ELF_BASE
        xor ecx, ecx
.dseg:
        cmp ecx, [elf_phnum]
        jae .dsegs_done
        mov eax, ecx
        imul eax, [elf_phentsz]
        add rax, [elf_ph]
        mov rbx, rax
        cmp dword [rbx], 1
        jne .next_dseg
        ; zera e copia deslocado pela base
        mov rdi, [rbx+16]
        add rdi, ELF_BASE
        mov rsi, [rbx+40]
        call k_memzero
        mov rdi, [rbx+16]
        add rdi, ELF_BASE
        mov rsi, [rbx+8]
        add rsi, r12
        mov rdx, [rbx+32]
        call k_memcpy
.next_dseg:
        inc ecx
        jmp .dseg
.dsegs_done:
        ; relocações RELATIVE via PT_DYNAMIC
        call elf_reloc
        ; executa
        mov rdi, s_elf_running
        call co_str
        mov rdi, r14
        call co_str
        call co_nl
        mov rdi, [elf_entry]
        add rdi, ELF_BASE
        xor rsi, rsi
        mov edx, 1
        xor rcx, rcx
        call exec_foreign
        jmp .report
; ================== relatório =============================================
.report:
        mov r15, rax
        mov eax, r15d
        mov edx, 0xDEAD0000
        cmp eax, edx
        jb .normal_exit
        mov rdi, s_elf_killed
        call co_str
        mov edi, r15d
        call co_hex16
        call co_nl
        mov rax, r15
        jmp .out
.normal_exit:
        mov rdi, s_elf_exit
        call co_str
        mov edi, r15d
        call co_dec
        call co_nl
        mov rax, r15
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret
.not_elf:
        mov rdi, s_elf_no
        call co_str
        mov rax, -2
        jmp .out
.bad_type:
        mov rdi, s_elf_type
        call co_str
        mov rax, -3
        jmp .out

; -----------------------------------------------------------------------------
; elf_reloc: aplica R_X86_64_RELATIVE do segmento dinâmico
; -----------------------------------------------------------------------------
elf_reloc:
        push rbx
        push r12
        xor ecx, ecx
.find_dyn:
        cmp ecx, [elf_phnum]
        jae .done
        mov eax, ecx
        imul eax, [elf_phentsz]
        add rax, [elf_ph]
        cmp dword [rax], 2              ; PT_DYNAMIC
        je .found
        inc ecx
        jmp .find_dyn
.found:
        mov rbx, rax
        mov r12, [elf_buf]
        add r12, [rbx+8]                ; tabela dinâmica
        ; varre d_tag/d_val (16 bytes por entrada)
        mov dword [er_rela], 0
        mov dword [er_relasz], 0
.dyn:
        mov rax, [r12]
        test rax, rax
        jz .have
        cmp rax, 7                      ; DT_RELA
        jne .chk_sz
        mov rax, [r12+8]
        mov [er_rela], rax
        jmp .dyn_next
.chk_sz:
        cmp rax, 8                      ; DT_RELASZ
        jne .dyn_next
        mov rax, [r12+8]
        mov [er_relasz], rax
.dyn_next:
        add r12, 16
        jmp .dyn
.have:
        mov rax, [er_rela]
        test rax, rax
        jz .done
        mov rcx, [er_relasz]
        ; entradas de 24 bytes: r_offset, r_info, r_addend
        add rax, ELF_BASE
        mov r12, rax
.ent:
        cmp rcx, 24
        jb .done
        ; tipo = r_info & 0xFFFFFFFF
        mov rax, [r12+8]
        and eax, 0xFFFFFFFF
        cmp eax, 8                      ; R_X86_64_RELATIVE
        jne .next
        ; *(base + r_offset) = base + r_addend
        mov rax, [r12]
        add rax, ELF_BASE
        mov rdx, [r12+16]
        add rdx, ELF_BASE
        mov [rax], rdx
.next:
        add r12, 24
        sub rcx, 24
        jmp .ent
.done:
        pop r12
        pop rbx
        ret

section .kdata
elf_entry:   dq 0
elf_ph:      dq 0
elf_phentsz: dd 0
elf_phnum:   dd 0
elf_buf:     dq 0
elf_dst:     dq 0
er_rela:     dq 0
er_relasz:   dq 0

s_elf_running: db "ELF: executando ", 0
s_elf_exit:    db "ELF: programa terminou com codigo ", 0
s_elf_killed:  db "ELF: encerrado (watchdog/Ctrl+C/excecao), motivo 0x", 0
s_elf_no:      db "ELF: assinatura invalida", 0
s_elf_type:    db "ELF: tipo nao suportado", 0

%endif
