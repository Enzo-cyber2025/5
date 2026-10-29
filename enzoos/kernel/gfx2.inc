; =============================================================================
;  EnzoOS — kernel/gfx2.inc: nova camada de renderização
;
;  Primitivas sobre a superfície ativa (gsurf_*):
;    * alpha blending por pixel (0xAARRGGBB)
;    * preenchimento com gradiente vertical
;    * retângulos com cantos arredondados (sólidos e translúcidos)
;    * sombras suaves para janelas
;    * linhas anti-aliased (algoritmo de Xiaolin Wu)
;    * círculos preenchidos
;    * blit de janela com cantos arredondados
;
;  Convenção interna: estado dos laços em rbx/rbp/r12-r15 (preservados);
;  qualquer chamada pode clobberar rax, rcx, rdx, r8-r11.
; =============================================================================
%ifndef GFX2_INC
%define GFX2_INC

section .ktext

; -----------------------------------------------------------------------------
; g2_blend_px: edi=x, esi=y, edx=cor 0xAARRGGBB
; -----------------------------------------------------------------------------
g2_blend_px:
        cmp edi, 0
        jl .no
        cmp esi, 0
        jl .no
        cmp edi, [gsurf_w]
        jge .no
        cmp esi, [gsurf_h]
        jge .no
        mov eax, edx
        shr eax, 24                 ; alpha
        test eax, eax
        jz .no
        cmp eax, 255
        jae .solid
        mov eax, esi
        imul eax, [gsurf_stride]
        mov ecx, edi
        shl ecx, 2
        add eax, ecx
        mov r8, [gsurf_ptr]
        add r8, rax
        mov eax, edx                ; fonte
        and eax, 0x00FFFFFF
        mov ecx, [r8]               ; destino
        and ecx, 0x00FFFFFF
        mov r9d, eax
        sub r9d, ecx                ; src - dst
        mov r10d, edx
        shr r10d, 24
        imul r9d, r10d
        sar r9d, 8
        add ecx, r9d
        and ecx, 0x00FFFFFF
        mov [r8], ecx
.no:
        ret
.solid:
        mov eax, esi
        imul eax, [gsurf_stride]
        mov ecx, edi
        shl ecx, 2
        add eax, ecx
        mov r8, [gsurf_ptr]
        add r8, rax
        mov eax, edx
        and eax, 0x00FFFFFF
        mov [r8], eax
        ret

; -----------------------------------------------------------------------------
; g2_blend_fill: edi=x, esi=y, edx=w, ecx=h, r8d=cor 0xAARRGGBB
; -----------------------------------------------------------------------------
g2_blend_fill:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; x
        mov r13d, esi               ; y
        mov r14d, edx               ; w
        mov r15d, ecx               ; h
        mov ebx, r8d                ; cor
        cmp r12d, 0
        jge .x1
        add r14d, r12d
        xor r12d, r12d
.x1:
        cmp r13d, 0
        jge .y1
        add r15d, r13d
        xor r13d, r13d
.y1:
        mov eax, r12d
        add eax, r14d
        cmp eax, [gsurf_w]
        jbe .x2
        mov r14d, [gsurf_w]
        sub r14d, r12d
.x2:
        mov eax, r13d
        add eax, r15d
        cmp eax, [gsurf_h]
        jbe .y2
        mov r15d, [gsurf_h]
        sub r15d, r13d
.y2:
        cmp r14d, 0
        jle .done
        cmp r15d, 0
        jle .done
        mov ebp, ebx
        shr ebp, 24                 ; alpha
        cmp ebp, 255
        jae .opaque
        mov r10d, ebp
.row:
        xor ecx, ecx
.col:
        cmp ecx, r14d
        jae .row_end
        mov eax, r13d
        imul eax, [gsurf_stride]
        mov edx, r12d
        add edx, ecx
        shl edx, 2
        add eax, edx
        mov r8, [gsurf_ptr]
        add r8, rax
        mov eax, ebx
        and eax, 0x00FFFFFF
        mov edx, [r8]
        and edx, 0x00FFFFFF
        mov r9d, eax
        sub r9d, edx
        imul r9d, r10d
        sar r9d, 8
        add edx, r9d
        and edx, 0x00FFFFFF
        mov [r8], edx
        inc ecx
        jmp .col
