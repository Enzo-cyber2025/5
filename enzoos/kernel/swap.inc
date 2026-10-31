; =============================================================================
;  EnzoOS — kernel/swap.inc: área de troca (swap) com paginação por demanda
;
;  * A região [HEAP_START, HEAP_START+SWAP_SPAN) do heap ganha tabelas de
;    página de 4 KB (o resto do espaço continua com páginas grandes).
;  * Páginas alocadas por aplicativos (api_alloc) podem ser removidas da
;    memória: o conteúdo vai para a área de troca no disco SATA e a PTE fica
;    não-presente; o frame físico volta para o alocador.
;  * No #PF (vetor 14), se o endereço cai numa página removida, o kernel lê
;    o conteúdo de volta, remapeia e retoma a execução — transparente.
;  * Contabilidade de frames pelo valor da PTE (suporta troca de frame).
; =============================================================================
%ifndef SWAP_INC
%define SWAP_INC

; índice da primeira entrada do PD que cobre o heap (HEAP_START = 4 MB)
%define SWAP_PD_BASE   (HEAP_START >> 21)

section .ktext

; -----------------------------------------------------------------------------
; k_swap_init — exige AHCI + ENZFS com área de troca; constrói as PTs
; -----------------------------------------------------------------------------
k_swap_init:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [ahci_ok], 0
        je .off
        cmp dword [enzfs_ok], 0
        je .off
        mov rax, [enz_super + 32]  ; swap_lba
        test rax, rax
        jz .off
        mov [sw_lba], eax            ; 32-bit: store qword esmagaria sw_slots (dd vizinho)
        ; lê o cabeçalho da área
        mov edi, eax
        mov esi, 1
        mov rdx, sw_hdr
        call ahci_read
        test eax, eax
        jnz .off
        cmp dword [sw_hdr], 0x505753        ; "SWP"
        jne .off
        mov eax, [sw_hdr + 8]               ; slots
        cmp eax, SW_MAXSLOTS
        jbe .sl_ok
        mov eax, SW_MAXSLOTS
.sl_ok:
        mov [sw_slots], eax
        ; zera o bitmap de slots
        lea rdi, [sw_slotbm]
        mov esi, SW_SLOTBM_BYTES
        call k_memzero
        ; ---- constrói as 32 tabelas de página (64 MB) ----
        ; detecta o modo: 1 GB grande ou 2 MB
        mov rax, cr3
        mov r12, [rax]                      ; PML4[0] -> PDPT
        and r12, -4096
        mov rax, [r12]                      ; PDPT[0]
        mov r13, rax
        and r13, -4096         ; endereço do PD (modo 2MB)
        test rax, 0x80                      ; PS -> página grande de 1GB
        jz .mode_2m
        ; ---- modo 1 GB: cria um PD novo ----
        mov edi, 4096
        call k_alloc
        test rax, rax
        jz .off
        mov r14, rax                        ; novo PD
        ; [0, 4 MB) e [SWAP_PD_BASE+32, 1 GB): páginas grandes de 2 MB
        ; (identidade); [4 MB, 68 MB) fica para as PTs do .pt_loop
        mov r15d, 0
.fill_pd_huge:
        cmp r15d, 2
        jb .pd_huge_set
        cmp r15d, SWAP_PD_BASE + 32
        jb .pd_huge_skip
        cmp r15d, 512
        jae .pd_done
.pd_huge_set:
        mov eax, r15d
        shl eax, 21                         ; 2 MB
        or eax, 0x83
        mov [r14 + r15*8], rax
.pd_huge_skip:
        inc r15d
        jmp .fill_pd_huge
.pd_done:
        mov r13, r14
        mov [sw_newpd], r13                 ; PD novo (ligado só no fim!)
        jmp .build_pts
.mode_2m:
        ; já existe um PD — vamos apenas substituir as 32 primeiras entradas
.build_pts:
        xor r15d, r15d                      ; índice da PT
