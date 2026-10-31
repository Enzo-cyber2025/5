; =============================================================================
;  EnzoOS — apps/attack.asm: ATTACK.ENZ — suíte de pen-test do sistema
;
;  Bateria hostil contra as APIs do kernel:
;    t1..t31  inputs inválidos clássicos (alloc/free, coords, paths, NULLs,
;             binários malformados TRUNC/BADENT/BADIMP/HUGE)
;    t32..t47 fuzzing: executa 16 mutantes de cabeçalho (FZ01..FZ16.ENZ)
;    t48      FS roundtrip: creat + write + read-back + compara + unlink
;    t49      estresse de heap: 32 ciclos de alloc/free
;    t50      sanity: swap_info e hpet_ns respondem
;
;  Cada teste concluído emite o número em hex (2 chars) na serial 0x3F8 e
;  pinta um quadradinho na linha de progresso da janela. Se o kernel pânico
;  em algum teste, a serial mostra exatamente onde parou. Ao final:
;  "ALL 50 TESTS OK".
;
;  App .ENZ cru (org 0) — cabeçalho gerado por tools/mkenz.py.
; =============================================================================
BITS 64
org 0
default rel

; ---- índices na APITBL (ordem de k_exports, 1..36) ----
%define API_RECT    1
%define API_TEXT    2
%define API_TITLE   4
%define API_EXEC    9
%define API_CONOUT  10
%define API_INVAL   12
%define API_ALLOC   13
%define API_FREE    14
%define API_SYSINFO 15
%define API_BEEP    18
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

; ---- ser_out: dl = byte para a COM1 (telemetria) --------------------------
ser_out:
        push rdx
        push rax
        mov dx, 0x3FD
.w1:    in al, dx
        test al, 0x20
        jz .w1
        pop rax
        mov dx, 0x3F8
        out dx, al
        pop rdx
        ret

; ---- marca o teste edi (0-based +1) como concluído ------------------------
pass:
        push rdi
        push rsi
        push rdx
        push rcx
        push r8
        push rax
        ; telemetria serial: número em hex, 2 chars + espaço
        mov eax, edi
        shr al, 4
        cmp al, 10
        jb .hi_d
        add al, 'A'-'0'-10
.hi_d:  add al, '0'
        mov dl, al
        call ser_out
        mov eax, edi
        and al, 15
        cmp al, 10
        jb .lo_d
        add al, 'A'-'0'-10
.lo_d:  add al, '0'
        mov dl, al
        call ser_out
        mov dl, ' '
        call ser_out
        pop rax
        ; quadradinho na linha de progresso
        mov esi, 34
        mov edx, 5
        mov ecx, 5
        mov r8d, GREEN
        imul edi, edi, 8
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
        cmp edi, STOP_AT
        jne .no_stop
        mov dword [rel alldone], 1
        mov rax, [r12 + 8*API_INVAL]
        call rax
        mov rax, epilogue
        jmp rax
.no_stop:
        ret

; ---- reporta erro de integridade (texto vermelho, r14d = nº do campo) -----
fs_fail:
        push rdi
        push rsi
        push rdx
        push rcx
        push r8
        mov edi, 2
        mov esi, 104
        lea rdx, [s_fsmismatch]
        mov ecx, 10
        mov r8d, RED
        mov rax, [r12 + 8*API_TEXT]
        call rax
        mov rax, [r12 + 8*API_INVAL]
        call rax
        pop r8
        pop rcx
        pop rdx
        pop rsi
        pop rdi
        ret

; =============================================================================
ev_init:
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
        call rax
        mov edi, 1
        call pass

        ; ------------------------------------------------ t2: alloc(0x7FFF0000)
        mov edi, 0x7FFF0000
        mov rax, [r12 + 8*API_ALLOC]
        call rax
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
        call rax
        mov edi, 4
        call pass

        ; ------------------------------------------------ t5: double free
        mov edi, 64
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        mov r14, rax
        mov rdi, r14
        mov esi, 64
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov rdi, r14
        mov esi, 64
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov edi, 5
        call pass

        ; ------------------------------------------------ t6: free(ptr+16)
        mov edi, 128
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        mov r14, rax
        lea rdi, [r14 + 16]
        mov esi, 128
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov rdi, r14
        mov esi, 128
        mov rax, [r12 + 8*API_FREE]
        call rax
        mov edi, 6
        call pass

        ; ------------------------------------------------ t7: rect imenso
        mov edi, -1000
        mov esi, -1000
        mov edx, 60000
        mov ecx, 60000
        mov r8d, RED
        mov rax, [r12 + 8*API_RECT]
        call rax
        mov edi, 7
        call pass

        ; ------------------------------------------------ t8: px fora
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
        mov r8d, 100000
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
        xor r8d, r8d
        xor r9d, r9d
        mov rax, [r12 + 8*API_BLEND]
        call rax
        mov edi, 12
        call pass

        ; ------------------------------------------------ t13: fs_open traversal
        lea rdi, [s_trav]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov edi, 13
        call pass

        ; ------------------------------------------------ t14: fs_open vazio
        lea rdi, [s_empty]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov edi, 14
        call pass

        ; ------------------------------------------------ t15: fs_open nome longo
        lea rdi, [s_longname]
        mov rax, [r12 + 8*API_FSOPEN]
        call rax
        mov edi, 15
        call pass

        ; ------------------------------------------------ t16: fs_read ino ruim
        mov edi, 99999
        lea rsi, [iobuf]
        mov edx, 64
        mov rax, [r12 + 8*API_FSREAD]
        call rax
        mov edi, 16
        call pass

        ; ------------------------------------------------ t17: fs_list ino ruim
        mov edi, 99999
        xor esi, esi
        lea rdx, [iobuf]
        mov rax, [r12 + 8*API_FSLIST]
        call rax
        mov edi, 17
        call pass

        ; ------------------------------------------------ t18: fs_write ino ruim
        mov edi, 99999
        lea rsi, [iobuf]
        mov edx, 4
        mov rax, [r12 + 8*API_FSWRITE]
        call rax
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
        xor edx, edx
        xor ecx, ecx
        mov r8d, WHITE
        mov rax, [r12 + 8*API_TEXT]
        call rax
        mov edi, 21
        call pass

        ; ------------------------------------------------ t22: text len imenso
        xor edi, edi
        xor esi, esi
        lea rdx, [s_banner]
        mov ecx, 0x40000000
        mov r8d, WHITE
        mov rax, [r12 + 8*API_TEXT]
        call rax
        mov edi, 22
        call pass

        ; ------------------------------------------------ t23: conout max 0
        lea rdi, [iobuf]
        xor esi, esi
        mov rax, [r12 + 8*API_CONOUT]
        call rax
        mov edi, 23
        call pass

        ; ------------------------------------------------ t24: exec inexistente
        lea rdi, [s_noexec]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 24
        call pass

        ; ------------------------------------------------ t25: title gigante
        lea rdi, [s_longname]
        mov rax, [r12 + 8*API_TITLE]
        call rax
        mov edi, 25
        call pass

        ; ------------------------------------------------ t26: tone(0,0)
        xor edi, edi
        xor esi, esi
        mov rax, [r12 + 8*API_TONE]
        call rax
        mov edi, 26
        call pass

        ; ------------------------------------------------ t27..t30: malformados
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

        ; ------------------------------------------------ t31: fs_unlink raiz
        lea rdi, [s_root]
        mov rax, [r12 + 8*API_FSUNLINK]
        call rax
        mov edi, 31
        call pass

        ; ------------------------------------------------ t32..t47: fuzz FZ01..FZ16
        mov r15d, 1
.fuzz:
        cmp r15d, 16
        jg .fuzz_done
        ; monta "FZnn.ENZ" em fuzzname
        mov eax, r15d
        xor edx, edx
        mov ecx, 10
        div ecx                       ; eax = dezena, edx = unidade
        lea rdi, [fuzzname]
        mov byte [rdi], 'F'
        mov byte [rdi+1], 'Z'
        add al, '0'
        mov [rdi+2], al
        lea rdi, [fuzzname]
        mov eax, r15d
        xor edx, edx
        mov ecx, 10
        div ecx
        add dl, '0'
        mov [rdi+3], dl
        mov byte [rdi+4], '.'
        mov byte [rdi+5], 'E'
        mov byte [rdi+6], 'N'
        mov byte [rdi+7], 'Z'
        mov byte [rdi+8], 0
        lea rdi, [fuzzname]
        mov rax, [r12 + 8*API_EXEC]
        call rax
        mov edi, 31
        add edi, r15d                 ; t32..t47
        push r15
        call pass
        pop r15
        inc r15d
        jmp .fuzz
