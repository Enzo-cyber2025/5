; =============================================================================
;  EnzoOS — apps/fox.asm: FOX.ENZ — navegador EnzoFox
;  HTTP real pela placa e1000 (TCP/IP no kernel). Digite a URL, Enter, e a
;  página chega de um servidor web na rede (QEMU user-net: 10.0.2.2:8000).
;  App .ENZ cru (org 0, entry 0) — cabeçalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_RECT    1
%define API_TEXT    2
%define API_TITLE   4
%define API_INVAL   12
%define API_ROUND   23
%define API_NETGET  32

%define URL_MAX  100
%define PAGE_MAX 8192
%define PAGE_X   14
%define PAGE_Y   78
%define LINE_H   20
%define MAX_LINES 16
%define LINE_CHARS 66

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
        ; URL inicial
        lea rdi, [url]
        lea rsi, [s_home]
        call copy_str
        jmp epilogue

ev_key:
        mov eax, [r13+16]
        cmp eax, 0x80                       ; backspace
        je .bs
        cmp eax, 13                         ; enter
        je .go
        cmp eax, 32
        jb .done
        cmp eax, 126
        ja .done
        ; adiciona se couber
        lea rdi, [url]
        call slen
        cmp eax, URL_MAX - 1
        jae .done
        lea rdi, [url]
        call slen
        lea rdi, [url + rax]
        mov [rdi], al
        mov byte [rdi + 1], 0
        jmp .done
.bs:
        lea rdi, [url]
        call slen
        test eax, eax
        jz .done
        lea rdi, [url]
        call slen
        lea rdi, [url + rax - 1]
        mov byte [rdi], 0
.done:
        call render
        jmp epilogue
.go:
        call fetch
        jmp epilogue

ev_mouse:
        mov eax, [r13+32]
        test eax, 1
        jz .out
        mov ebx, [r13+16]
        mov ebp, [r13+24]
        ; botão IR
        cmp ebx, 500
        jl .out
        cmp ebx, 546
        jg .out
        cmp ebp, 12
        jl .out
        cmp ebp, 42
        jg .out
        call fetch
.out:
        jmp epilogue

ev_paint:
        call render
        jmp epilogue

; ---- fetch: baixa a URL ----
fetch:
        mov dword [status], 0
        lea rdi, [s_stwait]
        call set_status
        call render
        lea rdi, [url]
        lea rsi, [page]
        mov edx, PAGE_MAX
        mov rax, [r12 + 8*API_NETGET]
        call rax
        mov [page_len], eax
        test eax, eax
        jns .ok
        ; erro
        mov [status], eax
        lea rdi, [s_sterr]
        call set_status
        call render
        ret
.ok:
        ; procura o fim do cabeçalho (\r\n\r\n) — corpo começa depois
        lea rbx, [page]
        add rbx, rax                        ; fim
        lea r14, [page]
.find:
        cmp r14, rbx
        jae .nofind
        cmp byte [r14], 13
        jne .n1
        cmp byte [r14 + 1], 10
        jne .n1
        cmp byte [r14 + 2], 13
        jne .n1
        cmp byte [r14 + 3], 10
        jne .n1
        add r14, 4
        jmp .found
.n1:
        inc r14
        jmp .find
.nofind:
        lea r14, [page]                     ; sem corpo: mostra tudo
.found:
        mov [body_off], r14
        lea rdi, [s_stok]
        call set_status
        call render
        ret

set_status:                  ; rdi = str
        lea rsi, [statusmsg]
        jmp copy_str

; ---- helpers ----------------------------------------------------------------
copy_str:                       ; rdi=dst rsi=src
.l:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .d
        inc rsi
        inc rdi
        jmp .l
.d:
        ret

slen:                           ; rdi=str -> eax
        xor eax, eax
.l:
        cmp byte [rdi + rax], 0
        je .d
        inc eax
        jmp .l
.d:
        ret

text_at:                        ; edi=x esi=y rdx=str r8d=cor
        push rdi
        push rsi
        push rdx
        push r8
        call slen
        mov ecx, eax
        pop r8
        pop rdx
        pop rsi
        pop rdi
        mov rax, [r12 + 8*API_TEXT]
        jmp rax

