; =============================================================================
;  EnzoOS — kernel/enzfs.inc: ENZFS — sistema de arquivos do EnzoOS
;
;  Disco (setor 0 = superbloco):
;    +0  "ENZFS1.0"     magia
;    +8  dd block_size  (4096)
;    +12 dd nblocks     blocos de 4 KB no volume
;    +16 dd bitmap_blk  bloco do bitmap (1 bit por bloco)
;    +20 dd inode_blk   bloco inicial da tabela de inodes (64 B cada)
;    +24 dd data_blk    primeiro bloco de dados
;    +28 dd n_inodes
;    +32 dq swap_lba    setor da área de troca (0 = nenhuma)
;    +40 dd swap_slots  páginas de 4 KB na área de troca
;
;  Inode (64 B): flags (1=arquivo, 2=diretório), size, blocks[13], ctime
;  Entrada de diretório (32 B): name[24], ino, rsv — nome até 23 bytes
; =============================================================================
%ifndef ENZFS_INC
%define ENZFS_INC

section .ktext

; -----------------------------------------------------------------------------
; k_enzfs_mount — monta o volume do disco AHCI
; -----------------------------------------------------------------------------
k_enzfs_mount:
        cmp dword [ahci_ok], 0
        je .no
        mov edi, 0
        mov esi, 1
        mov rdx, enz_super
        call ahci_read
        test eax, eax
        jnz .no
        ; ---- diag: dwords lidos + PRDBC (bytes transferidos) ----
        push rax
        mov rdi, [enz_super]
        call k_log_hex
        mov rdi, [enz_super + 4]
        call k_log_hex
        mov rdi, [enz_super + 8]
        call k_log_hex
        mov rdi, [enz_super + 32]
        call k_log_hex
        mov edi, [ahci_clb + 4]
        call k_log_hex
        pop rax
        mov eax, [enz_super]
        cmp eax, 0x465A4E45        ; "ENZF" (mkfs: +0 "ENZFS1.0")
        jne .bad
        cmp dword [enz_super + 4], 0x302E3153   ; "S1.0"
        jne .bad
        ; limites suportados pelo cache
        mov eax, [enz_super + 12]  ; nblocks
        cmp eax, 32768
        jbe .nb_ok
        mov eax, 32768
.nb_ok:
        mov [enz_nblocks], eax
        mov eax, [enz_super + 28]  ; n_inodes
        cmp eax, 256
        jbe .ni_ok
        mov eax, 256
.ni_ok:
        mov [enz_ninodes], eax
        ; carrega bitmap (1 bloco)
        mov edi, [enz_super + 16]
        shl edi, 3                 ; bloco -> setor
        mov esi, 8
        mov rdx, enz_bm
        call ahci_read
        test eax, eax
        jnz .bad
        ; carrega inodes (16 KB = 4 blocos)
        mov edi, [enz_super + 20]
        shl edi, 3
        mov esi, 32
        mov rdx, enz_inodes
        call ahci_read
        test eax, eax
        jnz .bad
        mov dword [enzfs_ok], 1
        mov dword [enz_dirty], 0
        mov rdi, s_enzfs_ok
        call k_log
        ret
.bad:
        mov rdi, s_enzfs_bad
        call k_log
.no:
        mov dword [enzfs_ok], 0
        mov rdi, s_enzfs_none
        call k_log
        ret

; -----------------------------------------------------------------------------
; e_inode: edi = ino -> rax = ponteiro para o inode em cache (0 se inválido)
; -----------------------------------------------------------------------------
e_inode:
        cmp edi, [enz_ninodes]
        jae .bad
        mov eax, edi
        shl rax, 6
        add rax, enz_inodes
        ret
.bad:
        xor eax, eax
        ret