.row_end:
        inc r13d
        dec r15d
        jnz .row
        jmp .done
.opaque:
        mov edi, r12d
        mov esi, r13d
        mov edx, r14d
        mov ecx, r15d
        mov r14d, ebx
        and r14d, 0x00FFFFFF
        call surf_fill
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; -----------------------------------------------------------------------------
; g2_grad: edi=x, esi=y, edx=w, ecx=h, r8d=cor0, r9d=cor1 (vertical)
; -----------------------------------------------------------------------------
g2_grad:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; x
        mov r13d, esi               ; y
        mov r14d, edx               ; w
        mov r15d, ecx               ; h
        mov ebp, r8d                ; c0
        mov ebx, r9d                ; c1
        test r15d, r15d
        jle .done
        xor r11d, r11d              ; linha (ecx é parâmetro h do surf_fill)
.row:
        cmp r11d, r15d
        jae .done
        ; t = linha * 256 / h
        mov eax, r11d
        shl eax, 8
        xor edx, edx
        div r15d
        ; canal r
        mov r8d, ebx
        shr r8d, 16
        and r8d, 0xFF
        mov r9d, ebp
        shr r9d, 16
        and r9d, 0xFF
        sub r8d, r9d
        imul r8d, eax
        add r8d, 128
        sar r8d, 8
        add r8d, r9d                ; r
        ; canal g
        mov r9d, ebx
        shr r9d, 8
        and r9d, 0xFF
        mov r10d, ebp
        shr r10d, 8
        and r10d, 0xFF
        sub r9d, r10d
        imul r9d, eax
        add r9d, 128
        sar r9d, 8
        add r9d, r10d
        shl r9d, 8
        or r8d, r9d                 ; g
        ; canal b
        mov r9d, ebx
        and r9d, 0xFF
        mov r10d, ebp
        and r10d, 0xFF
        sub r9d, r10d
        imul r9d, eax
        add r9d, 128
        sar r9d, 8
        add r9d, r10d
        or r8d, r9d                 ; b
        ; desenha a linha
        mov edi, r12d
        mov esi, r13d
        add esi, r11d
        mov edx, r14d
        mov ecx, 1
        push r14
        mov r14d, r8d
        call surf_fill
        pop r14
        inc r11d
        jmp .row
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; -----------------------------------------------------------------------------
; g2_round_blend: edi=x, esi=y, edx=w, ecx=h, r8d=raio, r9d=cor 0xAARRGGBB
; -----------------------------------------------------------------------------
g2_round_blend:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; x
        mov r13d, esi               ; y
        mov r14d, edx               ; w
        mov r15d, ecx               ; h
        mov ebx, r8d                ; raio
        mov ebp, r9d                ; cor
        cmp ebx, 16
        jbe .rok
        mov ebx, 16
.rok:
        xor r11d, r11d              ; linha (ecx é parâmetro h do g2_blend_fill)
.row:
        cmp r11d, r15d
        jae .done
        ; recuo nas linhas dos cantos
        xor edx, edx
        cmp r11d, ebx
        jae .bot
        mov eax, r11d
        call g2_inset
        mov edx, eax
        jmp .have
.bot:
        mov eax, r15d
        sub eax, ebx
        cmp r11d, eax
        jb .have
        mov eax, r15d
        dec eax
        sub eax, r11d
        call g2_inset
        mov edx, eax
.have:
        test edx, edx
        jz .full
        mov edi, r12d
        add edi, edx
        mov esi, r13d
        add esi, r11d
        mov eax, r14d
        sub eax, edx
        sub eax, edx
        mov edx, eax
        mov ecx, 1
        mov r8d, ebp
        call g2_blend_fill
        jmp .row_end
.full:
        mov edi, r12d
        mov esi, r13d
        add esi, r11d
        mov edx, r14d
        mov ecx, 1
        mov r8d, ebp
        call g2_blend_fill
.row_end:
        inc r11d
        jmp .row
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; g2_inset: eax = distância vertical da borda, ebx = raio -> eax = recuo
;           (preserva tudo, exceto eax)
g2_inset:
        push rcx
        push rdx
        push r8
        cmp eax, ebx
        jae .zero
        mov edx, ebx
        sub edx, eax                ; distância do centro do canto
        mov ecx, ebx
        imul ecx, ecx               ; r^2
        mov r8d, edx
        imul r8d, r8d               ; d^2
        sub ecx, r8d
        jns .sq