; ---- render -----------------------------------------------------------------
render:
        push rbx
        ; fundo
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, [th_]
        mov r8d, 0x0E1826
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; barra superior
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, 58
        mov r8d, 0x16233C
        mov r9d, 0x0E1826
        mov rax, [r12 + 8*22]               ; grad
        call rax
        ; campo URL
        mov edi, 12
        mov esi, 12
        mov edx, 476
        mov ecx, 30
        mov r8d, 5
        mov r9d, 0xFF0B1220
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 20
        mov esi, 20
        lea rdx, [url]
        mov r8d, 0x9FE8FF
        call text_at
        ; botão IR
        mov edi, 500
        mov esi, 12
        mov edx, 46
        mov ecx, 30
        mov r8d, 6
        mov r9d, 0xFF1C3B72
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 508
        mov esi, 20
        lea rdx, [s_go]
        mov r8d, 0xF2F5FA
        call text_at
        ; moldura da página
        mov edi, PAGE_X - 4
        mov esi, PAGE_Y - 6
        mov edx, 530
        mov ecx, MAX_LINES * LINE_H + 14
        mov r8d, 0x0A101C
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; linhas do corpo
        mov r14, [body_off]
        test r14, r14
        jz .nopage
        xor ebx, ebx
.lines:
        cmp ebx, MAX_LINES
        jae .status
        call next_line                       ; eax = len ou -1
        cmp eax, -1
        je .status
        mov ecx, eax
        mov esi, ebx
        imul esi, LINE_H
        add esi, PAGE_Y
        mov edi, PAGE_X
        mov rdx, r14
        mov r8d, 0xD8DEEA
        mov rax, [r12 + 8*API_TEXT]
        call rax
        ; r14 += len + 1 (pula o \n)
        mov eax, ecx
        lea r14, [r14 + rax + 1]
        inc ebx
        jmp .lines
.nopage:
        mov edi, PAGE_X
        mov esi, PAGE_Y
        lea rdx, [s_hint]
        mov r8d, 0x5A7196
        call text_at
.status:
        ; barra de status
        mov edi, 0
        mov esi, [th_]
        sub esi, 24
        mov edx, [tw_]
        mov ecx, 24
        mov r8d, 0x101B2E
        mov rax, [r12 + 8*API_RECT]
        call rax
        mov edi, 12
        mov esi, [th_]
        sub esi, 18
        lea rdx, [statusmsg]
        mov r8d, 0x8FA8CE
        call text_at
        ; bytes
        cmp dword [status], 0
        jne .sb
        mov edi, 420
        mov esi, [th_]
        sub esi, 18
        lea rdx, [s_bytes]
        mov r8d, 0x8FA8CE
        call text_at
.sb:
        pop rbx
        ret

; next_line: r14 = pos -> eax = comprimento (-1 = fim), para em \n ou NUL
next_line:
        xor eax, eax
.l:
        cmp eax, LINE_CHARS
        jae .d
        movzx edx, byte [r14 + rax]
        test edx, edx
        jz .e
        cmp dl, 10
        je .d
        cmp dl, 13
        je .d
        inc eax
        jmp .l
.e:
        test eax, eax
        jz .none
.d:
        ret
.none:
        mov eax, -1
        ret

; ---- dados ------------------------------------------------------------------
tw_:    dd 560
th_:    dd 440
page_len: dd 0
status:  dd 0
body_off: dq 0

url:     times URL_MAX + 1 db 0
statusmsg: times 48 db 0
align 16
page:    times PAGE_MAX db 0

s_home:   db "http://10.0.2.2:8000/", 0
s_go:     db "IR", 0
s_hint:   db "Digite a URL e aperte Enter — EnzoFox via e1000", 0
s_stwait: db "Baixando...", 0
s_stok:   db "Pronto.", 0
s_sterr:  db "Erro de rede (sem NIC? DHCP? conexao?).", 0
s_bytes:  db "bytes: ", 0