; -----------------------------------------------------------------------------
; e_dirent_find: edi = ino do diretório, rsi = nome -> rax = ino ou -1
; -----------------------------------------------------------------------------
e_dirent_find:
        push rbx
        push r12
        push r13
        push r14
        mov r12, rsi               ; nome
        call e_inode
        test rax, rax
        jz .nf
        mov rbx, rax
        xor r13d, r13d             ; índice de bloco
.blk:
        cmp r13d, 13
        jae .nf
        mov eax, [rbx + 8 + r13*4] ; blocks[i]
        test eax, eax
        jz .nf
        mov r14d, eax
        mov edi, r14d
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .next
        xor ecx, ecx
.ent:
        cmp ecx, 128
        jae .next
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx               ; rax = entrada
        cmp byte [rax], 0
        je .ent_next
        mov rdi, rax
        mov rsi, r12
        call k_strcasecmp
        test rax, rax
        jz .found
.ent_next:
        inc ecx
        jmp .ent
.next:
        inc r13d
        jmp .blk
.found:
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        mov eax, [rax + 24]        ; ino
        jmp .done
.nf:
        mov rax, -1
.done:
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_path: rdi = caminho ("/a/b") -> rax = ino ou -1
; -----------------------------------------------------------------------------
e_path:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi               ; caminho
        xor ebx, ebx               ; ino atual = raiz
.walk:
        movzx eax, byte [r12]
        test eax, eax
        jz .done
        cmp al, '/'
        jne .have
        inc r12
        jmp .walk
.have:
        ; extrai o componente até '/' ou fim
        lea r13, [enz_tmpname]
        lea r14, [enz_tmpname + 23]
.copy:
        movzx eax, byte [r12]
        test eax, eax
        jz .copied
        cmp al, '/'
        je .copied
        cmp r13, r14
        jae .copied
        mov [r13], al
        inc r13
        inc r12
        jmp .copy
.copied:
        mov byte [r13], 0
        test r13, r13
        jz .done
        cmp byte [enz_tmpname], 0
        je .skip
        mov edi, ebx
        mov rsi, enz_tmpname
        call e_dirent_find
        cmp rax, -1
        je .nf
        mov ebx, eax
.skip:
        jmp .walk
.done:
        mov rax, rbx
        jmp .out
.nf:
        mov rax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_list: edi = ino do dir, esi = índice (0..), rdx = buf nome (24 B)
;         -> rax = 0 fim / 1 arquivo / 2 diretório / -1 erro
; -----------------------------------------------------------------------------
e_list:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r15, rdx               ; buf do nome
        mov r14d, esi              ; índice desejado
        call e_inode
        test rax, rax
        jz .err
        mov rbx, rax
        xor r12d, r12d             ; contador de entradas válidas
        xor r13d, r13d             ; bloco
.blk:
        cmp r13d, 13
        jae .eof
        mov eax, [rbx + 8 + r13*4]
        test eax, eax
        jz .eof
        mov edi, eax
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .next
        xor ecx, ecx
.ent:
        cmp ecx, 128
        jae .next
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        cmp byte [rax], 0
        je .ent_next
        cmp r12d, r14d
        je .hit
        inc r12d
.ent_next:
        inc ecx
        jmp .ent
.next:
        inc r13d
        jmp .blk
.hit:
        ; copia o nome
        mov rdi, r15
        mov rsi, rax
        mov edx, 24
        call k_memcpy
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        mov rdi, [rax + 24]
        call e_inode
        test rax, rax
        jz .err
        mov eax, [rax]
        jmp .out
.eof:
        xor eax, eax
        jmp .out
.err:
        mov eax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_free_ino -> rax = índice de inode livre (ou -1)
; -----------------------------------------------------------------------------
e_free_ino:
        xor ecx, ecx
.l:
        cmp ecx, [enz_ninodes]
        jae .nf
        mov eax, ecx
        shl rax, 6
        cmp dword [enz_inodes + rax], 0
        jne .next
        mov rax, rcx
        ret
.next:
        inc ecx
        jmp .l
.nf:
        mov rax, -1
        ret

; -----------------------------------------------------------------------------
; e_balloc -> rax = bloco livre (marca como usado) ou -1
; -----------------------------------------------------------------------------
e_balloc:
        push rbx
        xor ebx, ebx
.l:
        cmp ebx, [enz_nblocks]
        jae .nf
        mov eax, ebx
        shr eax, 3
        mov r8d, 1
        mov ecx, ebx
        and ecx, 7
        shl r8d, cl
        test [enz_bm + rax], r8b
        jnz .next
        or [enz_bm + rax], r8b
        mov dword [enz_dirty], 1
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
; e_bfree:
        mov eax, edi
        shr eax, 3
        mov r8d, 1
        mov ecx, edi
        and ecx, 7
        shl r8d, cl
        not r8d
        and [enz_bm + rax], r8b
        mov dword [enz_dirty], 1
        ret

; -----------------------------------------------------------------------------
e_bfree:
        mov eax, edi
        mov ecx, edi
        shr eax, 3
        and ecx, 7
        mov edx, 1
        shl edx, cl
        not edx
        and [enz_bm + rax], dl
        mov dword [enz_dirty], 1
        ret

; -----------------------------------------------------------------------------
; e_dir_add: edi = ino do dir, rsi = nome, edx = ino novo -> rax = 0/-1
; -----------------------------------------------------------------------------
e_dir_add:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rsi               ; nome
        mov r13d, edx              ; ino
        call e_inode
        test rax, rax
        jz .err
        mov rbx, rax
        xor r14d, r14d
.blk:
        cmp r14d, 13
        jae .err
        mov eax, [rbx + 8 + r14*4]
        test eax, eax
        jnz .have
        ; aloca um bloco novo para o diretório
        call e_balloc
        cmp rax, -1
        je .err
        mov [rbx + 8 + r14*4], eax
        mov edi, eax
        shl edi, 3
        mov rsi, enz_dirbuf
        mov edx, 4096
        call k_memzero
        mov edi, [rbx + 8 + r14*4]
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_write
        test eax, eax
        jnz .err
        mov eax, [rbx + 8 + r14*4]
.have:
        mov r15d, eax
        mov edi, r15d
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .err
        ; procura entrada vazia
        xor ecx, ecx
.ent:
        cmp ecx, 128
        jae .nextblk
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        cmp byte [rax], 0
        je .free
        inc ecx
        jmp .ent
.nextblk:
        inc r14d
        jmp .blk
.free:
        mov rdi, rax
        mov rsi, r12
        mov edx, 24
        call k_memcpy
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        mov [rax + 24], r13d
        ; grava o bloco do diretório
        mov edi, r15d
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_write
        test eax, eax
        jnz .err
        ; atualiza o tamanho do diretório
        mov eax, [rbx + 4]
        add eax, 32
        mov [rbx + 4], eax
        mov dword [enz_dirty], 1
        xor eax, eax
        jmp .out
.err:
        mov eax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_creat: rdi = caminho, esi = tipo (1 arquivo, 2 dir) -> rax = ino ou -1
; -----------------------------------------------------------------------------
e_creat:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [enzfs_ok], 0
        je .err
        mov r12, rdi               ; caminho
        mov r13d, esi              ; tipo
        ; já existe?
        mov rdi, r12
        call e_path
        cmp rax, -1
        jne .err
        ; separa pai/último componente
        mov r14, r12
        xor ecx, ecx
.findend:
        mov al, [r14]
        test al, al
        jz .endfound
        inc r14
        inc ecx
        jmp .findend
.endfound:
        ; r14 -> fim; volta até '/'
        mov r15, r14