.pt_loop:
        cmp r15d, 32
        jae .pts_done
        mov edi, 4096
        call k_alloc
        test rax, rax
        jz .off
        mov r14, rax                        ; PT
        mov [sw_pts + r15*8], r14
        ; preenche identidade: HEAP_START + i*2MB + j*4KB
        xor ecx, ecx
.fill:
        mov eax, r15d
        shl eax, 21
        mov edx, ecx
        shl edx, 12
        add eax, edx
        add eax, HEAP_START
        or eax, 3
        mov [r14 + rcx*8], rax
        inc ecx
        cmp ecx, 512
        jb .fill
        ; liga a PT no diretório — a PT #i cobre o heap a partir de
        ; HEAP_START + i*2 MB, ou seja, a entrada SWAP_PD_BASE+i do PD
        mov rax, r14
        or rax, 3
        mov rdx, r15
        add rdx, SWAP_PD_BASE
        mov [r13 + rdx*8], rax
        inc r15d
        jmp .pt_loop
.pts_done:
        ; liga o PD novo (modo 1 GB) — agora que as 32 PTs cobrem o heap
        mov rax, [sw_newpd]
        test rax, rax
        jz .no_newpd
        or rax, 3
        mov [r12], rax
.no_newpd:
        ; zera os arrays de estado
        lea rdi, [sw_state]
        mov esi, SW_NPAGES
        call k_memzero
        lea rdi, [sw_owner]
        mov esi, SW_NPAGES
        call k_memzero
        ; invalida a TLB da região
        xor ecx, ecx
        mov eax, HEAP_START
.inv:
        invlpg [rax]
        add rax, 0x200000
        inc ecx
        cmp ecx, 32
        jb .inv
        mov dword [sw_armed], 1
        mov rdi, s_swap_on
        call k_log
        jmp .done
.off:
        mov dword [sw_armed], 0
        mov rdi, s_swap_off
        call k_log
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_pte: rax = endereço virtual -> rax = ponteiro para a PTE (ou 0)
; -----------------------------------------------------------------------------
sw_pte:
        cmp rax, HEAP_START
        jb .no
        cmp rax, HEAP_START + SWAP_SPAN
        jae .no
        mov rdx, rax
        sub rdx, HEAP_START
        shr rdx, 21                         ; índice da PT (0..31)
        mov rcx, [sw_pts + rdx*8]
        test rcx, rcx
        jz .no
        mov rdx, rax
        shr rdx, 12
        and rdx, 511
        lea rax, [rcx + rdx*8]
        ret
.no:
        xor eax, eax
        ret

; -----------------------------------------------------------------------------
; sw_remap_page: rdi = endereço da página — garante PTE presente (identidade).
; Chamado pelo k_alloc ao (re)alocar: uma página cuja PTE foi zerada por um
; free antigo (ou por um swap-out descartado) ficava SEM mapeamento e a
; primeira escrita gerava #PF fatal (sw_fault sem slot nao recupera).
; -----------------------------------------------------------------------------
sw_remap_page:
        push rax
        push rdx
        push rcx
        mov rax, rdi
        call sw_pte
        test rax, rax
        jz .out
        test byte [rax], 1
        jnz .out                        ; já presente
        mov rdx, rdi
        or rdx, 3                       ; identidade RW|P
        mov [rax], rdx
        invlpg [rdi]
.out:
        pop rcx
        pop rdx
        pop rax
        ret

; -----------------------------------------------------------------------------
; sw_track: rdi = início, rsi = bytes, edx = dono (slot do app)
;           marca as páginas como candidatas à remoção
; -----------------------------------------------------------------------------
sw_track:
        push rbx
        push r12
        push r13
        mov r12, rdi
        add rsi, r12                        ; fim
        mov r13d, edx
.pg:
        cmp r12, rsi
        jae .done
        mov rax, r12
        call sw_pte
        test rax, rax
        jz .next
        mov rdx, r12
        sub rdx, HEAP_START
        shr rdx, 12
        mov byte [sw_state + rdx], 1
        mov [sw_owner + rdx], r13b
        mov eax, [sw_lru_ctr]
        inc eax
        mov [sw_lru_ctr], eax
        mov [sw_lru + rdx*4], eax
