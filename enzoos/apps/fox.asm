; =============================================================================
;  EnzoOS — apps/fox.asm: FOX.ENZ — EnzoFox, o navegador embutido do EnzoOS
;
;  Firefox-style: 3 ABAS independentes, HISTORICO (voltar), FAVORITOS,
;  pagina inicial OFFLINE embutida, coloracao de titulos/links, barra de
;  status e fetch HTTP real pela placa e1000 (QEMU user-net 10.0.2.2:8000).
;
;  Teclas: Enter=IR  B=voltar  H=inicio  T=proxima aba  M=marcar favorito
;          L=pagina de favoritos  (digitacao edita a URL)
;  Mouse: clique em abas, VOLTAR, INICIO, IR.
;
;  App .ENZ cru (org 0, entry 0) — cabecalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

%define API_RECT    1
%define API_TEXT    2
%define API_TITLE   4
%define API_INVAL   12
%define API_GRAD    22
%define API_ROUND   23
%define API_NETGET  32

%define URL_MAX    96
%define PAGE_MAX   6144
%define NTABS      3
%define NHIST      8
%define NBM        5

%define PAGE_X     14
%define PAGE_Y     74
%define LINE_H     18
%define MAX_LINES  19
%define LINE_CHARS 70

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

; ---------------------------------------------------------------------------
ev_init:
        mov eax, [r13+16]
        mov [tw_], eax
        mov eax, [r13+24]
        mov [th_], eax
        mov rax, [r12 + 8*API_TITLE]
        lea rdi, [s_title]
        call rax
        ; aba 0 comeca na home; aba 1 vem com o endereco de demonstracao
        ; (servidor na porta 8000 do host no QEMU); aba 2 em branco
        mov dword [cur_tab], 0
        lea rdi, [tab_url]
        lea rsi, [s_homeurl]
        call copy_str
        call load_home_cur
        lea rdi, [tab_url + 1*(URL_MAX+1)]
        lea rsi, [s_demourl]
        call copy_str
        jmp epilogue

; ---------------------------------------------------------------------------
ev_key:
        mov eax, [r13+16]
        cmp eax, 0x80                       ; backspace
        je .bs
        cmp eax, 13                         ; enter
        je .go
        ; atalhos exigem Ctrl (senao 'h'/'t' atrapalham URLs)
        mov ecx, [r13+32]                   ; mods
        test ecx, 2
        jz .plain
        cmp eax, 116                        ; ctrl+t = proxima aba
        je .tab
        cmp eax, 104                        ; ctrl+h = inicio
        je .home
        cmp eax, 98                         ; ctrl+b = voltar
        je .back
        cmp eax, 109                        ; ctrl+m = marcar favorito
        je .mark
        cmp eax, 108                        ; ctrl+l = lista de favoritos
        je .bmlist
        jmp .done
.plain:
        cmp eax, 32
        jb .done
        cmp eax, 126
        ja .done
        ; adiciona caractere na URL da aba atual
        cmp dword [editing], 0
        jne .ed1
        call url_cur
        mov rdi, rax
        lea rsi, [nav_prev]
        call copy_str
        mov dword [editing], 1
.ed1:
        mov rbx, rax                        ; salva o caractere
        call url_cur
        mov rdi, rax
        call slen
        cmp eax, URL_MAX - 1
        jae .done
        call url_cur
        mov rdi, rax
        call slen
        call url_cur
        add rdi, rax
        mov [rdi], bl
        mov byte [rdi + 1], 0
        jmp .done
.bs:
        cmp dword [editing], 0
        jne .ed2
        call url_cur
        mov rdi, rax
        lea rsi, [nav_prev]
        call copy_str
        mov dword [editing], 1
.ed2:
        call url_cur
        mov rdi, rax
        call slen
        test eax, eax
        jz .done
        call url_cur
        mov rdi, rax
        call slen
        call url_cur
        add rdi, rax
        dec rdi
        mov byte [rdi], 0
.done:
        call render
        jmp epilogue
.go:
        cmp dword [editing], 0
        je .gonav
        lea rsi, [nav_prev]
        call push_str_hist
.gonav:
        mov dword [editing], 0
        call fetch_cur
        jmp epilogue
.tab:
        mov eax, [cur_tab]
        inc eax
        cmp eax, NTABS
        jb .tabok
        xor eax, eax
.tabok:
        mov [cur_tab], eax
        lea rdi, [s_sttab]
        call set_status
        call render
        jmp epilogue
.home:
        call url_cur
        mov rdi, rax
        lea rsi, [s_homeurl]
        call copy_str
        call load_home_cur
        jmp epilogue
