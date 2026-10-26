; =============================================================================
;  EnzoOS — apps/info.asm: INFO.CE — informações do sistema (CPUID, memória,
;  vídeo, heap, janelas, arquivos).
; =============================================================================
BITS 64
org 0
default rel

header:
        db "CE01"
        dw 64, 0
        dd app_entry
        dd image_end - header
        dd 1
        dw 460, 340
        dd 0
        db "Sistema", 0
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
        cmp eax, 5
        je ev_tick
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
        lea rdi, [sibuf]
        mov rax, [r12 + 8*15]
        call rax
        jmp epilogue

ev_tick:
        mov rax, [r12 + 8*5]
        call rax
        mov [uptime], eax
        call render
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

; ---- render ------------------------------------------------------------------
render:
        push rbx
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0B1220
        mov rax, [r12 + 8*1]
        call rax
        ; marca da CPU
        mov edi, 12
        mov esi, 12
        lea rdx, [sibuf]
        call slen
        mov r8d, 0x10A372
        call text_at
        ; pares rótulo/valor
        lea rdi, [l_cores]
        mov esi, 48
        mov eax, [sibuf + 52]
        call draw_kv
        lea rdi, [l_ram]
        mov esi, 64
        mov eax, [sibuf + 56]
        call draw_kv
        ; modo: WxHxbpp
        lea rdi, [l_mode]
        mov esi, 80
        call draw_label
        mov edi, 170
        mov esi, 80
        call draw_mode
        ; LFB
        lea rdi, [l_lfb]
        mov esi, 96
        call draw_label
        mov edi, 170
        mov esi, 96
        mov eax, [sibuf + 72]
        call draw_hex
        ; heap
        lea rdi, [l_heap]
        mov esi, 112
        mov eax, [sibuf + 104]
        shl eax, 2                     ; páginas * 4 = KB
        call draw_kv
        ; RAM total heap (MB)
        lea rdi, [l_heapmax]
        mov esi, 128
        mov eax, [sibuf + 120]
        call draw_kv
        lea rdi, [l_wnd]
        mov esi, 144
        mov eax, [sibuf + 112]
        call draw_kv
        lea rdi, [l_files]
        mov esi, 160
        mov eax, [sibuf + 116]
        call draw_kv
        lea rdi, [l_up]
        mov esi, 176
        mov eax, [uptime]
        mov ecx, 1000
        xor edx, edx
        div ecx
        call draw_kv
        ; recursos CPUID (hex)
        lea rdi, [l_edx]
        mov esi, 192
        call draw_label
        mov edi, 170
        mov esi, 192
        mov eax, [sibuf + 88]
        call draw_hex
        lea rdi, [l_ecx]
        mov esi, 208
        call draw_label
        mov edi, 170
        mov esi, 208
        mov eax, [sibuf + 92]
        call draw_hex
        ; rodapé
        mov edi, 12
        mov esi, 288
        lea rdx, [l_foot]
        call slen
        mov r8d, 0x445066
        call text_at
        pop rbx
        ret

; ---- helpers -----------------------------------------------------------------
text_at:                           ; edi=x, esi=y, rdx=str, ecx=len, r8d=cor
        mov rax, [r12 + 8*2]
        jmp rax

slen:                               ; rdx=str -> ecx=len
        xor ecx, ecx
.l:
        cmp ecx, 60
        jae .d
        cmp byte [rdx + rcx], 0
        je .d
        inc ecx
        jmp .l
.d:
        ret

draw_label:                        ; rdi=rótulo, esi=y
        push rsi
        mov rdx, rdi
        mov edi, 12
        call slen
        mov r8d, 0x8FA0B8
        call text_at
        pop rsi
        ret

draw_kv:                           ; rdi=rótulo, esi=y, eax=valor
        push rbx
        push r14
        mov r14d, esi
        mov rbx, rdi
        mov ebp, eax
        call draw_label
        mov eax, ebp
        call utoa_local
        mov edi, 170
        mov esi, r14d
        lea rdx, [numbuf]
        mov r8d, 0xF2F5FA
        call text_at
        pop r14
        pop rbx
        ret