.zero:
        xor eax, eax
        pop r8
        pop rdx
        pop rcx
        ret
.sq:
        xor eax, eax
        mov r8d, 1
.l:
        cmp r8d, ecx
        jg .d
        sub ecx, r8d
        add r8d, 2
        inc eax
        jmp .l
.d:
        mov ecx, ebx
        sub ecx, eax
        mov eax, ecx
        cmp eax, 0
        jge .ok
        xor eax, eax
.ok:
        pop r8
        pop rdx
        pop rcx
        ret

; -----------------------------------------------------------------------------
; g2_round: edi=x, esi=y, edx=w, ecx=h, r8d=raio, r9d=cor RGB (opaco)
; -----------------------------------------------------------------------------
g2_round:
        or r9d, 0xFF000000
        jmp g2_round_blend

; -----------------------------------------------------------------------------
; g2_wu_line: edi=x0, esi=y0, edx=x1, ecx=y1, r8d=cor RGB
; -----------------------------------------------------------------------------
g2_wu_line:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; x0
        mov r13d, esi               ; y0
        mov r14d, edx               ; x1
        mov r15d, ecx               ; y1
        mov ebx, r8d                ; cor
        ; |dx|, |dy|
        mov eax, r14d
        sub eax, r12d
        mov ecx, eax
        test ecx, ecx
        jns .dxp
        neg ecx
.dxp:
        mov eax, r15d
        sub eax, r13d
        mov edx, eax
        test edx, edx
        jns .dyp
        neg edx
.dyp:
        cmp ecx, edx
        jae .horiz
        ; ---------- linha vertical ----------
        cmp r13d, r15d
        jle .vord
        xchg r12d, r14d
        xchg r13d, r15d
.vord:
        mov eax, r14d
        sub eax, r12d
        mov ecx, r15d
        sub ecx, r13d
        imul eax, 256
        cdq
        idiv ecx
        mov ebp, eax                ; gradiente (fixo 8 bits)
        mov r11d, r12d
        shl r11d, 8                 ; acumulador
        mov esi, r13d
.vloop:
        cmp esi, r15d
        ja .done
        mov r10d, r11d
        shr r10d, 8                 ; x inteiro
        mov eax, r11d
        and eax, 0xFF               ; fração
        ; pixel principal (alpha = 255 - frac)
        mov edi, r10d
        mov edx, ebx
        mov r8d, 255
        sub r8d, eax
        shl r8d, 24
        or edx, r8d
        call g2_blend_px
        ; pixel secundário
        mov eax, r11d
        and eax, 0xFF
        test eax, eax
        jz .vnext
        mov edi, r10d
        inc edi
        mov edx, ebx
        mov r8d, eax
        shl r8d, 24
        or edx, r8d
        call g2_blend_px
.vnext:
        add r11d, ebp
        inc esi
        jmp .vloop
.horiz:
        ; ---------- linha horizontal ----------
        cmp r12d, r14d
        jle .hord
        xchg r12d, r14d
        xchg r13d, r15d
.hord:
        mov eax, r15d
        sub eax, r13d
        mov ecx, r14d
        sub ecx, r12d
        jz .done
        imul eax, 256
        cdq
        idiv ecx
        mov ebp, eax
        mov r11d, r13d
        shl r11d, 8
        mov edi, r12d
.hloop:
        cmp edi, r14d
        ja .done
        mov r10d, r11d
        shr r10d, 8                 ; y inteiro
        mov eax, r11d
        and eax, 0xFF               ; fração
        mov esi, r10d
        mov edx, ebx
        mov r8d, 255
        sub r8d, eax
        shl r8d, 24
        or edx, r8d
        call g2_blend_px
        mov eax, r11d
        and eax, 0xFF
        test eax, eax
        jz .hnext
        mov esi, r10d
        inc esi
        mov edx, ebx
        mov r8d, eax
        shl r8d, 24
        or edx, r8d
        call g2_blend_px