.back:
        call go_back
        jmp epilogue
.mark:
        call add_bookmark
        jmp epilogue
.bmlist:
        call render_bookmarks
        jmp epilogue

; ---------------------------------------------------------------------------
ev_mouse:
        mov eax, [r13+32]
        test eax, 1
        jz .out
        mov ebx, [r13+16]                   ; x
        mov ebp, [r13+24]                   ; y
        ; abas (y 4..26, x 8..500)
        cmp ebp, 4
        jl .out
        cmp ebp, 26
        jg .toolbar
        cmp ebx, 8
        jl .out
        cmp ebx, 8 + NTABS*164
        jg .out
        mov eax, ebx
        sub eax, 8
        xor edx, edx
        mov ecx, 164
        div ecx
        cmp eax, NTABS
        jae .out
        mov [cur_tab], eax
        call refresh_tab
        lea rdi, [s_sttab]
        call set_status
        call render
        jmp .out
.toolbar:
        cmp ebp, 34
        jl .out
        cmp ebp, 60
        jg .out
        ; VOLTAR (10..66)
        cmp ebx, 10
        jl .out
        cmp ebx, 66
        jle .do_back
        ; INICIO (72..128)
        cmp ebx, 72
        jl .out
        cmp ebx, 128
        jle .do_home
        ; IR (492..536)
        cmp ebx, 492
        jl .out
        cmp ebx, 536
        jle .do_go
        jmp .out
.do_back:
        call go_back
        jmp .out
.do_home:
        lea rdi, [url_cur]
        lea rsi, [s_homeurl]
        call copy_str
        call load_home_cur
        jmp .out
.do_go:
        call fetch_cur
.out:
        jmp epilogue

; ---------------------------------------------------------------------------
ev_paint:
        call render
        jmp epilogue

; ---- enderecos da aba corrente ---------------------------------------------
; url_cur -> rdi = &url da aba atual (para copy_str dst)
url_cur:
        mov eax, [cur_tab]
        imul eax, eax, URL_MAX+1
        lea rdx, [tab_url]
        add rax, rdx
        ret
page_cur:
        mov eax, [cur_tab]
        imul eax, eax, PAGE_MAX
        lea rdx, [tab_page]
        add rax, rdx
        ret

; ---- fetch na aba corrente --------------------------------------------------
fetch_cur:
        push rbx
        mov dword [cur_status], 0
        lea rdi, [s_stwait]
        call set_status
        call render
        call url_cur                        ; rax = &url
        mov rdi, rax
        call page_cur
        mov rsi, rax
        mov edx, PAGE_MAX
        mov rax, [r12 + 8*API_NETGET]
        call rax
        mov [cur_len], eax
        test eax, eax
        jns .ok
        ; erro de rede -> pagina embutida de erro
        mov [cur_status], eax
        mov rbx, rax                        ; codigo
        call page_cur
        mov rdi, rax
        lea rsi, [s_errpage]
        call copy_str
        call page_cur
        mov rdi, rax
        call slen
        mov [cur_len], eax
        lea rdi, [s_sterr]
        call set_status
        call render
        pop rbx
        ret
.ok:
        call page_cur
        mov rdi, rax
        mov esi, [cur_len]
        call strip_tags                    ; remove <...> e \r in-place
        mov [cur_len], eax                 ; novo comprimento
        ; corpo: acha \r\n\r\n (fim do cabecalho HTTP)
        call page_cur
        mov rbx, rax
        add rbx, [cur_len]
        mov r14, rax
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
        call page_cur
        mov r14, rax
.found:
        mov [cur_body], r14
        lea rdi, [s_stok]
        call set_status
        call render
        pop rbx
        ret

; ---- home embutida na aba corrente ------------------------------------------
load_home_cur:
        push rbx
        call push_hist
        call page_cur
        mov rdi, rax
        lea rsi, [s_homepage]
        call copy_str
        call refresh_tab
        lea rdi, [s_sthome]
        call set_status
        call render
        pop rbx
        ret

; refresh_tab: cur_body/cur_len a partir do buffer da aba corrente
refresh_tab:
        push rbx
        call page_cur
        mov [cur_body], rax
        mov rdi, rax
        call slen
        mov [cur_len], eax
        pop rbx
        ret

; ---- historico ----------------------------------------------------------------
push_hist:                       ; empilha a URL atual (se nao vazia)
        push rbx
        call url_cur
        mov rdi, rax
        call slen
        test eax, eax
        jz .skip
        call url_cur
        mov rsi, rax
        call push_str_hist
.skip:
        pop rbx
        ret

push_str_hist:                   ; rsi = URL fonte -> empilha no historico
        push rbx
        mov rbx, rsi
        test rbx, rbx
        jz .skip2
        ; desloca historico para cima (descarta o mais antigo)
        mov ecx, NHIST - 1
.shift:
        lea rdi, [hist]
        mov eax, ecx
        dec eax
        imul eax, eax, URL_MAX+1
        add rdi, rax
        lea rsi, [hist]
        mov eax, ecx
        imul eax, eax, URL_MAX+1
        add rsi, rax
        call copy_str
        dec ecx
        jnz .shift
        ; slot 0 = URL fonte
        mov rsi, rbx
        lea rdi, [hist]
        call copy_str
        cmp dword [hist_n], NHIST
        jae .skip2
        inc dword [hist_n]
.skip2:
        pop rbx
        ret

go_back:                         ; volta no historico
        push rbx
        cmp dword [hist_n], 1
        jbe .none
        ; URL <- hist[0]; compacta o historico
        lea rsi, [hist]
        call url_cur
        mov rdi, rax
        lea rsi, [hist]
        call copy_str
        mov ecx, NHIST - 1
.comp:
        lea rsi, [hist]
        mov eax, ecx
        imul eax, eax, URL_MAX+1
        add rsi, rax
        lea rdi, [hist]
        mov eax, ecx
        dec eax
        imul eax, eax, URL_MAX+1
        add rdi, rax
        call copy_str
        dec ecx
        jnz .comp
        dec dword [hist_n]
        ; carrega a URL (se for http, fetch; senao home)
        call url_cur
        mov rdi, rax
        call slen
        test eax, eax
        jz .loadhome
        call url_cur
        mov rax, [rax]
        cmp eax, 0x70747468               ; "http"
        je .dofetch
.loadhome:
        call url_cur
        mov rdi, rax
        lea rsi, [s_homeurl]
        call copy_str
        call load_home_cur
        pop rbx
        ret
.dofetch:
        call fetch_cur
        pop rbx
        ret
.none:
        lea rdi, [s_stnohist]
        call set_status
        call render
        pop rbx
        ret

; ---- favoritos -----------------------------------------------------------------
add_bookmark:
        push rbx
        cmp dword [bm_n], NBM
        jae .full
        mov eax, [bm_n]
        imul eax, eax, URL_MAX+1
        lea rdi, [bm]
        add rdi, rax
        call url_cur
        mov rsi, rax
        mov eax, [bm_n]
        imul eax, eax, URL_MAX+1
        lea rdi, [bm]
        add rdi, rax
        call copy_str
        inc dword [bm_n]
        lea rdi, [s_stmarked]
        call set_status
        call render
        pop rbx
        ret
.full:
        lea rdi, [s_stbmfull]
        call set_status
        call render
        pop rbx
        ret

render_bookmarks:                ; pagina de favoritos na aba corrente
        push rbx
        call page_cur
        mov rdi, rax
        lea rsi, [s_bmhdr]
        call copy_str
        xor ebx, ebx
.lp:
        cmp ebx, [bm_n]
        jae .done
        call page_cur
        mov rdi, rax
        call slen
        mov ecx, eax
        call page_cur
        add rcx, rax
        mov rax, rbx
        imul rax, rax, URL_MAX+1
        lea rsi, [bm]
        add rsi, rax
        ; copia a entrada
        mov rdi, rcx
.bcopy:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .bdone
        inc rsi
        inc rdi
        jmp .bcopy
.bdone:
        mov byte [rdi], 10
        mov byte [rdi + 1], 0
        inc ebx
        jmp .lp
.done:
        call refresh_tab
        lea rdi, [s_stbm]
        call set_status
        call render
        pop rbx
        ret

; ---- utilitarios -----------------------------------------------------------------
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

slen:                           ; rdi=str -> eax (máx 4096: hardening)
        xor eax, eax
.l:
        cmp eax, 4096
        jae .d
        cmp byte [rdi + rax], 0
        je .d
        inc eax
        jmp .l
.d:
        ret

set_status:                     ; rdi=str -> statusmsg da aba corrente? (global)
        lea rsi, [statusmsg]
        jmp copy_str

text_at:                        ; edi=x esi=y rdx=str r8d=cor
        push rdi
        push rsi
        push rdx
        push r8
        mov rdi, rdx
        call slen
        mov ecx, eax
        pop r8
        pop rdx
        pop rsi
        pop rdi
        mov rax, [r12 + 8*API_TEXT]
        jmp rax