draw_hex:                          ; edi=x, esi=y, eax=valor hex
        push rsi
        push r14
        mov r14d, esi
        mov ebp, eax
        call hex8_local
        mov edi, 170
        mov esi, r14d
        lea rdx, [numbuf]
        mov ecx, 8
        mov r8d, 0xF2F5FA
        call text_at
        pop r14
        pop rsi
        ret

; draw_mode: edi=x, esi=y — "WxHxbpp" a partir do sysinfo
draw_mode:
        push rsi
        mov r14d, esi
        lea rdi, [numbuf]
        mov eax, [sibuf + 60]
        call cat_dec
        mov al, 'x'
        call stosb_c
        mov eax, [sibuf + 64]
        call cat_dec
        mov al, 'x'
        call stosb_c
        mov eax, [sibuf + 68]
        call cat_dec
        xor eax, eax
        call stosb_c
        mov edi, 170
        mov esi, r14d
        lea rdx, [numbuf]
        call slen
        mov r8d, 0xF2F5FA
        call text_at
        pop rsi
        ret

; cat_dec: eax=valor, rdi=ponteiro de escrita (avança)
cat_dec:                           ; eax=valor, rdi=dest (rdi avança)
        push rdi
        push rsi
        push rdx
        push rcx
        mov ebp, eax
        call utoa_local
        lea rsi, [numbuf]
        xor edx, edx
.cp:
        cmp edx, ecx
        jae .cd
        mov al, [rsi + rdx]
        mov [rdi], al
        inc rdi
        inc rdx
        jmp .cp
.cd:
        pop rcx
        pop rdx
        pop rsi
        add rsp, 8                   ; descarta o rdi antigo
        ret

stosb_c:
        mov [rdi], al
        inc rdi
        ret

; utoa_local: eax -> numbuf (decimal), ecx=len
utoa_local:
        lea rdi, [numbuf + 20]
        mov byte [rdi], 0
        mov ecx, 10
        mov r8d, 0
        test eax, eax
        jz .zero
.d:
        test eax, eax
        jz .done
        xor edx, edx
        div ecx
        add dl, '0'
        dec rdi
        mov [rdi], dl
        inc r8d
        jmp .d
.zero:
        dec rdi
        mov byte [rdi], '0'
        mov r8d, 1
.done:
        mov r9, rdi
        lea rdi, [numbuf]
        xor ecx, ecx
.cp:
        cmp ecx, r8d
        jae .cd
        mov al, [r9 + rcx]
        mov [rdi + rcx], al
        inc ecx
        jmp .cp
.cd:
        mov byte [rdi + rcx], 0
        mov ecx, r8d
        ret

; hex8_local: eax -> numbuf (8 dígitos hex)
hex8_local:
        lea rdi, [numbuf]
        mov ecx, 8
.l:
        rol eax, 4
        mov edx, eax
        and edx, 15
        cmp edx, 10
        jb .dig
        add edx, 'A' - 10
        jmp .wr
.dig:
        add edx, '0'
.wr:
        mov [rdi], dl
        inc rdi
        dec ecx
        jnz .l
        mov byte [rdi], 0
        ret

; dados
l_cores:  db "Nucleos logicos:", 0
l_ram:    db "Memoria RAM (MB):", 0
l_mode:   db "Modo grafico:", 0
l_lfb:    db "LFB:", 0
l_heap:   db "Heap livre (KB):", 0
l_heapmax: db "Heap total (MB):", 0
l_wnd:    db "Janelas ativas:", 0
l_files:  db "Arquivos no CEFS:", 0
l_up:     db "Tempo ligado (s):", 0
l_edx:    db "CPUID EDX (hex):", 0
l_ecx:    db "CPUID ECX (hex):", 0
l_foot:   db "EnzoOS — kernel 100% Assembly x86-64, sem C, sem libc", 0

tw_: dd 460
th_: dd 340
uptime: dd 0

align 16
sibuf: times 128 db 0
numbuf: times 32 db 0

image_end:
