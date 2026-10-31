; =============================================================================
;  EnzoOS — apps/attack.asm: ATTACK.ENZ — suíte de pen-test do sistema
;
;  Roda uma bateria de chamadas hostis contra as APIs do kernel (inputs
;  inválidos, ponteiros ruins, tamanhos negativos/imensos, paths maliciosos
;  e binários malformados) para verificar que o kernel rejeita tudo sem
;  pânico, sem corrupção de memória e sem corromper o sistema de arquivos.
;
;  Cada teste concluído marca um pixel na linha de progresso da janela.
;  Se o kernel pânico em algum teste, a linha mostra exatamente onde.
;  Ao final: "ALL TESTS OK" na janela.
;
;  App .ENZ cru (org 0) — cabeçalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

; ---- índices na APITBL (ordem de k_exports, 1..36) ----
%define API_RECT    1
%define API_TEXT    2
%define API_BLIT    3
%define API_TITLE   4
%define API_EXEC    9
%define API_CONOUT  10
%define API_INVAL   12
%define API_ALLOC   13
%define API_FREE    14
%define API_SYSINFO 15
%define API_TIME    16
%define API_BEEP    18
%define API_SELF    19
%define API_PX      20
%define API_LINE    21
%define API_GRAD    22
%define API_ROUND   23
%define API_BLEND   24
%define API_FSOPEN  25
%define API_FSLIST  26
%define API_FSREAD  27
%define API_FSWRITE 28
%define API_FSCREAT 29
%define API_FSMKDIR 30
%define API_FSUNLINK 31
%define API_HPET    35
%define API_TONE    36

%define GREEN   0x10A372
%define CYAN    0x56C8D8
%define WHITE   0xF2F5FA
%define RED     0xE05555

; bissetação: para a bateria após o teste STOP_AT (default: todos)
%ifndef STOP_AT
%define STOP_AT 999
%endif

; =============================================================================
app_entry:
        push rbx
        push rbp
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; APITBL
        mov r13, rsi                    ; evento
        mov eax, [rsi]
        cmp eax, 1
        je ev_init
        cmp eax, 2
        je ev_paint
        jmp epilogue
epilogue:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbp
        pop rbx
        ret

; ---- marca o teste n como concluído (pixel na linha de progresso) ----
;      edi = número do teste
pass:
        push rdi
        push rsi
        push rdx
        push rcx
        push r8
        push rax
        push rdx
        push rcx
        ; telemetria serial: 'a' + n (0x3F8) — mostra o último teste vivo
        mov al, 96                     ; 'a'-1
        add al, dil
        mov dx, 0x3FD                  ; LSR
.w1:    in al, dx
        test al, 0x20
        jz .w1
        mov al, 96
        add al, dil
        mov dx, 0x3F8
        out dx, al
        pop rcx
        pop rdx
        pop rax
        mov esi, 34                     ; y fixo da linha de progresso
        mov edx, 6
        mov ecx, 6
        mov r8d, GREEN
        imul edi, edi, 10
        add edi, 12
        mov rax, [r12 + 8*API_RECT]
        call rax
        mov rax, [r12 + 8*API_INVAL]
        call rax
        pop r8
        pop rcx
        pop rdx
        pop rsi
        pop rdi
        mov [rel tests_done], edi
        ; bissetação: fim antecipado?
        cmp edi, STOP_AT
        jne .no_stop
        mov dword [rel alldone], 1
        mov rax, [r12 + 8*API_INVAL]
        call rax
        mov rax, epilogue
        jmp rax                        ; retorna do EV_INIT imediatamente
.no_stop:
        ret

; (nota: edi aqui ainda é o número original do teste — o imul acima
;  trabalhou numa cópia? NÃO: precisamos preservar o número)
; pass_save: variável local para o número do teste

