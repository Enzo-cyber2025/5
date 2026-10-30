; =============================================================================
;  EnzoOS — kernel/inflate.inc: descompressor DEFLATE (RFC 1951), estilo
;  "puff" — leitura LSB-first de bits e Huffman canônico.
; =============================================================================
%ifndef INFLATE_INC
%define INFLATE_INC

section .ktext

; -----------------------------------------------------------------------------
; inf_take: ecx=n bits (1..25) -> eax (LSB-first)
; -----------------------------------------------------------------------------
inf_take:
        push rbx
        mov ebx, ecx
.fill:
        mov eax, [inf_bitcnt]
        cmp eax, ebx
        jae .ready
        mov rdx, [inf_src]
        movzx eax, byte [rdx]
        inc qword [inf_src]
        push rcx
        mov ecx, [inf_bitcnt]
        shl rax, cl
        pop rcx
        or [inf_bitbuf], rax
        add dword [inf_bitcnt], 8
        jmp .fill
.ready:
        mov rdx, [inf_bitbuf]
        mov rax, 1
        push rcx
        mov rcx, rbx
        shl rax, cl
        pop rcx
        dec rax                        ; máscara (1<<n)-1
        and rax, rdx
        mov rdx, [inf_bitbuf]
        push rcx
        mov rcx, rbx
        shr rdx, cl
        pop rcx
        mov [inf_bitbuf], rdx
        sub [inf_bitcnt], ebx
        pop rbx
        ret

; -----------------------------------------------------------------------------
; inf_decode: rdi = huff (count[16] + symbol[]) -> rax = símbolo ou -1
; -----------------------------------------------------------------------------
inf_decode:
        xor r8d, r8d                   ; code
        xor r9d, r9d                   ; first
        xor r10d, r10d                 ; index
        mov r11d, 1                    ; len
.lenloop:
        cmp r11d, 15
        ja .bad
        mov ecx, 1
        call inf_take
        or r8d, eax                    ; code |= bit
        mov eax, [rdi + r11*4]         ; count[len]
        mov ecx, r8d
        sub ecx, r9d                   ; code - first
        cmp ecx, eax
        jae .nextlen
        add ecx, r10d
        mov eax, [rdi + 64 + rcx*4]
        ret
.nextlen:
        add r10d, eax
        add r9d, eax
        shl r9d, 1
        shl r8d, 1
        inc r11d
        jmp .lenloop
.bad:
        mov eax, -1
        ret

; -----------------------------------------------------------------------------
; inf_build: rdi=lens(dwords), rsi=nsym, rdx=huff -> rax=0/-2
; -----------------------------------------------------------------------------
inf_build:
        push rbx
        push r12
        push r13
        push r14
        sub rsp, 80
        mov r12, rdi
        mov r13, rsi
        mov r14, rdx
        xor ecx, ecx
.zc:
        mov dword [r14 + rcx*4], 0
        inc ecx
        cmp ecx, 16
        jb .zc
        xor ecx, ecx
.cnt:
        cmp ecx, r13d
        jae .cd
        mov eax, [r12 + rcx*4]
        cmp eax, 15
        ja .err
        inc dword [r14 + rax*4]
        inc ecx
        jmp .cnt
.cd:
        mov dword [r14], 0
        mov dword [rsp + 4], 0
        mov ecx, 1
.of:
        mov eax, [rsp + rcx*4]
        add eax, [r14 + rcx*4]
        mov [rsp + rcx*4 + 4], eax
        inc ecx
        cmp ecx, 16
        jb .of
        xor ecx, ecx
.sym:
        cmp ecx, r13d
        jae .done
        mov eax, [r12 + rcx*4]
        test eax, eax
        jz .nextsym
        mov ebx, [rsp + rax*4]
        mov [r14 + 64 + rbx*4], ecx
        inc dword [rsp + rax*4]
.nextsym:
        inc ecx
        jmp .sym
.done:
        xor rax, rax
        jmp .out
.err:
        mov rax, -2
.out:
        add rsp, 80
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; inf_codes: decodifica símbolos até EOB (r13=nlen não usado aqui)
; -----------------------------------------------------------------------------
inf_codes:
        push rbx
