; =============================================================================
;  EnzoOS — kernel/mm.inc: gerenciador de memória física (bitmap)
;
;  O heap do kernel cobre [HEAP_START, heap_top) com páginas de 4 KiB.
;  heap_top = topo da região RAM mais alta do E820, limitado a HEAP_MAX.
;  Alocação first-fit de blocos contíguos.
; =============================================================================
%ifndef MM_INC
%define MM_INC

section .ktext

; -----------------------------------------------------------------------------
; mark_used / mark_free / page_is_free — rax = índice da página
; -----------------------------------------------------------------------------
mark_used:
        push rcx
        push r8
        push r9
        mov r8, rax
        shr r8, 3
        mov r9, HEAP_START
        add r9, r8
        mov rcx, rax
        and rcx, 7
        mov r8, 1
        shl r8, cl
        or [r9], r8b
        pop r9
        pop r8
        pop rcx
        ret

mark_free:
        push rcx
        push r8
        push r9
        mov r8, rax
        shr r8, 3
        mov r9, HEAP_START
        add r9, r8
        mov rcx, rax
        and rcx, 7
        mov r8, 1
        shl r8, cl
        not r8
        and [r9], r8b
        pop r9
        pop r8
        pop rcx
        ret

page_is_free:
        push rcx
        push r8
        push r9
        mov r8, rax
        shr r8, 3
        mov r9, HEAP_START
        add r9, r8
        mov rcx, rax
        and rcx, 7
        mov r8, 1
        shl r8, cl
        test [r9], r8b
        setz al
        movzx rax, al
        pop r9
        pop r8
        pop rcx
        ret

; -----------------------------------------------------------------------------
k_mm_init:
        ; E820: soma RAM e acha o topo
        mov r8d, [boot_params + BP_E820N]
        mov r9d, [boot_params + BP_E820P]   ; ponteiro 32-bit (dword no BP)
        ; diag: count e ponteiro
        mov edi, r8d
        call k_log_hex
        mov rdi, r9
        call k_log_hex
        xor r10, r10                  ; total RAM
        xor r11, r11                  ; topo da RAM
.mm_next:
        test r8d, r8d
        jz .mm_done
        cmp dword [r9+16], 1
        jne .mm_skip
        mov rax, [r9+8]
        add r10, rax
        mov rax, [r9+0]
        add rax, [r9+8]
        cmp rax, r11
        jbe .mm_skip
        mov r11, rax
.mm_skip:
        add r9, 24
        dec r8d
        jmp .mm_next
.mm_done:
        mov [ram_total], r10
        push rdi
        lea rdi, [rel s_mm_e820]
        call k_log
        mov rdi, r10                 ; diag: ram_total
        call k_log_hex
        mov rdi, r11                 ; diag: topo
        call k_log_hex
        pop rdi
        ; heap_top = min(topo, HEAP_MAX)
        mov rax, r11
        mov rcx, HEAP_MAX
        cmp rax, rcx
        jbe .min_ok
        mov rax, rcx
.min_ok:
        ; clamp defensivo: heap_top deve ficar sempre >= HEAP_START+1 MB
        mov rcx, HEAP_START + 0x100000
        cmp rax, rcx
        jae .clamp_ok
        mov rax, rcx
.clamp_ok:
        mov [heap_top], rax
        ; páginas e bitmap
        mov rcx, rax
        sub rcx, HEAP_START
        shr rcx, 12
        mov [heap_pages], rcx
        add rcx, 7
        shr rcx, 3
        mov [bitmap_bytes], rcx
        mov rdi, HEAP_START
        mov rsi, rcx
        call k_memzero
        mov rax, [bitmap_bytes]
        add rax, 4095
        shr rax, 12
        mov [bitmap_pages], rax
        ; marca as páginas do bitmap como usadas
        xor rcx, rcx
.mark:
        cmp rcx, [bitmap_pages]
        jae .marked
        mov rax, rcx
        call mark_used
        inc rcx
        jmp .mark
.marked:
        push rdi
        lea rdi, [rel s_mm_bitmap]
        call k_log
        mov rdi, [bitmap_bytes]      ; diag
        call k_log_hex
        pop rdi
        ; reserva a zona de binários estrangeiros:
        ; [PE_BASE, 0x1D000000) = PE + ELF + 8 pilhas de 1 MB
        mov rax, [heap_top]
        cmp rax, PE_BASE
        jbe .reserved                   ; RAM pequena: zona fora do heap
        mov rax, PE_BASE
        sub rax, HEAP_START
        shr rax, 12
        mov rcx, 0x1D000000 - PE_BASE
        shr rcx, 12