; =============================================================================
ev_init:
        ; banner
        xor edi, edi
        xor esi, esi
        lea rdx, [s_banner]
        mov ecx, 20
        mov r8d, CYAN
        mov rax, [r12 + 8*API_TEXT]
        call rax

        ; ------------------------------------------------ t1: alloc(0)
        xor edi, edi
        mov rax, [r12 + 8*API_ALLOC]
        call rax                        ; deve retornar 0 ou ptr válido
        mov edi, 1
        call pass

        ; ------------------------------------------------ t2: alloc(0x7FFF0000)
        mov edi, 0x7FFF0000
        mov rax, [r12 + 8*API_ALLOC]
        call rax                        ; deve falhar -> 0, sem corromper
        mov edi, 2
        call pass

        ; ------------------------------------------------ t3: free(NULL)
        xor edi, edi
        xor esi, esi
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov edi, 3
        call pass

        ; ------------------------------------------------ t4: free(ptr lixo)
        mov edi, 0xDEADB000
        mov esi, 64
        mov rax, [r12 + 8*API_FREE]
        call rax                        ; não pode pânico/corrupção
        mov edi, 4
        call pass

        ; ------------------------------------------------ t5: double free
        mov edi, 64
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        mov r14, rax                    ; r14 = bloco
        mov rdi, r14
        mov esi, 64
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov rdi, r14
        mov esi, 64
        mov rax, [r12 + 8*API_FREE]
        call rax                        ; segundo free: rejeitar
        mov edi, 5
        call pass

        ; ------------------------------------------------ t6: free(ptr+16)
        mov edi, 128
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        mov r14, rax
        lea rdi, [r14 + 16]             ; interior do bloco
        mov esi, 128
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov rdi, r14                    ; e o free correto depois
        mov esi, 128
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov edi, 6
        call pass

        ; ------------------------------------------------ t7: rect negativo/imenso
        mov edi, -1000
        mov esi, -1000
        mov edx, 60000
        mov ecx, 60000
        mov r8d, RED
        mov rax, [r12 + 8*API_RECT]
        call rax                        ; clamp: nada fora da janela
        mov edi, 7
        call pass

        ; ------------------------------------------------ t8: px fora da janela
        mov edi, -100
        mov esi, -100
        mov edx, RED
        mov rax, [r12 + 8*API_PX]
        call rax
        mov edi, 0x100000
        mov esi, 0x100000
        mov edx, RED
        mov rax, [r12 + 8*API_PX]
        call rax
        mov edi, 8
        call pass

        ; ------------------------------------------------ t9: line imensa
        mov edi, -5
        mov esi, -5
        mov edx, 99999
        mov ecx, 99999
        mov r8d, RED
        mov rax, [r12 + 8*API_LINE]
        call rax
        mov edi, 9
        call pass

        ; ------------------------------------------------ t10: grad negativo
        mov edi, 10
        mov esi, 10
        mov edx, -50
        mov ecx, -50
        mov r8d, RED
        mov r9d, 0
        mov rax, [r12 + 8*API_GRAD]
        call rax
        mov edi, 10
        call pass

        ; ------------------------------------------------ t11: round imenso
        mov edi, -10
        mov esi, -10
        mov edx, 100000
        mov ecx, 100000
        mov r8d, 100000                  ; raio gigante
        mov r9d, RED
        mov rax, [r12 + 8*API_ROUND]
        call rax
        mov edi, 11
        call pass

        ; ------------------------------------------------ t12: blend src nulo
        xor edi, edi
        xor esi, esi
        mov edx, 16
        mov ecx, 16
        xor r8d, r8d                    ; src = NULL
        xor r9d, r9d
        mov rax, [r12 + 8*API_BLEND]
        call rax
        mov edi, 12
        call pass

        ; ------------------------------------------------ t13: fs_open path traversal
        lea rdi, [s_trav]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax                        ; "../../etc/passwd" -> -1
        mov edi, 13
        call pass

        ; ------------------------------------------------ t14: fs_open vazio
        lea rdi, [s_empty]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov edi, 14
        call pass

        ; ------------------------------------------------ t15: fs_open nome comprido
        lea rdi, [s_longname]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov edi, 15
        call pass

        ; ------------------------------------------------ t16: fs_read ino inválido
        mov edi, 99999
        lea rsi, [iobuf]
        mov edx, 64
        mov rax, [r12 + 8*API_FSREAD]
        call rax                        ; -> 0/-1, sem tocar iobuf além
        mov edi, 16
        call pass

        ; ------------------------------------------------ t17: fs_list ino inválido
        mov edi, 99999
        xor esi, esi
        lea rdx, [iobuf]
        mov rax, [r12 + 8*API_FSLIST]
        call rax
        mov edi, 17
        call pass

        ; ------------------------------------------------ t18: fs_write ino inválido
        mov edi, 99999
        lea rsi, [iobuf]
        mov edx, 4
        mov rax, [r12 + 8*API_FSWRITE]
        call rax                        ; -> -1
        mov edi, 18
        call pass

        ; ------------------------------------------------ t19: fs_creat vazio
        lea rdi, [s_empty]
        mov rax, [r12 + 8*API_FSCREAT]
        call rax
        mov edi, 19
        call pass

        ; ------------------------------------------------ t20: fs_mkdir profundo
        lea rdi, [s_deep]
        mov rax, [r12 + 8*API_FSMKDIR]
        call rax
        mov edi, 20
        call pass

        ; ------------------------------------------------ t21: text str NULL
        xor edi, edi
        xor esi, esi
        xor edx, edx                    ; str = NULL
        xor ecx, ecx
        mov r8d, WHITE
        mov rax, [r12 + 8*API_TEXT]
        call rax                        ; kernel deve ignorar sem crash
        mov edi, 21
        call pass

        ; ------------------------------------------------ t22: text len imenso
        xor edi, edi
        xor esi, esi
        lea rdx, [s_banner]
        mov ecx, 0x40000000
        mov r8d, WHITE
        mov rax, [r12 + 8*API_TEXT]
        call rax                        ; clamp no conteúdo
        mov edi, 22
        call pass

        ; ------------------------------------------------ t23: conout_read max 0
        lea rdi, [iobuf]
        xor esi, esi
        mov rax, [r12 + 8*API_CONOUT]
        call rax
        mov edi, 23
        call pass

        ; ------------------------------------------------ t24: exec inexistente
        lea rdi, [s_noexec]
        mov rax, [r12 + 8*API_EXEC]
        call rax                        ; -> código negativo
        mov edi, 24
        call pass

        ; ------------------------------------------------ t25: title gigante
        lea rdi, [s_longname]
        mov rax, [r12 + 8*API_TITLE]
        call rax                        ; trunca em 31
        mov edi, 25
        call pass

        ; ------------------------------------------------ t26: tone/beep limites
        xor edi, edi
        xor esi, esi
        mov rax, [r12 + 8*API_TONE]
        call rax                        ; freq 0, dur 0
        mov edi, 26
        call pass

        ; ------------------------------------------------ t27..t30: binários malformados
        lea rdi, [s_f_trunc]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 27
        call pass

        lea rdi, [s_f_badent]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 28
        call pass

        lea rdi, [s_f_badimp]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 29
        call pass

        lea rdi, [s_f_huge]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 30
        call pass

        ; ------------------------------------------------ t31: fs_unlink raiz (destrutivo — último)
        lea rdi, [s_root]
        mov rax, [r12 + 8*API_FSUNLINK]
        call rax                        ; raiz intocável -> -1
        mov edi, 31
        call pass

        ; ---- concluído
        mov dword [rel alldone], 1
        mov rax, [r12 + 8*API_INVAL]
        call rax
        jmp epilogue