.lit:
        lea rdi, [huff_lit]
        call inf_decode
        cmp eax, 256
        jb .literal
        je .endblk
        cmp eax, 286
        jae .bad
        sub eax, 257
        mov ecx, eax
        mov edx, [len_base + rcx*4]
        mov r8d, [len_extra + rcx*4]
        test r8d, r8d
        jz .nolen
        push rdx
        mov ecx, r8d
        call inf_take
        pop rdx
        add eax, edx
.nolen:
        mov r9d, eax
        lea rdi, [huff_dist]
        call inf_decode
        cmp eax, 30
        jae .bad
        mov ecx, eax
        mov edx, [dist_base + rcx*4]
        mov r8d, [dist_extra + rcx*4]
        test r8d, r8d
        jz .nodist
        push rdx
        mov ecx, r8d
        call inf_take
        pop rdx
        add eax, edx
.nodist:
        mov r10d, eax
        mov eax, r9d
        cmp eax, [inf_room]
        ja .room_bad
        mov rbx, [inf_dst]
        mov rcx, r9
        mov rsi, rbx
        sub rsi, r10
        mov rdi, rbx
.cp:
        mov al, [rsi]
        mov [rdi], al
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
        mov [inf_dst], rdi
        sub [inf_room], r9d
        jmp .lit
.literal:
        cmp dword [inf_room], 0
        je .room_bad
        mov rbx, [inf_dst]
        mov [rbx], al
        inc qword [inf_dst]
        dec dword [inf_room]
        jmp .lit
.endblk:
        clc
        pop rbx
        ret
.bad:
.room_bad:
        stc
        pop rbx
        ret

; -----------------------------------------------------------------------------
; inflate: rdi=src (dados DEFLATE), rsi=dst, edx=capacidade -> rax=0/erro
; -----------------------------------------------------------------------------
inflate:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov [inf_src], rdi
        mov [inf_dst], rsi
        mov qword [inf_bitbuf], 0
        mov dword [inf_bitcnt], 0
        mov [inf_room], edx
.block:
        mov ecx, 1
        call inf_take
        mov r12d, eax                  ; BFINAL
        mov ecx, 2
        call inf_take
        cmp eax, 0
        je .stored
        cmp eax, 1
        je .fixed
        cmp eax, 2
        je .dynamic
        mov rax, -3
        jmp .out
.stored:
        mov dword [inf_bitcnt], 0
        mov qword [inf_bitbuf], 0
        mov r8, [inf_src]
        movzx r13d, word [r8]
        movzx eax, word [r8+2]
        mov ecx, r13d
        not ecx
        and ecx, 0xFFFF
        cmp eax, ecx
        jne .bad_stored
        add qword [inf_src], 4
        mov eax, r13d
        cmp eax, [inf_room]
        ja .bad_room
        mov rdi, [inf_dst]
        mov rsi, [inf_src]
        mov rdx, r13
        call k_memcpy
        add [inf_src], r13
        add [inf_dst], r13
        sub [inf_room], r13d
        jmp .nextblk
.fixed:
        xor ecx, ecx
.fl1:
        cmp ecx, 144
        jae .fl2
        mov dword [lens_lit + rcx*4], 8
        inc ecx
        jmp .fl1
.fl2:
        cmp ecx, 256
        jae .fl3
        mov dword [lens_lit + rcx*4], 9
        inc ecx
        jmp .fl2
.fl3:
        cmp ecx, 280
        jae .fl4
        mov dword [lens_lit + rcx*4], 7
        inc ecx
        jmp .fl3
.fl4:
        cmp ecx, 288
        jae .fl5
        mov dword [lens_lit + rcx*4], 8
        inc ecx
        jmp .fl4
.fl5:
        xor ecx, ecx
.fd:
        cmp ecx, 30
        jae .fdone
        mov dword [lens_dist + rcx*4], 5
        inc ecx
        jmp .fd
.fdone:
        lea rdi, [lens_lit]
        mov rsi, 288
        lea rdx, [huff_lit]
        call inf_build
        lea rdi, [lens_dist]
        mov rsi, 30
        lea rdx, [huff_dist]
        call inf_build
        call inf_codes
        jc .bad_huff
        jmp .nextblk