.reserve:
        test rcx, rcx
        jz .reserved
        call mark_used
        inc rax
        dec rcx
        jmp .reserve
.reserved:
        lea rdi, [rel s_mm_end]
        call k_log
        ret

; -----------------------------------------------------------------------------
; k_alloc — rdi=bytes -> rax=ptr (0 se falhar)
; -----------------------------------------------------------------------------
k_alloc:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        add r12, 4095
        shr r12, 12
        test r12, r12
        jz .fail
        mov r13, [heap_pages]
        sub r13, r12
        mov r14, [bitmap_pages]
        ; diag
        lea rdi, [rel s_ka_start]
        call k_log
        mov rdi, r12
        call k_log_hex
        mov rdi, [heap_pages]
        call k_log_hex
.next:
        cmp r14, r13
        ja .fail
        mov r15, r14
        mov rbx, r12
.test:
        mov rax, r15
        call page_is_free
        test rax, rax
        jz .advance
        inc r15
        dec rbx
        jnz .test
        mov r15, r14
        mov rbx, r12
.mark:
        mov rax, r15
        call mark_used
        inc r15
        dec rbx
        jnz .mark
        mov rax, r14
        shl rax, 12
        add rax, HEAP_START
        ; diag
        push rax
        lea rdi, [rel s_ka_ok]
        call k_log
        mov rdi, rax
        call k_log_hex
        pop rax
        jmp .done
.advance:
        inc r14
        jmp .next
.fail:
        ; pressão de memória: tenta recuperar páginas via swap e repete
        cmp dword [sw_armed], 0
        je .fail2
        cmp dword [sw_retry], 0
        jne .fail2
        mov dword [sw_retry], 1
        mov edi, 64
        call sw_reclaim
        mov dword [sw_retry], 0
        mov r13, [heap_pages]
        sub r13, r12
        mov r14, [bitmap_pages]
        jmp .next
.fail2:
        ; diag
        lea rdi, [rel s_ka_fail]
        call k_log
        mov rdi, [heap_pages]
        call k_log_hex
        mov rdi, [bitmap_pages]
        call k_log_hex
        xor rax, rax
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; k_free_n — rdi=ptr, rsi=páginas
; -----------------------------------------------------------------------------
k_free_n:
        push rbx
        push r12
        push r13
        cmp rdi, HEAP_START
        jb .done
        mov r13, rdi
        add r13, 4095
        and r13, -4096               ; primeira página
        mov rbx, rsi
.loop:
        test rbx, rbx
        jz .done
        mov rdi, r13
        call sw_free_frame           ; desmapeia e devolve o frame da PTE
        add r13, 4096
        dec rbx
        jmp .loop
.done:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; k_free — rdi=ptr (libera 1 página)
; -----------------------------------------------------------------------------
k_free:
        push rsi
        mov rsi, 1
        call k_free_n
        pop rsi
        ret

; -----------------------------------------------------------------------------
; k_free_bytes — rdi=ptr, rsi=bytes do bloco original
; -----------------------------------------------------------------------------
k_free_bytes:
        push rsi
        add rsi, 4095
        shr rsi, 12
        call k_free_n
        pop rsi
        ret

; -----------------------------------------------------------------------------
; k_free_pages_count -> rax = páginas livres
; -----------------------------------------------------------------------------
k_free_pages_count:
        mov rcx, [heap_pages]
        xor rdx, rdx
        mov r11, [bitmap_pages]
.loop:
        cmp r11, rcx
        jae .done
        mov rax, r11
        call page_is_free
        add rdx, rax
        inc r11
        jmp .loop
.done:
        mov rax, rdx
        ret

section .kdata
sw_retry:   dd 0
section .kdata
s_ka_start: db "[ka] varrendo npages:", 0
s_ka_ok:    db "[ka] alocou em:", 0
s_ka_fail:  db "[ka] FALHOU heap/bitmap pages:", 0
ram_total2: dq 0

ram_total:     dq 0
heap_top:      dq 0
heap_pages:    dq 0
bitmap_bytes:  dq 0
bitmap_pages:  dq 0


section .kdata
s_mm_e820:   db "[mm] e820 somado", 0
s_mm_bitmap: db "[mm] bitmap pronto", 0
s_mm_end:    db "[mm] reservas ok — mm_init completo", 0

%endif