.hnext:
        add r11d, ebp
        inc edi
        jmp .hloop
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; -----------------------------------------------------------------------------
; g2_circle: edi=cx, esi=cy, edx=raio, ecx=cor RGB (preenchido)
; -----------------------------------------------------------------------------
g2_circle:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; cx
        mov r13d, esi               ; cy
        mov r14d, edx               ; raio
        mov r15d, ecx               ; cor
        test r14d, r14d
        jle .done
        xor ebx, ebx                ; dy
.loop:
        mov eax, r14d
        cmp ebx, eax
        jg .done
        ; dx = raiz(r^2 - dy^2)
        imul eax, eax
        mov ecx, ebx
        imul ecx, ecx
        sub eax, ecx
        jns .sq
        xor r10d, r10d
        jmp .draw
.sq:
        mov ecx, eax
        xor eax, eax
        mov r8d, 1
.sql:
        cmp r8d, ecx
        jg .sqd
        sub ecx, r8d
        add r8d, 2
        inc eax
        jmp .sql
.sqd:
        mov r10d, eax               ; dx
.draw:
        ; linha inferior
        mov edi, r12d
        sub edi, r10d
        mov esi, r13d
        add esi, ebx
        mov edx, r10d
        add edx, r10d
        inc edx
        mov ecx, 1
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r14d, r15d
        call surf_fill
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        test ebx, ebx
        jz .next
        ; linha superior
        mov edi, r12d
        sub edi, r10d
        mov esi, r13d
        sub esi, ebx
        mov edx, r10d
        add edx, r10d
        inc edx
        mov ecx, 1
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r14d, r15d
        call surf_fill
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
.next:
        inc ebx
        jmp .loop
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; -----------------------------------------------------------------------------
; g2_shadow: edi=x, esi=y, edx=w, ecx=h — sombra suave sob uma janela
; -----------------------------------------------------------------------------
g2_shadow:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        mov r13d, esi
        mov r14d, edx
        mov r15d, ecx
        mov ebx, 5
.ring:
        test ebx, ebx
        jz .done
        mov edi, r12d
        sub edi, ebx
        mov esi, r13d
        add esi, 4                  ; sombra desloca para baixo
        mov edx, r14d
        add edx, ebx
        add edx, ebx
        mov ecx, r15d
        add ecx, ebx
        add ecx, ebx
        mov r8d, 16
        mov r9d, 0x1E0A0E1A
        call g2_round_blend
        dec ebx
        jmp .ring
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; -----------------------------------------------------------------------------
; g2_win_blit: edi=x, esi=y, edx=w, ecx=h, r8=fonte, r9d=passo da fonte
;              blit com cantos arredondados (raio 10)
; -----------------------------------------------------------------------------
g2_win_blit:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi               ; x dst
        mov r13d, esi               ; y dst
        mov r14d, edx               ; w
        mov r15d, ecx               ; h
        mov rbx, r8                 ; fonte
        mov ebp, r9d                ; passo
        xor ecx, ecx
.row:
        cmp ecx, r15d
        jae .done
        xor edx, edx
        cmp ecx, 10
        jae .bot
        movzx edx, byte [g2_rtab + rcx]
        jmp .have
.bot:
        mov eax, r15d
        sub eax, 10
        cmp ecx, eax
        jb .have
        mov eax, r15d
        dec eax
        sub eax, ecx
        movzx edx, byte [g2_rtab + rax]
.have:
        mov eax, r14d
        sub eax, edx
        sub eax, edx
        cmp eax, 0
        jle .row_end
        ; destino
        mov rdi, [gsurf_ptr]
        mov r9d, ecx
        add r9d, r13d
        imul r9d, [gsurf_stride]
        mov r10d, r12d
        add r10d, edx
        shl r10d, 2
        add r9d, r10d
        add rdi, r9
        ; origem
        mov rsi, rbx
        mov r9d, ecx
        imul r9d, ebp
        add rsi, r9
        mov r9d, edx
        shl r9d, 2
        add rsi, r9
        ; comprimento
        mov rdx, rax
        shl rdx, 2
        push rcx
        call k_memcpy
        pop rcx
.row_end:
        inc ecx
        jmp .row
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

section .kdata
g2_rtab: db 10, 6, 4, 3, 2, 2, 1, 1, 1, 1

%endif