; strip_tags: rdi=buf esi=len — remove <...> e \r, compacta; retorna novo len em eax
strip_tags:
        push rbx
        push r12
        push r13
        push r14
        mov rbx, rdi                 ; destino (mesmo buffer)
        mov r12, rdi                 ; origem
        lea r13, [rdi + rsi]         ; fim
        xor r14d, r14d               ; dentro de <..>?
.scan:
        cmp r12, r13
        jae .end
        movzx eax, byte [r12]
        cmp al, '<'
        je .open
        cmp al, '>'
        je .close
        cmp al, 13
        je .skipc
        cmp al, 9
        je .skipc
        test r14d, r14d
        jnz .skipc
        mov [rbx], al
        inc rbx
        jmp .skipc
.open:
        mov r14d, 1
        jmp .skipc
.close:
        xor r14d, r14d
        jmp .skipc
.skipc:
        inc r12
        jmp .scan
.end:
        mov byte [rbx], 0
        mov rax, rbx
        sub rax, rdi                 ; novo comprimento
        and eax, 0xFFFF
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; ---- render -----------------------------------------------------------------------
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
        ; faixa de abas + toolbar (gradiente laranja EnzoFox)
        xor edi, edi
        xor esi, esi
        mov edx, [tw_]
        mov ecx, 64
        mov r8d, 0x16233C
        mov r9d, 0x0E1826
        mov rax, [r12 + 8*API_GRAD]
        call rax
        ; ---- abas
        xor ebx, ebx
.tabs:
        cmp ebx, NTABS
        jae .tabs_done
        ; fundo da aba
        mov edi, 8
        mov eax, ebx
        imul eax, eax, 164
        add edi, eax
        mov esi, 4
        mov edx, 156
        mov ecx, 22
        mov r8d, 0x1A2740
        cmp ebx, [cur_tab]
        jne .tabcol
        mov r8d, 0x2E4166
.tabcol:
        mov rax, [r12 + 8*API_ROUND]
        mov r9d, 6
        push rbx
        call rax
        pop rbx
        ; rotulo "Aba N" + dominio curto
        mov edi, 8
        mov eax, ebx
        imul eax, eax, 164
        add edi, eax
        add edi, 10
        mov esi, 9
        lea rdx, [s_tablbl]
        mov r8d, 0x9FB6D8
        cmp ebx, [cur_tab]
        jne .tabfg
        mov r8d, 0xFFFFFF
.tabfg:
        push rbx
        call text_at
        pop rbx
        ; numero da aba sobreposto
        mov edi, 8
        mov eax, ebx
        imul eax, eax, 164
        add edi, eax
        add edi, 48
        mov esi, 9
        mov eax, ebx
        add al, '1'
        mov [tabdig], al
        lea rdx, [tabdig]
        mov r8d, 0x6BDCFF
        push rbx
        call text_at
        pop rbx
        inc ebx
        jmp .tabs
.tabs_done:
        ; ---- botao VOLTAR
        mov edi, 10
        mov esi, 34
        mov edx, 56
        mov ecx, 26
        mov r8d, 6
        mov r9d, 0xFF1C3B72
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 16
        mov esi, 40
        lea rdx, [s_back]
        mov r8d, 0xF2F5FA
        call text_at
        ; ---- botao INICIO
        mov edi, 72
        mov esi, 34
        mov edx, 56
        mov ecx, 26
        mov r8d, 6
        mov r9d, 0xFF1C6B3B
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 78
        mov esi, 40
        lea rdx, [s_home]
        mov r8d, 0xF2F5FA
        call text_at
        ; ---- campo URL
        mov edi, 136
        mov esi, 34
        mov edx, 348
        mov ecx, 26
        mov r8d, 5
        mov r9d, 0xFF0B1220
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 144
        mov esi, 40
        call url_cur
        mov rdx, rax
        mov r8d, 0x9FE8FF
        call text_at
        ; ---- botao IR
        mov edi, 492
        mov esi, 34
        mov edx, 44
        mov ecx, 26
        mov r8d, 6
        mov r9d, 0xFFB35C1E
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 500
        mov esi, 40
        lea rdx, [s_go]
        mov r8d, 0xFFF3E8
        call text_at
        ; ---- moldura da pagina
        mov edi, PAGE_X - 6
        mov esi, PAGE_Y - 8
        mov edx, [tw_]
        sub edx, PAGE_X - 12
        mov ecx, MAX_LINES * LINE_H + 16
        mov r8d, 0x0A101C
        mov rax, [r12 + 8*API_RECT]
        call rax
        ; ---- linhas do corpo
        mov r14, [cur_body]
        test r14, r14
        jz .nopage
        xor ebx, ebx
.lines:
        cmp ebx, MAX_LINES
        jae .status
        call next_line                       ; eax = len ou -1
        cmp eax, -1
        je .status
        mov [line_len], eax
        mov esi, ebx
        imul esi, esi, LINE_H
        add esi, PAGE_Y
        mov edi, PAGE_X
        mov rdx, r14
        ; cor da linha: '#'=titulo, 'http'=link, '=='=separador
        mov r8d, 0xD8DEEA
        cmp byte [r14], '#'
        jne .c2
        mov r8d, 0xFFC46B
        jmp .cdraw
.c2:
        cmp byte [r14], '='
        jne .c3
        mov r8d, 0x6B8CC8
        jmp .cdraw
.c3:
        cmp byte [r14], 'h'
        jne .cdraw
        cmp byte [r14 + 1], 't'
        jne .cdraw
        cmp byte [r14 + 2], 't'
        jne .cdraw
        cmp byte [r14 + 3], 'p'
        jne .cdraw
        mov r8d, 0x6BDCFF
.cdraw:
        push rbx
        mov rax, [r12 + 8*API_TEXT]
        mov ecx, [line_len]
        call rax
        pop rbx
        ; r14 += len + 1 (pula o \n)
        mov eax, [line_len]
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
        ; indicador de bytes
        cmp dword [cur_status], 0
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
tw_:    dd 580
th_:    dd 460
cur_tab: dd 0
cur_len: dd 0
cur_status: dd 0
cur_body: dq 0
line_len: dd 0
hist_n: dd 0
bm_n:   dd 0
editing: dd 0
tabdig: db '1', 0

statusmsg: times 48 db 0

align 16
tab_url: times NTABS*(URL_MAX+1) db 0
hist:    times NHIST*(URL_MAX+1) db 0
nav_prev: times URL_MAX+1 db 0
bm:      times NBM*(URL_MAX+1) db 0
align 16
tab_page: times NTABS*PAGE_MAX db 0

s_title:   db "EnzoFox", 0
s_homeurl: db "home:inicio", 0
s_demourl: db "http://10.0.2.2:8000/", 0
s_tablbl:  db "Aba", 0
s_go:      db "IR", 0
s_back:    db "< VOLTAR", 0
s_home:    db "INICIO", 0
s_hint:    db "Enter navega | Ctrl+B volta | Ctrl+H inicio | Ctrl+T aba | Ctrl+M favorito", 0
s_stwait:  db "Baixando...", 0
s_stok:    db "Pronto.", 0
s_sterr:   db "Erro de rede — mostrando pagina offline.", 0
s_sthome:  db "Pagina inicial do EnzoFox.", 0
s_sttab:   db "Aba alterada.", 0
s_stnohist: db "Sem historico para voltar.", 0
s_stmarked: db "Favorito adicionado.", 0
s_stbmfull: db "Lista de favoritos cheia (5).", 0
s_stbm:    db "Favoritos.", 0
s_bytes:   db "bytes: ", 0
s_bmhdr:   db "== FAVORITOS ==\n", 0

s_errpage:
        db "== SEM CONEXAO ==\n"
        db "Nao deu para baixar a pagina (placa/DHCP/servidor).\n"
        db "No QEMU, rode um servidor na porta 8000 do host:\n"
        db "python3 -m http.server 8000\n"
        db "e navegue para http://10.0.2.2:8000/\n", 0

s_homepage:
        db "== EnzoFox ==\n"
        db "O navegador do EnzoOS — 64-bit, turbo, embutido.\n"
        db "# Como usar\n"
        db "Digite um endereco e aperte ENTER para navegar.\n"
        db "Com Ctrl pressionado, B H T M e L abrem os recursos.\n"
        db "# Atalhos\n"
        db "ENTER navega para o endereco digitado\n"
        db "Ctrl+B volta no historico  Ctrl+H volta para ca\n"
        db "Ctrl+T troca de aba  Ctrl+M marca favorito\n"
        db "# Links rapidos (com servidor na rede)\n"
        db "http://10.0.2.2:8000/\n"
        db "http://10.0.2.2:8000/pagina2\n"
        db "# Sobre o EnzoOS\n"
        db "Kernel NASM 64-bit, GUI, ENZFS 1 GB, 2000+ apps na LOJA,\n"
        db "compilador .CE, tradutores de .EXE/.RUN e som HDA.\n"
        db "== fim ==\n", 0