.dynamic:
        mov ecx, 5
        call inf_take
        add eax, 257
        mov r13d, eax                  ; nlen
        mov ecx, 5
        call inf_take
        add eax, 1
        mov r14d, eax                  ; ndist
        mov ecx, 4
        call inf_take
        add eax, 4
        mov r15d, eax                  ; ncode
        xor ecx, ecx
.zclc:
        mov dword [lens_clc + rcx*4], 0
        inc ecx
        cmp ecx, 19
        jb .zclc
        xor ebx, ebx
.clcr:
        cmp ebx, r15d
        jae .clcr_done
        mov ecx, 3
        call inf_take
        mov ecx, ebx
        mov edx, [clc_order + rcx*4]
        mov [lens_clc + rdx*4], eax
        inc ebx
        jmp .clcr
.clcr_done:
        lea rdi, [lens_clc]
        mov rsi, 19
        lea rdx, [huff_clc]
        call inf_build
        xor ebx, ebx                   ; índice
.rl:
        mov ecx, r13d
        add ecx, r14d
        cmp ebx, ecx
        jae .rl_done
        lea rdi, [huff_clc]
        call inf_decode
        cmp eax, 16
        jb .rl_lit
        je .rl_rep16
        cmp eax, 17
        je .rl_rep17
        cmp eax, 18
        je .rl_rep18
        jmp .bad_huff
.rl_lit:
        mov ecx, r13d
        add ecx, r14d
        cmp ebx, ecx
        jae .bad_huff
        mov [lens_all + rbx*4], eax
        inc ebx
        jmp .rl
.rl_rep16:
        test ebx, ebx
        jz .bad_huff
        mov ecx, 2
        call inf_take
        add eax, 3
        mov r10d, [lens_all + rbx*4 - 4]
        jmp .rl_fill
.rl_rep17:
        mov ecx, 3
        call inf_take
        add eax, 3
        xor r10d, r10d
        jmp .rl_fill
.rl_rep18:
        mov ecx, 7
        call inf_take
        add eax, 11
        xor r10d, r10d
.rl_fill:
        mov r9d, eax
.rl_fill_loop:
        test r9d, r9d
        jz .rl
        mov ecx, r13d
        add ecx, r14d
        cmp ebx, ecx
        jae .bad_huff
        mov [lens_all + rbx*4], r10d
        inc ebx
        dec r9d
        jmp .rl_fill_loop
.rl_done:
        xor ecx, ecx
.sp1:
        cmp ecx, r13d
        jae .sp1d
        mov eax, [lens_all + rcx*4]
        mov [lens_lit + rcx*4], eax
        inc ecx
        jmp .sp1
.sp1d:
        xor ecx, ecx
.sp2:
        cmp ecx, r14d
        jae .sp2d
        mov r9, r13
        shl r9, 2
        lea r9, [lens_all + r9]
        mov eax, [r9 + rcx*4]
        mov [lens_dist + rcx*4], eax
        inc ecx
        jmp .sp2
.sp2d:
        lea rdi, [lens_lit]
        mov rsi, r13
        lea rdx, [huff_lit]
        call inf_build
        lea rdi, [lens_dist]
        mov rsi, r14
        lea rdx, [huff_dist]
        call inf_build
        call inf_codes
        jc .bad_huff
.nextblk:
        test r12d, r12d
        jnz .block
        xor rax, rax
        jmp .out
.bad_stored:
        mov rax, -4
        jmp .out
.bad_room:
        mov rax, -6
        jmp .out
.bad_huff:
        mov rax, -5
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

section .kdata
inf_src:    dq 0
inf_dst:    dq 0
inf_bitbuf: dq 0
inf_bitcnt: dd 0
inf_room:   dd 0

align 8
clc_order: dd 16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15
len_base:  dd 3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258
len_extra: dd 0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0
dist_base: dd 1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577
dist_extra:dd 0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13

lens_all:  times 320 dd 0
lens_lit:  times 288 dd 0
lens_dist: times 30 dd 0
lens_clc:  times 19 dd 0
huff_lit:  times (16+288) dd 0
huff_dist: times (16+30) dd 0
huff_clc:  times (16+19) dd 0

%endif