.back:
        cmp r15, r12
        jbe .root
        dec r15
        cmp byte [r15], '/'
        jne .back
        ; nome = r15+1
        lea rdi, [r15 + 1]
        mov rsi, enz_tmpname
        mov edx, 23
        call k_memcpy
        mov byte [enz_tmpname + 23], 0
        ; constrói caminho do pai em enz_parent (zerado)
        lea rdi, [enz_parent]
        mov esi, 64
        call k_memzero
        mov rsi, r12
        lea rdi, [enz_parent]
        mov rdx, r15
        sub rdx, r12               ; bytes do pai
        cmp rdx, 62
        jbe .plen
        mov rdx, 62
.plen:
        call k_memcpy
        cmp byte [enz_parent], 0
        jne .pdad
        mov dword [enz_parent], '/'
        mov byte [enz_parent + 1], 0
.pdad:
        lea rdi, [enz_parent]
        call e_path
        cmp rax, -1
        je .err
        mov rbx, rax               ; ino do pai
        ; inode livre
        call e_free_ino
        cmp rax, -1
        je .err
        mov r14d, eax              ; novo ino
        ; inicializa o inode
        mov edi, r14d
        call e_inode
        test rax, rax
        jz .err
        mov rcx, rax
        mov eax, r13d
        mov [rcx], eax             ; flags
        mov dword [rcx + 4], 0     ; size
        ; zera blocks
        xor eax, eax
        mov [rcx + 8], eax
        mov [rcx + 12], eax
        mov [rcx + 16], eax
        mov [rcx + 20], eax
        mov [rcx + 24], eax
        mov [rcx + 28], eax
        mov [rcx + 32], eax
        mov [rcx + 36], eax
        mov [rcx + 40], eax
        mov [rcx + 44], eax
        mov [rcx + 48], eax
        mov [rcx + 52], eax
        mov [rcx + 56], eax
        mov eax, [uptime_ms]
        mov [rcx + 60], eax        ; ctime (ms de uptime como marca)
        ; adiciona ao diretório pai
        mov edi, ebx
        mov rsi, enz_tmpname
        mov edx, r14d
        call e_dir_add
        test eax, eax
        jnz .err
        mov dword [enz_dirty], 1
        call e_flush
        mov rax, r14
        jmp .out
.root:
.err:
        mov rax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_read: rdi = ino, rsi = destino, rdx = deslocamento, rcx = bytes
;         -> rax = bytes lidos
; -----------------------------------------------------------------------------
e_read:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rsi               ; destino
        mov r13, rdx               ; offset
        mov r14, rcx               ; restante
        call e_inode
        test rax, rax
        jz .err
        mov rbx, rax
        mov eax, [rbx + 4]         ; size
        sub rax, r13
        cmp rax, r14
        jbe .sz_ok
        mov r14, rax               ; trunca no tamanho
.sz_ok:
        xor r15d, r15d             ; lidos
.loop:
        test r14d, r14d
        jz .done
        mov eax, r13d
        shr eax, 12                ; índice do bloco
        cmp eax, 13
        jae .done
        mov edi, [rbx + 8 + rax*4]
        test edi, edi
        jz .done
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .done
        ; deslocamento dentro do bloco
        mov eax, r13d
        and eax, 0xFFF
        lea r8, [enz_dirbuf]
        add r8, rax
        ; bytes a copiar neste bloco
        mov ecx, 4096
        sub ecx, eax
        cmp ecx, r14d
        jbe .cp
        mov ecx, r14d
.cp:
        mov rdi, r12
        mov rsi, r8
        mov rdx, rcx
        push rcx
        call k_memcpy
        pop rcx
        add r12, rcx
        add r13, rcx
        sub r14, rcx
        add r15, rcx
        jmp .loop
.done:
        mov rax, r15
        jmp .out
.err:
        xor eax, eax
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_write: rdi = ino, rsi = origem, rdx = deslocamento, rcx = bytes
;          -> rax = bytes gravados (-1 erro)
; -----------------------------------------------------------------------------
e_write:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [enzfs_ok], 0
        je .err
        mov r12, rsi               ; origem
        mov r13, rdx               ; offset
        mov r14, rcx               ; restante
        call e_inode
        test rax, rax
        jz .err
        mov rbx, rax
        xor r15d, r15d             ; gravados
