; =============================================================================
;  EnzoOS — kernel/pe.inc: tradutor PE (Portable Executable) — carrega .exe
;  e .dll, aplica relocações de base, lista importações e executa o entry.
; =============================================================================
%ifndef PE_INC
%define PE_INC

section .ktext

; -----------------------------------------------------------------------------
; pe_run: rdi=buf, rsi=size, rdx=nome -> rax=status
; -----------------------------------------------------------------------------
pe_run:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; buf
        mov r13, rsi                    ; size
        mov r14, rdx                    ; nome
        ; ---- cabeçalho DOS ----
        cmp word [r12], 0x5A4D
        jne .not_pe
        mov eax, [r12 + 0x3C]
        cmp eax, 0x400
        ja .not_pe
        cmp rax, r13
        jae .not_pe
        ; ---- assinatura PE ----
        mov rbx, r12
        add rbx, rax                    ; rbx = lfanew
        cmp dword [rbx], 0x00004550
        jne .not_pe
        movzx eax, word [rbx+6]
        mov [pe_nsects], eax
        movzx eax, word [rbx+20]
        mov [pe_sizeopt], eax
        lea r15, [rbx + 24]             ; r15 = optional header
        movzx eax, word [r15]
        cmp eax, 0x20B
        je .pe32p
        cmp eax, 0x10B
        je .pe32
        jmp .not_pe
.pe32p:
        mov dword [pe_plus], 1
        mov eax, [r15+16]
        mov [pe_entry], eax
        mov rax, [r15+24]
        mov [pe_imgbase], rax
        jmp .common_opt
.pe32:
        mov dword [pe_plus], 0
        mov eax, [r15+16]
        mov [pe_entry], eax
        mov eax, [r15+28]
        mov [pe_imgbase], rax
.common_opt:
        mov eax, [r15+56]
        mov [pe_imgsz], eax
        mov eax, [r15+60]
        mov [pe_hdrsz], eax
        cmp dword [pe_imgsz], 0x08000000
        ja .too_big
        ; ---- carrega em PE_BASE ----
        mov rdi, PE_BASE
        mov esi, [pe_imgsz]
        add rsi, 4095
        and rsi, -4096
        call k_memzero
        mov rdi, PE_BASE
        mov rsi, r12
        mov edx, [pe_hdrsz]
        cmp rdx, r13
        jbe .hh_ok
        mov edx, r13d
.hh_ok:
        call k_memcpy
        ; ---- seções ----
        mov eax, [pe_sizeopt]
        lea rbx, [r15 + rax]
        xor ecx, ecx
.sect:
        cmp ecx, [pe_nsects]
        jae .sects_done
        mov eax, [rbx + 12]             ; VirtualAddress
        add rax, PE_BASE
        mov [pe_dst], rax
        mov eax, [rbx + 20]             ; PointerToRawData
        add rax, r12
        mov [pe_src], rax
        mov eax, [rbx + 16]             ; SizeOfRawData
        cmp rax, r13
        jbe .rs_ok
        mov eax, r13d
.rs_ok:
        add rax, [rbx + 12]             ; vaddr + rawsize <= imgsz?
        cmp eax, [pe_imgsz]
        jbe .fits
        mov eax, [pe_imgsz]
        sub eax, [rbx + 12]
.fits:
        cmp rax, 0
        jle .next_sect
        mov [pe_len], rax
        mov rdi, [pe_dst]
        mov rsi, [pe_src]
        mov rdx, [pe_len]
        call k_memcpy
.next_sect:
        add rbx, 40
        inc ecx
        jmp .sect
.sects_done:
        call pe_reloc
        call pe_imports
        ; ---- executa ----
        mov rdi, s_pe_running
        call co_str
        mov rdi, r14
        call co_str
        call co_nl
        mov rdi, PE_BASE
        mov eax, [pe_entry]
        add rdi, rax
        xor rsi, rsi
        mov edx, 1                      ; argc
        xor rcx, rcx                    ; argv
        call exec_foreign
        mov r15, rax
        mov eax, r15d
        mov edx, 0xDEAD0000
        cmp eax, edx
        jb .normal_exit
        mov rdi, s_pe_killed
        call co_str
        mov edi, r15d
        call co_hex16
        call co_nl
        mov rax, r15
        jmp .out
.normal_exit:
        mov rdi, s_pe_exit
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
.not_pe:
        mov rdi, s_pe_nope
        call co_str
        mov rax, -2
        jmp .out
.too_big:
        mov rdi, s_pe_big
        call co_str
        mov rax, -3
        jmp .out