.next:
        add r12, 4096
        jmp .pg
.done:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_untrack: rdi = início, rsi = bytes — páginas deixam de ser candidatas
; -----------------------------------------------------------------------------
sw_untrack:
        push rbx
        push r12
        push r13
        mov r12, rdi
        add rsi, r12
.pg:
        cmp r12, rsi
        jae .done
        mov rdx, r12
        sub rdx, HEAP_START
        shr rdx, 12
        cmp rdx, SW_NPAGES
        jae .next
        mov byte [sw_state + rdx], 0
.next:
        add r12, 4096
        jmp .pg
.done:
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_slot_alloc -> rax = slot livre ou -1
; -----------------------------------------------------------------------------
sw_slot_alloc:
        push rbx
        xor ebx, ebx
.l:
        cmp ebx, [sw_slots]
        jae .nf
        mov eax, ebx
        shr eax, 3
        mov r8d, 1
        mov ecx, ebx
        and ecx, 7
        shl r8d, cl
        test [sw_slotbm + rax], r8b
        jnz .next
        or [sw_slotbm + rax], r8b
        mov rax, rbx
        pop rbx
        ret
.next:
        inc ebx
        jmp .l
.nf:
        mov rax, -1
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_slot_free: edi = slot
; -----------------------------------------------------------------------------
sw_slot_free:
        mov eax, edi
        shr eax, 3
        mov r8d, 1
        mov ecx, edi
        and ecx, 7
        shl r8d, cl
        not r8d
        and [sw_slotbm + rax], r8b
        ret

; -----------------------------------------------------------------------------
; sw_page_out — remove a página LRU de um app para o disco
;               -> rax = 1 removeu / 0 sem candidato
; -----------------------------------------------------------------------------
sw_page_out:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [sw_armed], 0
        je .none
        ; procura a página com menor LRU entre state=1 e dono >= 0
        xor ecx, ecx
        xor r14d, r14d                      ; melhor índice (0 = nenhum)
        mov r15d, 0x7FFFFFFF                ; menor LRU
.scan:
        cmp ecx, SW_NPAGES
        jae .scan_done
        cmp byte [sw_state + rcx], 1
        jne .scan_next
        movsx rdx, byte [sw_owner + rcx]
        cmp rdx, 0
        jl .scan_next
        mov eax, [sw_lru + rcx*4]
        cmp eax, r15d
        jae .scan_next
        mov r15d, eax
        mov r14d, ecx
.scan_next:
        inc ecx
        jmp .scan
.scan_done:
        test r14d, r14d
        jz .none
        ; endereço virtual da página
        mov r12, r14
        shl r12, 12
        add r12, HEAP_START
        ; frame atual (via PTE)
        mov rax, r12
        call sw_pte
        test rax, rax
        jz .none
        mov rbx, [rax]
        test rbx, 1
        jz .none
        and rbx, -4096         ; endereço do frame (identidade)
        ; slot de troca
        call sw_slot_alloc
        cmp rax, -1
        je .none
        mov r13, rax
        ; DMA: 8 setores a partir do frame
        mov edi, r13d
        imul edi, edi, 8
        mov eax, [sw_lba]
        add edi, eax
        inc edi                             ; +1: cabeçalho
        mov esi, 8
        mov rdx, rbx
        call ahci_write
        test eax, eax
        jnz .none
        ; desmapeia a página
        mov rax, r12
        call sw_pte
        mov qword [rax], 0
        invlpg [r12]
        ; devolve o frame ao alocador
        mov rax, rbx
        sub rax, HEAP_START
        shr rax, 12
        call mark_free
        ; atualiza o estado
        mov byte [sw_state + r14], 2
        mov [sw_slot + r14*2], r13w
        inc dword [sw_out_ctr]
        mov eax, 1
        jmp .out
