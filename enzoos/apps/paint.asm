; =============================================================================
;  EnzoOS — apps/paint.asm: PAINT.CE — pintura livre com paleta de cores.
;  Botão esquerdo desenha; clique na paleta troca a cor; C limpa.
; =============================================================================
BITS 64
org 0
default rel

%define CVW   320
%define CVH   224

header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 360, 300
        dd 0
        db "Pintura", 0
        times 64-($-header) db 0

app_entry:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        mov r13, rsi
        mov eax, [rsi]
        cmp eax, 1
        je ev_init
        cmp eax, 2
        je ev_paint
        cmp eax, 3
        je ev_mouse
        cmp eax, 4
        je ev_key
        jmp epilogue
epilogue:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        ; aloca o canvas
        mov edi, CVW*CVH*4
        mov rax, [r12 + 8*13]
        call rax
        mov [canvas], rax
        ; zera
        mov rdi, rax
        mov ecx, CVW*CVH
.z:
        mov dword [rdi], 0xFF10151F
        add rdi, 4
        dec ecx
        jnz .z
        mov dword [color], 0x10A372
        mov dword [lastx], -1
        mov dword [lasty], -1
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

ev_key:
        mov eax, [r13+16]
        cmp eax, 'c'
        jne .done
        ; limpa
        mov rdi, [canvas]
        test rdi, rdi
        jz .done
        mov ecx, CVW*CVH
.z:
        mov dword [rdi], 0xFF10151F
        add rdi, 4
        dec ecx
        jnz .z
        call invalidate
.done:
        jmp epilogue

ev_mouse:
        ; a=x, b=y, c=botões, d=press
        mov ebx, [r13+16]               ; x
        mov ebp, [r13+24]               ; y
        mov r14d, [r13+32]              ; botões
        ; dentro da paleta?
        cmp ebp, 0
        jl .out
        cmp ebp, 20
        jge .not_pal
        xor ecx, ecx
.pal:
        cmp ecx, 8
        jae .out
        mov eax, ecx
        imul eax, 28
        add eax, 4
        cmp ebx, eax
        jl .out
        add eax, 24
        cmp ebx, eax
        jge .nextc
        ; cor = pal[ecx]
        lea rax, [palette]
        mov eax, [rax + rcx*4]
        mov [color], eax
        call invalidate
        jmp epilogue
.nextc:
        inc ecx
        jmp .pal
.not_pal:
        ; dentro do canvas?
        cmp ebp, 26
        jl .out
        sub ebp, 26
        cmp ebp, CVH
        jge .out
        cmp ebx, 4
        jl .out
        sub ebx, 4
        cmp ebx, CVW
        jge .out
        ; desenha se botão pressionado
        test r14d, 1
        jz .up
        mov edi, ebx
        mov esi, ebp
        call draw_px3
        call invalidate
        jmp .out
.up:
        mov dword [lastx], -1
.out:
        jmp epilogue

draw_px3:                         ; edi=x, esi=y — liga ao ponto anterior
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov ebx, edi                   ; x1
        mov ebp, esi                   ; y1
        mov r12d, [lastx]              ; x0
        mov r13d, [lasty]              ; y0
        cmp r12d, -1
        je .plot
        mov r14d, 1                    ; sx
        mov r15d, 1                    ; sy
        mov eax, ebx
        sub eax, r12d
        test eax, eax
        jns .dxok
        neg eax
        mov r14d, -1
.dxok:
        mov [gdx], eax
        mov eax, ebp
        sub eax, r13d
        test eax, eax
        jns .dyok
        neg eax
        mov r15d, -1
.dyok:
        mov [gdy], eax
        mov eax, [gdx]
        sub eax, [gdy]
        mov [gerr], eax
.step:
        mov edi, r12d
        mov esi, r13d
        call plot3
        cmp r12d, ebx
        jne .cont
        cmp r13d, ebp
        je .plot
.cont:
        mov eax, [gerr]
        add eax, eax                   ; e2
        mov ecx, [gdy]
        neg ecx
        cmp eax, ecx
        jl .no_x
        mov edx, [gdy]
        sub [gerr], edx
        add r12d, r14d
.no_x:
        cmp eax, [gdx]
        jg .no_y
        mov edx, [gdx]
        add [gerr], edx
        add r13d, r15d
.no_y:
        jmp .step
.plot:
        mov edi, ebx
        mov esi, ebp
        call plot3
        mov [lastx], ebx
        mov [lasty], ebp
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; plot3: edi=x, esi=y — quadrado 3x3
plot3:
        cmp edi, 0
        jl .no
        cmp esi, 0
        jl .no
        cmp edi, CVW
        jge .no
        cmp esi, CVH
        jge .no
        mov ecx, esi
        imul ecx, CVW
        add ecx, edi
        shl ecx, 2
        add rcx, [canvas]
        mov eax, [color]
        mov [rcx], eax
        ; vizinhos (clip simples)
        cmp edi, CVW-1
        jge .no2
        mov [rcx+4], eax
.no2:
        cmp esi, CVH-1
        jge .no3
        mov [rcx + CVW*4], eax
.no3:
.no:
        ret

render:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x101726
        mov rax, [r12 + 8*1]
        call rax
        ; paleta
        xor ebx, ebx
.pl:
        cmp ebx, 8
        jae .pl_done
        mov edi, ebx
        imul edi, 28
        add edi, 4
        xor esi, esi
        mov edx, 24
        mov ecx, 18
        lea rax, [palette]
        mov r8d, [rax + rbx*4]
        mov rax, [r12 + 8*1]
        call rax
        inc ebx
        jmp .pl
.pl_done:
        ; canvas
        mov edi, 4
        mov esi, 26
        mov edx, CVW
        mov ecx, CVH
        mov r8, [canvas]
        mov r9d, CVW*4
        mov rax, [r12 + 8*3]
        call rax
        pop rbx
        ret

invalidate:
        mov rax, [r12 + 8*12]
        jmp rax

palette: dd 0x10A372, 0x2D9CDB, 0xE05555, 0xE8C558, 0xF2F5FA, 0xE055FF, 0x56C8D8, 0x8FA0B8

tw_: dd 360
th_: dd 300
color: dd 0x10A372
lastx: dd -1
lasty: dd -1
canvas: dq 0
gdx:  dd 0
gdy:  dd 0
gerr: dd 0

image_end:
