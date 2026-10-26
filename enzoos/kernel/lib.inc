; =============================================================================
;  EnzoOS — kernel/lib.inc: rotinas básicas (memória, strings, números)
;  Cópia/preenchimento em SSE2 de 128 bits — garantido no x86-64 e ideal para
;  o Pentium Silver N5030 (Gemini Lake não possui AVX; SSE2 é o ponto ideal).
; =============================================================================
%ifndef LIB_INC
%define LIB_INC

section .ktext

; -----------------------------------------------------------------------------
; k_memcpy — rdi=destino, rsi=origem, rdx=bytes
; -----------------------------------------------------------------------------
k_memcpy:
        mov rcx, rdx
        test rcx, rcx
        jz .done
        cld
        cmp rcx, 32
        jb .bytes
        ; alinha o destino em 16 bytes
        mov rax, rdi
        and al, 15
        jz .sse
        mov r9, 16
        sub r9, rax
        sub rcx, r9
.head:
        movsb
        dec r9
        jnz .head
.sse:
        mov rdx, rcx
        and rcx, -16
        shr rcx, 4
        jz .tail
.sseloop:
        movdqu xmm0, [rsi]
        movdqu [rdi], xmm0
        add rsi, 16
        add rdi, 16
        dec rcx
        jnz .sseloop
.tail:
        mov rcx, rdx
        and rcx, 15
.bytes:
        rep movsb
.done:
        ret

; -----------------------------------------------------------------------------
; k_memset32 — rdi=destino, rsi=qtd de dwords, edx=valor
; -----------------------------------------------------------------------------
k_memset32:
        test rsi, rsi
        jz .done
        movd xmm0, edx
        pshufd xmm0, xmm0, 0
        mov rcx, rsi
        shr rcx, 5
        jz .mid
.loop:
        movdqu [rdi],    xmm0
        movdqu [rdi+16], xmm0
        movdqu [rdi+32], xmm0
        movdqu [rdi+48], xmm0
        movdqu [rdi+64], xmm0
        movdqu [rdi+80], xmm0
        movdqu [rdi+96], xmm0
        movdqu [rdi+112], xmm0
        add rdi, 128
        dec rcx
        jnz .loop
.mid:
        mov rcx, rsi
        and rcx, 31
        shr rcx, 2
        jz .tail
.loop16:
        movdqu [rdi], xmm0
        add rdi, 16
        dec rcx
        jnz .loop16
.tail:
        mov rcx, rsi
        and rcx, 3
        jz .done
.loop4:
        mov [rdi], edx
        add rdi, 4
        dec rcx
        jnz .loop4
.done:
        ret

; -----------------------------------------------------------------------------
; k_memzero — rdi=destino, rsi=bytes
; -----------------------------------------------------------------------------
k_memzero:
        push rdi
        push rsi
        push rdx
        mov rax, rsi
        add rax, 3
        shr rax, 2
        mov rsi, rax
        xor edx, edx
        call k_memset32
        pop rdx
        pop rsi
        pop rdi
        ret

; -----------------------------------------------------------------------------
; k_strlen — rdi=str -> rax=len (máx 4096)
; -----------------------------------------------------------------------------
k_strlen:
        xor rax, rax
.loop:
        cmp byte [rdi + rax], 0
        je .done
        inc rax
        cmp rax, 4096
        jb .loop
.done:
        ret

; -----------------------------------------------------------------------------
; k_strcmp — rdi, rsi -> rax=0 se iguais
; -----------------------------------------------------------------------------
k_strcmp:
        xor rcx, rcx
.loop:
        mov al, [rdi + rcx]
        cmp al, [rsi + rcx]
        jne .diff
        test al, al
        jz .same
        inc rcx
        jmp .loop
.same:
        xor rax, rax
        ret
.diff:
        movzx eax, byte [rdi + rcx]
        movzx edx, byte [rsi + rcx]
        sub rax, rdx
        ret

; -----------------------------------------------------------------------------
; k_strcasecmp — rdi, rsi -> rax=0 se iguais (ASCII, caixa ignorada)
; -----------------------------------------------------------------------------
k_strcasecmp:
        xor rcx, rcx
.loop:
        mov al, [rdi + rcx]
        mov dl, [rsi + rcx]
        cmp al, 'a'
        jb .ok1
        cmp al, 'z'
        ja .ok1
        sub al, 32
.ok1:
        cmp dl, 'a'
        jb .ok2
        cmp dl, 'z'
        ja .ok2
        sub dl, 32
.ok2:
        cmp al, dl
        jne .diff
        test al, al
        jz .same
        inc rcx
        jmp .loop
.same:
        xor rax, rax
        ret
.diff:
        movzx eax, al
        movzx edx, dl
        sub rax, rdx
        ret

; -----------------------------------------------------------------------------
; k_strcpy — rdi=dest, rsi=origem -> rax=dest
; -----------------------------------------------------------------------------
k_strcpy:
        mov rax, rdi
.loop:
        mov dl, [rsi]
        mov [rdi], dl
        test dl, dl
        jz .done
        inc rsi
        inc rdi
        jmp .loop
.done:
        ret

; -----------------------------------------------------------------------------
; k_upper — rdi=str: converte para maiúsculas in-place
; -----------------------------------------------------------------------------
k_upper:
        push rbx
        mov rbx, rdi
.loop:
        mov al, [rbx]
        test al, al
        jz .done
        cmp al, 'a'
        jb .next
        cmp al, 'z'
        ja .next
        sub al, 32
        mov [rbx], al
.next:
        inc rbx
        jmp .loop
.done:
        pop rbx
        ret

; -----------------------------------------------------------------------------
; k_utoa — rdi=valor, rsi=buffer, rdx=base -> rax=comprimento
; -----------------------------------------------------------------------------
k_utoa:
        push rbx
        push r12
        push r13
        mov r12, rsi
        mov r13, rdx
        lea rbx, [rel .digits]
        mov rax, rdi
        xor rcx, rcx
.conv:
        xor edx, edx
        div r13
        mov r9, rax                     ; quociente
        mov al, [rbx + rdx]             ; dígito
        push rax
        inc rcx
        mov rax, r9
        test rax, rax
        jnz .conv
        mov r13, rcx
.pop:
        pop rax
        mov [r12], al
        inc r12
        dec rcx
        jnz .pop
        mov rax, r13
        pop r13
        pop r12
        pop rbx
        ret
.digits: db "0123456789ABCDEF"

; -----------------------------------------------------------------------------
; k_utf8_next — rdi=ptr -> rax=codepoint (Latin-1 ou '?'), rdx=bytes consumidos
; Nas strings NASM os acentos vêm em UTF-8; a fonte é indexada em Latin-1.
; -----------------------------------------------------------------------------
k_utf8_next:
        movzx eax, byte [rdi]
        test al, al
        jz .end
        cmp al, 0x80
        jb .ascii
        cmp al, 0xC2
        jb .quest
        cmp al, 0xC5
        ja .quest
        ; sequência de 2 bytes: U+0080..U+07FF (usamos só até U+00FF)
        movzx edx, byte [rdi+1]
        and edx, 0x3F
        and eax, 0x1F
        shl eax, 6
        or eax, edx
        cmp eax, 0xFF
        ja .quest2
        mov rdx, 2
        ret
.quest2:
        mov rdx, 2
.quest:
        mov eax, '?'
        ret
.ascii:
        mov rdx, 1
        ret
.end:
        xor eax, eax
        xor edx, edx
        ret

%endif