.loop:
        test r14d, r14d
        jz .done
        mov eax, r13d
        shr eax, 12
        cmp eax, 13
        jae .full
        cmp dword [rbx + 8 + rax*4], 0
        jne .have
        push rax
        call e_balloc
        pop rcx
        cmp rax, -1
        je .full
        mov [rbx + 8 + rcx*4], eax
.have:
        mov eax, r13d
        shr eax, 12
        mov edi, [rbx + 8 + rax*4]
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .done
        ; deslocamento no bloco
        mov eax, r13d
        and eax, 0xFFF
        mov r9, enz_dirbuf
        add r9, rax
        mov ecx, 4096
        sub ecx, eax
        cmp ecx, r14d
        jbe .cp
        mov ecx, r14d
.cp:
        mov rdi, r9
        mov rsi, r12
        mov rdx, rcx
        push rcx
        call k_memcpy
        pop rcx
        ; grava o bloco
        mov eax, r13d
        shr eax, 12
        mov edi, [rbx + 8 + rax*4]
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_write
        test eax, eax
        jnz .done
        add r12, rcx
        add r13, rcx
        sub r14, rcx
        add r15, rcx
        ; atualiza o tamanho
        mov eax, r13d
        cmp eax, [rbx + 4]
        jbe .nosz
        mov [rbx + 4], eax
.nosz:
        mov dword [enz_dirty], 1
        jmp .loop
.full:
.done:
        call e_flush
        mov rax, r15
        jmp .out
.err:
        mov rax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_unlink: rdi = caminho -> rax = 0/-1 (remove arquivo ou diretório vazio)
; -----------------------------------------------------------------------------
e_unlink:
        push rbx
        push r12
        push r13
        push r14
        push r15
        cmp dword [enzfs_ok], 0
        je .err
        mov r12, rdi
        call e_path
        cmp rax, -1
        je .err
        mov r13, rax               ; ino
        ; não remove a raiz
        test r13d, r13d
        jz .err
        ; separa pai/nome
        mov r14, r12
.back:
        mov al, [r14]
        test al, al
        jz .b2
        inc r14
        jmp .back
.b2:
        mov r15, r14
.back2:
        cmp r15, r12
        jbe .err
        dec r15
        cmp byte [r15], '/'
        jne .back2
        lea rdi, [r15 + 1]
        mov rsi, enz_tmpname
        mov edx, 23
        call k_memcpy
        mov byte [enz_tmpname + 23], 0
        ; caminho do pai (zerado)
        lea rdi, [enz_parent]
        mov esi, 64
        call k_memzero
        mov rsi, r12
        lea rdi, [enz_parent]
        mov rdx, r15
        sub rdx, r12
        cmp rdx, 62
        jbe .plen2
        mov rdx, 62
.plen2:
        call k_memcpy
        cmp byte [enz_parent], 0
        jne .pd
        mov dword [enz_parent], '/'
        mov byte [enz_parent + 1], 0
.pd:
        lea rdi, [enz_parent]
        call e_path
        cmp rax, -1
        je .err
        mov ebx, eax               ; pai
        ; se diretório, só remove se vazio
        mov edi, r13d
        call e_inode
        mov rcx, rax
        cmp dword [rcx], 2
        jne .notdir
        cmp dword [rcx + 4], 0
        jne .err                   ; diretório com conteúdo
.notdir:
        ; libera os blocos do inode (rdx = índice, rcx = inode)
        xor edx, edx
.freeb:
        cmp edx, 13
        jae .freed
        mov edi, [rcx + 8 + rdx*4]
        test edi, edi
        jz .freenext
        push rcx
        push rdx
        call e_bfree
        pop rdx
        pop rcx
.freenext:
        inc edx
        jmp .freeb