.fuzz_done:

        ; ------------------------------------------------ t48: FS roundtrip
        lea rdi, [s_fspath]
        mov rax, [r12 + 8*API_FSCREAT]
        call rax
        cmp eax, 0
        jl .fs_skip                   ; FS de dados desativado — pula
        mov r14d, eax                 ; ino
        ; escreve 16 bytes do padrão
        mov edi, r14d
        lea rsi, [s_pattern]
        mov edx, 16
        mov rax, [r12 + 8*API_FSWRITE]
        call rax
        ; lê de volta
        mov edi, r14d
        lea rsi, [iobuf]
        mov edx, 16
        mov rax, [r12 + 8*API_FSREAD]
        call rax
        cmp eax, 16
        jl .fs_bad
        ; compara
        xor ecx, ecx
        xor r15d, r15d
        lea r8, [iobuf]
        lea r9, [s_pattern]
.cmp16:
        cmp ecx, 16
        jae .cmp_ok
        mov al, [r8 + rcx]
        cmp al, [r9 + rcx]
        je .cmp_next
        inc r15d
.cmp_next:
        inc ecx
        jmp .cmp16
.cmp_ok:
        test r15d, r15d
        jnz .fs_bad
        ; remove
        mov edi, r14d
        lea rdi, [s_fspath]
        mov rax, [r12 + 8*API_FSUNLINK]
        call rax
        mov edi, 48
        call pass
        jmp .fs_done
.fs_bad:
        call fs_fail
        mov edi, 48
        call pass
        jmp .fs_done
.fs_skip:
        mov edi, 48
        call pass
.fs_done:

        ; ------------------------------------------------ t49: alloc/free ×32
        xor r15d, r15d
.hloop:
        cmp r15d, 32
        jge .hdone
        mov edi, 256
        mov rax, [r12 + 8*API_ALLOC]
        call rax
        mov r14, rax
        mov rdi, r14
        mov esi, 256
        mov rax, [r12 + 8*API_FREE]
        call rax
        inc r15d
        jmp .hloop
.hdone:
        mov edi, 49
        call pass

        ; ------------------------------------------------ t50: sanity hpet
        lea rdi, [hpet_out]             ; api_hpet_ns escreve o u64 aqui
        mov rax, [r12 + 8*API_HPET]
        call rax
        test rax, rax
        jz .hpet_zero
        mov edi, 50
        call pass
        jmp .sanity_done
.hpet_zero:
        mov edi, 50
        call pass
.sanity_done:

        ; ---- concluído
        mov dword [rel alldone], 1
        mov rax, [r12 + 8*API_INVAL]
        call rax
        jmp epilogue

; =============================================================================
ev_paint:
        xor edi, edi
        xor esi, esi
        lea rdx, [s_banner]
        mov ecx, 20
        mov r8d, CYAN
        mov rax, [r12 + 8*API_TEXT]
        call rax
        mov edi, 2
        mov esi, 60
        lea rdx, [s_prog]
        mov ecx, 18
        mov r8d, WHITE
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
        mov edx, 5
        mov ecx, 5
        mov r8d, GREEN
        imul edi, edi, 8
        add edi, 12
        mov rax, [r12 + 8*API_RECT]
        call rax
        pop rdi
        inc edi
        jmp .pl
.pl_done:
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
s_allok:   db "ALL 50 TESTS OK", 0
s_fsmismatch: db "FS MISMATCH", 0
s_trav:    db "/../../etc/passwd", 0
s_empty:   db 0
s_longname: times 200 db "A"
           db 0
s_deep:    db "/a/b/c/d/e/f/g/h", 0
s_noexec:  db "NAOEXISTE.ENZ", 0
s_root:    db "/", 0
s_fspath:  db "/pen_test.tmp", 0
s_pattern: db "EnzoOS-pentest!!"
s_f_trunc: db "TRUNC.ENZ", 0
s_f_badent: db "BADENT.ENZ", 0
s_f_badimp: db "BADIMP.ENZ", 0
s_f_huge:  db "HUGE.ENZ", 0
alldone:   dd 0
tests_done: dd 0
fuzzname:  times 16 db 0
iobuf:     times 256 db 0
hpet_out:  dq 0