.none:
        xor eax, eax
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_fault: rax = endereço que gerou #PF -> eax = 1 se paginou de volta
; -----------------------------------------------------------------------------
sw_fault:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [sw_armed], 0
        je .no
        mov r12, rax
        and r12, 0xFFFFFFFFFFFFF000         ; página
        cmp r12, HEAP_START
        jb .no
        mov rax, HEAP_START + SWAP_SPAN
        cmp r12, rax
        jae .no
        mov r13, r12
        sub r13, HEAP_START
        shr r13, 12                         ; índice
        cmp byte [sw_state + r13], 2
        jne .no
        ; lê de volta: aloca um frame
        mov edi, 4096
        call k_alloc
        test rax, rax
        jz .no
        mov r14, rax                        ; frame novo
        movzx edi, word [sw_slot + r13*2]
        imul edi, edi, 8
        mov eax, [sw_lba]
        add edi, eax
        inc edi
        mov esi, 8
        mov rdx, r14
        call ahci_read
        test eax, eax
        jnz .no
        ; remapeia
        mov rax, r12
        call sw_pte
        test rax, rax
        jz .no
        mov rdx, r14
        or rdx, 3
        mov [rax], rdx
        invlpg [r12]
        ; estado
        mov byte [sw_state + r13], 1
        mov eax, [sw_lru_ctr]
        inc eax
        mov [sw_lru_ctr], eax
        mov [sw_lru + r13*4], eax
        mov edi, r13d
        call sw_slot_free
        inc dword [sw_in_ctr]
        inc dword [sw_fault_ctr]
        mov eax, 1
        jmp .out
.no:
        xor eax, eax
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_reclaim: edi = nº de páginas a remover (usado sob pressão de memória)
; -----------------------------------------------------------------------------
sw_reclaim:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12d, edi
        xor r13d, r13d
.loop:
        cmp r13d, r12d
        jae .done
        call sw_page_out
        test eax, eax
        jz .done
        inc r13d
        jmp .loop
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sw_free_frame: rdi = endereço virtual da página — libera o frame pela PTE
;               (chamado pelo k_free quando o swap está ativo)
; FIX: (1) página já livre no bitmap = double-free -> ignora (um free
;          espúrio/duplicado desmapeava página viva e o próximo acesso
;          à sombra gerava #PF fatal — panic com layout dependente);
;      (2) página presente NÃO é mais desmapeada: o frame é devolvido
;          pelo bitmap; o mapeamento identidade fica (k_alloc remapeia
;          na realocação via sw_remap_page).
; -----------------------------------------------------------------------------
sw_free_frame:
        push rbx
        mov rbx, rdi
        ; double-free? página já livre no bitmap -> nada a fazer
        mov rax, rbx
        sub rax, HEAP_START
        shr rax, 12
        call page_is_free
        test rax, rax
        jnz .out
        mov rax, rbx
        call sw_pte
        test rax, rax
        jz .plain
        mov rdx, [rax]
        test rdx, 1
        jz .swapped                         ; não-presente: frame já devolvido
        ; frame presente: devolve pelo bitmap, MANTÉM o mapeamento
        and rdx, -4096
        mov rax, rdx
        sub rax, HEAP_START
        shr rax, 12
        call mark_free
        jmp .out
.swapped:
        mov qword [rax], 0
        invlpg [rbx]
        jmp .out
.plain:
        ; fora do span ou swap desligado: frame identidade
        mov rax, rbx
        sub rax, HEAP_START
        shr rax, 12
        call mark_free
.out:
        pop rbx
        ret

section .kdata
sw_hdr:     times 512 db 0
sw_armed:   dd 0
sw_newpd:   dq 0
sw_lba:     dd 0
sw_slots:   dd 0
sw_out_ctr: dd 0
sw_in_ctr:  dd 0
sw_fault_ctr: dd 0
sw_lru_ctr: dd 0
sw_pts:     times 32 dq 0
align 16
sw_state:   times 16384 db 0
sw_owner:   times 16384 db 0
sw_slot:    times 16384*2 db 0
align 16
sw_lru:     times 16384 dd 0
align 16
sw_slotbm:  times 1024 db 0                ; 8192 slots

s_swap_on:  db "[swap] paginacao por demanda ativa (64 MB)", 10, 0
s_swap_off: db "[swap] area de troca ausente — swap desativado", 10, 0

%endif