; -----------------------------------------------------------------------------
; pe_reloc: aplica relocações de base (DataDirectory[5]); usa r15 = opt
; -----------------------------------------------------------------------------
pe_reloc:
        push r12
        lea rax, [r15]
        add rax, 112
        cmp dword [pe_plus], 1
        je .have_dir
        lea rax, [r15]
        add rax, 96
.have_dir:
        mov edx, [rax + 5*8]            ; RVA
        test edx, edx
        jz .done
        mov ecx, [rax + 5*8 + 4]        ; tamanho
        mov rax, PE_BASE
        sub rax, [pe_imgbase]
        mov [pe_delta], rax
        mov r8, PE_BASE
        add r8, rdx                     ; primeiro bloco
        mov r12, r8
        add r12, rcx                    ; fim
.blk:
        mov ecx, [r8 + 4]               ; BlockSize
        cmp ecx, 8
        jb .done
        lea rax, [r8 + rcx]
        cmp rax, r12
        ja .done
        mov r9d, [r8]                   ; PageRVA
        lea r10, [r8 + 8]
        mov r11, rax                    ; fim do bloco
.ent:
        cmp r10, r11
        jae .next_blk
        movzx edx, word [r10]
        test edx, edx
        jz .next_blk
        mov ecx, edx
        shr ecx, 12                     ; tipo (4 bits altos)
        and edx, 0xFFF                  ; offset (12 bits baixos)
        cmp ecx, 3
        je .type3
        cmp ecx, 10
        je .type10
        jmp .next_ent
.type3:
        mov eax, edx
        add eax, r9d
        add rax, PE_BASE
        mov edx, [pe_delta]
        add [rax], edx
        jmp .next_ent
.type10:
        mov eax, edx
        add eax, r9d
        add rax, PE_BASE
        mov rcx, [pe_delta]
        add [rax], rcx
.next_ent:
        add r10, 2
        jmp .ent
.next_blk:
        mov ecx, [r8 + 4]
        add r8, rcx
        cmp r8, r12
        jb .blk
.done:
        pop r12
        ret

; -----------------------------------------------------------------------------
; pe_imports: conta DLLs e funções importadas (DataDirectory[1])
; -----------------------------------------------------------------------------
pe_imports:
        xor ecx, ecx
        mov [pe_ndlls], ecx
        mov [pe_nfuncs], ecx
        lea rax, [r15]
        add rax, 112
        cmp dword [pe_plus], 1
        je .have_dir
        lea rax, [r15]
        add rax, 96
.have_dir:
        mov edx, [rax + 1*8]
        test edx, edx
        jz .none
        mov rbx, PE_BASE
        add rbx, rdx
.desc:
        mov eax, [rbx + 12]             ; NameRVA
        test eax, eax
        jz .report
        inc dword [pe_ndlls]
        mov edx, [rbx]
        test edx, edx
        jnz .have_oft
        mov edx, [rbx + 16]
.have_oft:
        mov r9, PE_BASE
        add r9, rdx
.thunk:
        cmp dword [pe_plus], 1
        jne .t32
        mov rax, [r9]
        test rax, rax
        jz .next_desc
        inc dword [pe_nfuncs]
        add r9, 8
        jmp .thunk
.t32:
        mov eax, [r9]
        test eax, eax
        jz .next_desc
        inc dword [pe_nfuncs]
        add r9, 4
        jmp .thunk
.next_desc:
        add rbx, 20
        jmp .desc
.report:
        mov rdi, s_pe_imports
        call co_str
        mov edi, [pe_nfuncs]
        call co_dec
        mov rdi, s_pe_imports2
        call co_str
        mov edi, [pe_ndlls]
        call co_dec
        call co_nl
        ret
.none:
        mov rdi, s_pe_noimports
        call co_str
        ret

section .kdata
pe_nsects:  dd 0
pe_sizeopt: dd 0
pe_plus:    dd 0
pe_entry:   dd 0
pe_imgbase: dq 0
pe_imgsz:   dd 0
pe_hdrsz:   dd 0
pe_delta:   dq 0
pe_dst:     dq 0
pe_src:     dq 0
pe_len:     dq 0
pe_ndlls:   dd 0
pe_nfuncs:  dd 0

s_pe_running:   db "PE: executando ", 0
s_pe_exit:      db "PE: programa terminou com codigo ", 0
s_pe_killed:    db "PE: encerrado (watchdog/Ctrl+C/excecao), motivo 0x", 0
s_pe_nope:      db "PE: assinatura invalida", 0
s_pe_big:       db "PE: imagem grande demais", 0
s_pe_imports:   db "PE: importa ", 0
s_pe_imports2:  db " funcoes de ", 0
s_pe_noimports: db "PE: sem importacoes (freestanding)", 0

%endif