.freed:
        ; zera o inode
        mov dword [rcx], 0
        mov dword [rcx + 4], 0
        ; remove a entrada do diretório pai
        mov edi, ebx
        mov rsi, enz_tmpname
        call e_dir_del
        test eax, eax
        jnz .err
        mov dword [enz_dirty], 1
        call e_flush
        xor eax, eax
        jmp .out
.err:
        mov eax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_dir_del: edi = ino do dir, rsi = nome -> rax = 0/-1 (zera a entrada)
; -----------------------------------------------------------------------------
e_dir_del:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rsi
        call e_inode
        test rax, rax
        jz .err
        mov rbx, rax
        xor r13d, r13d
.blk:
        cmp r13d, 13
        jae .err
        mov eax, [rbx + 8 + r13*4]
        test eax, eax
        jz .err
        mov r14d, eax
        mov edi, r14d
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_read
        test eax, eax
        jnz .next
        xor ecx, ecx
.ent:
        cmp ecx, 128
        jae .next
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        cmp byte [rax], 0
        je .ent_next
        mov rdi, rax
        mov rsi, r12
        call k_strcasecmp
        test rax, rax
        jnz .ent_next
        ; achou: zera a entrada
        mov rax, enz_dirbuf
        shl rcx, 5
        add rax, rcx
        mov dword [rax], 0
        mov dword [rax + 4], 0
        mov dword [rax + 8], 0
        mov dword [rax + 12], 0
        mov dword [rax + 16], 0
        mov dword [rax + 20], 0
        mov dword [rax + 24], 0
        mov dword [rax + 28], 0
        mov edi, r14d
        shl edi, 3
        mov esi, 8
        mov rdx, enz_dirbuf
        call ahci_write
        test eax, eax
        jnz .err
        ; diminui o tamanho do diretório
        mov eax, [rbx + 4]
        sub eax, 32
        jns .sz
        xor eax, eax
.sz:
        mov [rbx + 4], eax
        xor eax, eax
        jmp .out
.ent_next:
        inc ecx
        jmp .ent
.next:
        inc r13d
        jmp .blk
.err:
        mov eax, -1
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; e_flush — grava bitmap + inodes no disco
; -----------------------------------------------------------------------------
e_flush:
        cmp dword [enz_dirty], 0
        je .done
        mov edi, [enz_super + 16]
        shl edi, 3
        mov esi, 8
        mov rdx, enz_bm
        call ahci_write
        mov edi, [enz_super + 20]
        shl edi, 3
        mov esi, 32
        mov rdx, enz_inodes
        call ahci_write
        mov dword [enz_dirty], 0
.done:
        ret

; -----------------------------------------------------------------------------
; e_size: rdi = ino -> rax = tamanho (ou -1)
; -----------------------------------------------------------------------------
e_size:
        call e_inode
        test rax, rax
        jz .nf
        mov eax, [rax + 4]
        ret
.nf:
        mov rax, -1
        ret

; -----------------------------------------------------------------------------
; e_stat: rdi = ino -> rax = flags do inode (1/2) ou -1
; -----------------------------------------------------------------------------
e_stat:
        call e_inode
        test rax, rax
        jz .nf
        mov eax, [rax]
        ret
.nf:
        mov rax, -1
        ret

section .kdata
enz_super:  times 512 db 0
align 4096
enz_bm:     times 4096 db 0         ; bitmap de blocos (32k blocos)
enz_inodes: times 256*64 db 0       ; cache de inodes
enz_dirbuf: times 4096 db 0         ; bloco de trabalho
enz_tmpname: times 24 db 0
enz_parent: times 64 db 0
enzfs_ok:   dd 0
enz_dirty:  dd 0
enz_nblocks: dd 0
enz_ninodes: dd 0

s_enzfs_ok:   db "[enzfs] volume montado", 10, 0
s_enzfs_bad:  db "[enzfs] superbloco invalido", 10, 0
s_enzfs_none: db "[enzfs] sem volume (FS de dados desativado)", 10, 0

%endif