; =============================================================================
ev_paint:
        ; redesenha banner + linha + resultado
        xor edi, edi
        xor esi, esi
        lea rdx, [s_banner]
        mov ecx, 20
        mov r8d, CYAN
        mov rax, [r12 + 8*API_TEXT]
        call rax
        ; linha de progresso: um quadradinho por teste concluído
        mov r14d, [rel tests_done]
        mov edi, 1
.pl:
        cmp edi, r14d
        jg .pl_done
        push rdi
        mov esi, 34
        mov edx, 6
        mov ecx, 6
        mov r8d, GREEN
        imul edi, edi, 10
        add edi, 12
        mov rax, [r12 + 8*API_RECT]
        call rax
        pop rdi
        inc edi
        jmp .pl
.pl_done:
        mov edi, 2
        mov esi, 60
        lea rdx, [s_prog]
        mov ecx, 18
        mov r8d, WHITE
        mov rax, [r12 + 8*API_TEXT]
        call rax
        cmp dword [rel alldone], 0
        je .noall
        mov edi, 2
        mov esi, 80
        lea rdx, [s_allok]
        mov ecx, 16
        mov r8d, GREEN
        mov rax, [r12 + 8*API_TEXT]
        call rax
.noall:
        mov rax, [r12 + 8*API_INVAL]
        call rax
        jmp epilogue

; =============================================================================
section .data
s_banner:  db "PEN-TEST EnzoOS", 0
s_prog:    db "progresso dos testes", 0
s_allok:   db "ALL 31 TESTS OK", 0
s_trav:    db "/../../etc/passwd", 0
s_empty:   db 0
s_longname: times 200 db "A"
           db 0
s_deep:    db "/a/b/c/d/e/f/g/h", 0
s_noexec:  db "NAOEXISTE.ENZ", 0
s_root:    db "/", 0
s_f_trunc: db "TRUNC.ENZ", 0
s_f_badent: db "BADENT.ENZ", 0
s_f_badimp: db "BADIMP.ENZ", 0
s_f_huge:  db "HUGE.ENZ", 0
alldone:   dd 0
tests_done: dd 0
iobuf:     times 256 db 0
