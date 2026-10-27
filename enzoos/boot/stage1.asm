; =============================================================================
;  EnzoOS — boot/stage1.asm
;  Bootloader primário e secundário, 100% Assembly (NASM), código próprio.
;
;  Parte A (primeiros 512 bytes, carregada em 0x7C00):
;    - via El Torito no-emulação (CD/DVD) ou MBR híbrido (USB)
;    - detecta o tamanho de setor (2048 no CD, 512 no disco) e carrega a
;      imagem completa (kernel + CEFS) para 0x10000; salta para a Parte B
;
;  Parte B (offset 0x200, roda em 0x10200):
;    - E820, A20, VBE (1024x768x32 com LFB), parâmetros de boot
;    - modo protegido -> modo longo (páginas de 1GB ou 2MB, PAT/WC no LFB)
;    - copia o KERNEL.BIN (entrada 0 do CEFS) para 0x100000 e salta
;
;  Layout da imagem de boot:
;    +0x0000 parte A (512 bytes)   +0x0200 parte B (até 0x2000)
;    +0x2000 CEFS — KERNEL.BIN é a entrada 0
;
;  Patch do mkiso.py na parte A (offset 0x1E0):
;    +0x1E0 u32 LBA da imagem (setores de 2048)  +0x1E4 u32 tamanho (bytes)
;    +0x1E8 u32 offset do CEFS (0x2000)          +0x1EC u32 0x5A5AA5A5
; =============================================================================

%define IMG_BASE   0x10000
%define CEFS_OFF   0x2000
%define DAP        0x0500
%define AH48BUF    0x0520
%define BP         0x0E00

BITS 16
; ---------------------------------------------------------------------------
; PARTE A
; ---------------------------------------------------------------------------
section .text vstart=0x7C00

start:
        cli
        xor ax, ax
        mov ds, ax
        mov es, ax
        mov ss, ax
        mov sp, 0x7B00
        sti
        cld
        mov [bdrv], dl

        mov si, msgA1
        call bprint

        cmp dword [0x7C00+0x1EC], 0x5A5AA5A5
        jne err_img

        mov dl, [bdrv]
        mov ah, 0x41
        mov bx, 0x55AA
        int 0x13
        jc err_nodisk
        cmp bx, 0xAA55
        jne err_nodisk

        ; tamanho de setor: CD no-emulação = 2048; disco consulta AH=48h
        mov word [secsize], 512
        mov word [mult], 4
        mov dl, [bdrv]
        cmp dl, 0xE0
        jb .disco
        mov word [secsize], 2048
        mov word [mult], 1
        jmp .tem
.disco:
        mov word [AH48BUF], 30
        mov di, AH48BUF
        mov ah, 0x48
        int 0x13
        jc .tem
        cmp word [AH48BUF+24], 2048
        jne .tem
        mov word [secsize], 2048
        mov word [mult], 1
.tem:

        mov eax, [0x7C00+0x1E0]
        movzx ecx, word [mult]
        mul ecx
        mov [lba_cur], eax

        xor eax, eax
        mov [done], eax
.rdloop:
        mov eax, [0x7C00+0x1E4]
        sub eax, [done]
        jbe .rdfim                 ; concluído também quando ultrapassa (CF)
        cmp eax, 32768
        jbe .rdsize_ok
        mov eax, 32768
.rdsize_ok:
        mov edi, IMG_BASE
        add edi, [done]
        mov cx, di
        jcxz .rdblocks
        neg cx
        cmp ecx, eax
        jae .rdblocks
        movzx eax, cx
.rdblocks:
        mov ecx, [secsize]
        add eax, ecx
        dec eax
        xor edx, edx
        div ecx
        cmp eax, 64
        jbe .rdcount_ok
        mov eax, 64
.rdcount_ok:
        mov [DAP+2], ax
        mov ax, di
        and ax, 0x0F
        mov [DAP+4], ax
        mov eax, edi
        shr eax, 4
        mov [DAP+6], ax
        mov eax, [lba_cur]
        mov [DAP+8], eax
        mov dword [DAP+12], 0
        mov byte [tries], 4
.rdretry:
        mov si, DAP
        mov dl, [bdrv]
        mov ah, 0x42
        int 0x13
        jnc .rdok
        dec byte [tries]
        jz err_read
        xor ah, ah
        mov dl, [bdrv]
        int 0x13
        jmp .rdretry
.rdok:
        call bdot
        movzx eax, word [DAP+2]
        add [lba_cur], eax
        mov ecx, [secsize]
        mul ecx
        add [done], eax
        jmp .rdloop
.rdfim:
        mov si, msgB0
        call bprint
        push word 0x1000
        push word 0x0200
        retf

err_img:
        mov si, msgE1
        jmp err_halt
err_nodisk:
        mov si, msgE2
        jmp err_halt
err_read:
        mov si, msgE3
err_halt:
        call bprint
.halt:
        hlt
        jmp .halt

bprint:
        pusha
.next:
        lodsb
        test al, al
        jz .done
        mov ah, 0x0E
        mov bx, 0x0007
        int 0x10
        jmp .next
.done:
        popa
        ret

msgA1:  db 13, 10, "EnzoOS", 0
msgB0:  db " B", 0
msgE1:  db " ERRO: imagem", 0
msgE2:  db " ERRO: int13 LBA", 0
msgE3:  db " ERRO: disco", 0

bdot:
        pusha
        mov al, '.'
        mov ah, 0x0E
        mov bx, 7
        int 0x10
        popa
        ret

bdrv:    db 0
tries:   db 0
secsize: dd 512
mult:    dw 4
done:    dd 0
lba_cur: dd 0

times 0x1E0-($-$$) db 0
patch_lba:   dd 0
patch_size:  dd 0
patch_cefs:  dd CEFS_OFF
patch_sig:   dd 0x5A5AA5A5
times 512-($-$$) db 0

; ---------------------------------------------------------------------------
; PARTE B — roda em 0x10200 (cópia carregada em 0x10000)
; ---------------------------------------------------------------------------
section .s2 vstart=0x10200 follows=.text

        ; labels da parte B são offsets 16-bit com base 0x10000 — o far jump
        ; só troca o CS; DS precisa acompanhar (senão lodsb lê 0x00xxx)
        mov ax, 0x1000
        mov ds, ax
        call serial_init
        mov si, msgB1
        call b2_print
        mov si, sB
        call serial_print

        ; ----------------------------------------------------------------
        ; Mapa de memória E820 -> 0x600 (entradas de 24 bytes), count em 0x5F0
        ; ----------------------------------------------------------------
        xor ax, ax
        mov es, ax
        xor ebp, ebp
        mov di, 0x600
        xor ebx, ebx
.e820_loop:
        mov eax, 0xE820
        mov edx, 0x534D4150          ; 'SMAP'
        mov ecx, 20
        int 0x15
        jc .e820_endchk
        cmp eax, 0x534D4150
        jne .e820_endchk
        add di, 20
        mov dword [es:di], 0         ; attr = 0
        add di, 4
        inc ebp
        cmp ebp, 24
        jae .e820_done
        test ebx, ebx
        jz .e820_done
        jmp .e820_loop
.e820_endchk:
        test ebp, ebp
        jnz .e820_done
        mov dword [es:0x600], 0      ; fallback: 0..64 MB tipo 1
        mov dword [es:0x604], 0
        mov dword [es:0x608], 0
        mov dword [es:0x60C], 0x04000000
        mov dword [es:0x610], 1
        mov dword [es:0x614], 1
        mov ebp, 1
.e820_done:
        mov [es:0x5F0], bp
        mov si, sM
        call serial_print

        ; ----------------------------------------------------------------
        ; A20
        ; ----------------------------------------------------------------
        call a20_check
        jnc .a20_ok
        in al, 0x92
        or al, 2
        and al, 0xFE
        out 0x92, al
        call a20_spin
        call a20_check
        jnc .a20_ok
        call a20_kbdc
        call a20_check
        jnc .a20_ok
        jmp err_a20
.a20_ok:
        mov si, sW
        call serial_print

        ; ----------------------------------------------------------------
        ; VBE — 1024x768x32, depois 800x600x32, 640x480x32 (com LFB)
        ; ----------------------------------------------------------------
        mov ax, 0x900
        mov es, ax
        xor di, di
        mov dword [es:di], 0x32454256       ; "VBE2"
        mov ax, 0x4F00
        int 0x10
        cmp ax, 0x004F
        jne err_vbe
        mov ax, [es:0x0E]
        mov [vbe_list_off], ax
        mov ax, [es:0x10]
        mov [vbe_list_seg], ax

        mov si, pref_tbl
.pref_next:
        lodsw
        test ax, ax
        jz err_vbe
        mov [want_w], ax
        lodsw
        mov [want_h], ax
        call vbe_scan
        jnc .vbe_found
        jmp .pref_next
.vbe_found:
        mov cx, [found_mode]
        or cx, 0x4000
        mov ax, 0x4F02
        int 0x10
        cmp ax, 0x004F
        jne err_vbe
        mov ax, 0x900
        mov es, ax
        xor di, di
        mov cx, [found_mode]
        mov ax, 0x4F01
        int 0x10
        cmp ax, 0x004F
        jne err_vbe
        xor ax, ax
        mov es, ax
        mov ax, [0x900+18]           ; XRes
        mov [vesa_w], ax
        mov ax, [0x900+20]           ; YRes
        mov [vesa_h], ax
        mov al, [0x900+25]           ; bpp
        mov [vesa_bpp], al
        mov ax, [0x900+16]           ; pitch
        test ax, ax
        jnz .pitch_ok
        mov ax, [vesa_w]
        shl ax, 2
.pitch_ok:
        mov [vesa_pitch], ax
        mov eax, [0x900+40]          ; PhysBasePtr
        mov [vesa_lfb], eax
        mov ax, [found_mode]
        mov [vesa_mode], ax
        mov si, sV
        call serial_print

        ; ----------------------------------------------------------------
        ; Parâmetros de boot em 0xE00
        ; ----------------------------------------------------------------
        mov dword [BP+0x00], 0x50423545       ; 'E5BP'
        mov dword [BP+0x04], 1
        mov eax, [vesa_lfb]
        mov [BP+0x08], eax
        mov dword [BP+0x0C], 0
        movzx eax, word [vesa_w]
        mov [BP+0x10], eax
        movzx eax, word [vesa_h]
        mov [BP+0x14], eax
        movzx eax, byte [vesa_bpp]
        mov [BP+0x18], eax
        movzx eax, word [vesa_pitch]
        mov [BP+0x1C], eax
        mov dword [BP+0x20], IMG_BASE
        mov dword [BP+0x24], CEFS_OFF
        mov eax, [dword IMG_BASE+0x1E4]
        mov [BP+0x28], eax
        movzx eax, word [0x5F0]
        mov [BP+0x2C], eax
        mov dword [BP+0x30], 0x600
        movzx eax, word [vesa_mode]
        mov [BP+0x34], eax
        mov dword [BP+0x38], 0
        mov dword [BP+0x3C], 0

        ; ----------------------------------------------------------------
        ; Modo protegido
        ; ----------------------------------------------------------------
        cli
        lgdt [gdtr]
        mov eax, cr0
        or eax, 1
        mov cr0, eax
        jmp 0x08:pm_entry

; ---------------------------------------------------------------------------
; rotinas 16-bit da parte B
; ---------------------------------------------------------------------------
serial_init:
        pusha
        mov dx, 0x3F9
        xor al, al
        out dx, al
        mov dx, 0x3FB
        mov al, 0x80
        out dx, al
        mov dx, 0x3F8
        mov al, 1
        out dx, al
        mov dx, 0x3F9
        xor al, al
        out dx, al
        mov dx, 0x3FB
        mov al, 0x03
        out dx, al
        mov dx, 0x3FA
        mov al, 0xC7
        out dx, al
        popa
        ret

serial_print:
        pusha
.next:
        lodsb
        test al, al
        jz .done
        mov ah, al
        mov dx, 0x3FD
.w:
        in al, dx
        test al, 0x20
        jz .w
        mov al, ah
        mov dx, 0x3F8
        out dx, al
        jmp .next
.done:
        popa
        ret

b2_print:
        pusha
.next:
        lodsb
        test al, al
        jz .done
        mov ah, 0x0E
        mov bx, 0x0007
        int 0x10
        jmp .next
.done:
        popa
        ret

a20_check:
        push ds
        xor ax, ax
        mov ds, ax
        mov word [0x0000], 0x1234
        mov ax, 0xFFFF
        mov es, ax
        mov word [es:0x0010], 0x4321
        cmp word [0x0000], 0x1234
        pop ds
        je a20_on          ; intacto -> o wrap nao alcancou 0x0 -> A20 ligada
        stc                ; mudou -> escrita em 0x100000 embrulhou -> A20 desligada
        ret
a20_on:
        clc
        ret

a20_spin:
        mov cx, 0x2000
.w:
        out 0x80, al
        loop .w
        ret

a20_kbdc:
        mov cx, 0xFFFF
.w1:
        in al, 0x64
        test al, 2
        loopnz .w1
        mov al, 0xAD
        out 0x64, al
        mov cx, 0xFFFF
.w2:
        in al, 0x64
        test al, 2
        loopnz .w2
        mov al, 0xD0
        out 0x64, al
        mov cx, 0xFFFF
.w3:
        in al, 0x64
        test al, 1
        loopz .w3
        in al, 0x60
        or al, 2
        mov ah, al
        mov cx, 0xFFFF
.w4:
        in al, 0x64
        test al, 2
        loopnz .w4
        mov al, 0xD1
        out 0x64, al
        mov cx, 0xFFFF
.w5:
        in al, 0x64
        test al, 2
        loopnz .w5
        mov al, ah
        out 0x60, al
        mov cx, 0xFFFF
.w6:
        in al, 0x64
        test al, 2
        loopnz .w6
        mov al, 0xAE
        out 0x64, al
        ret

; vbe_scan: procura modo (want_w, want_h) 32bpp com LFB e cor direta
vbe_scan:
        mov ax, [vbe_list_seg]
        mov es, ax
        mov di, [vbe_list_off]
.scan:
        mov cx, [es:di]
        cmp cx, 0xFFFF
        je .fail
        add di, 2
        push cx
        push di
        push es
        mov ax, 0x900
        mov es, ax
        xor di, di
        mov ax, 0x4F01
        int 0x10
        cmp ax, 0x004F
        jne .skip
        mov ax, [es:0]
        test ax, 0x0081              ; bit0 suportado | bit7 LFB
        jz .skip
        cmp byte [es:25], 32
        jne .skip
        cmp byte [es:27], 6
        jne .skip
        cmp dword [es:40], 0
        je .skip
        mov ax, [es:18]
        cmp ax, [want_w]
        jne .skip
        mov ax, [es:20]
        cmp ax, [want_h]
        jne .skip
        pop es
        pop di
        pop cx
        mov [found_mode], cx
        clc
        ret
.skip:
        pop es
        pop di
        pop cx
        jmp .scan
.fail:
        stc
        ret

err_a20:
        mov si, msgEA20
        jmp b2_err
err_vbe:
        mov si, msgEVBE
b2_err:
        call b2_print
        mov si, sE2
        call serial_print
.halt:
        hlt
        jmp .halt

; ---------------------------------------------------------------------------
; dados 16-bit da parte B
; ---------------------------------------------------------------------------
msgB1:   db " parte B", 13, 10, 0
msgEA20: db " ERRO: A20", 0
msgEVBE: db " ERRO: VBE", 0
sB:      db "[B]", 0
sM:      db "[e820]", 0
sW:      db "[a20]", 0
sV:      db "[vbe]", 0
sE2:     db "[ERR]", 0

pref_tbl:    dw 1024, 768, 800, 600, 640, 480, 0
want_w:      dw 0
want_h:      dw 0
found_mode:  dw 0
vbe_list_off: dw 0
vbe_list_seg: dw 0
vesa_w:      dw 0
vesa_h:      dw 0
vesa_bpp:    db 0
vesa_pitch:  dw 0
vesa_lfb:    dd 0
vesa_mode:   dw 0

align 8
gdt:
        dq 0x0000000000000000
        dq 0x00CF9A000000FFFF          ; 0x08 código 32-bit
        dq 0x00CF93000000FFFF          ; 0x10 dados
        dq 0x00AF9A000000FFFF          ; 0x18 código 64-bit
gdtr:
        dw gdt_end - gdt - 1
        dd gdt
        dw 0
gdt_end:

; ---------------------------------------------------------------------------
; Modo protegido 32-bit
; ---------------------------------------------------------------------------
use32
pm_entry:
        mov ax, 0x10
        mov ds, ax
        mov es, ax
        mov ss, ax
        mov fs, ax
        mov gs, ax
        mov esp, 0x7B00

        ; ----------------------------------------------------------------
        ; Tabelas de página: PML4 @0x90000, PDPT @0x91000,
        ; PD @0x92000..0x95FFF (2MB), extra @0x96000 (LFB >= 4GB)
        ; ----------------------------------------------------------------
        mov edi, 0x90000
        mov ecx, 0x8000/4
        xor eax, eax
        cld
        rep stosd

        mov eax, 0x80000001            ; PDPE1GB?
        cpuid
        mov [pdpe1gb], edx
        test edx, 1 << 26
        jz .map_2m

        mov eax, 0x91000
        or eax, 3
        mov [0x90000], eax
        mov edi, 0x91000
        xor ecx, ecx
.pg1g:                                  ; 512 páginas de 1GB = 0..512GB
        mov eax, ecx
        shl eax, 30
        or eax, 0x81
        stosd
        mov eax, ecx
        shr eax, 2
        stosd
        inc ecx
        cmp ecx, 512
        jb .pg1g
        jmp .pat_setup

.map_2m:
        mov eax, 0x91000
        or eax, 3
        mov [0x90000], eax
        mov edi, 0x91000
        xor ecx, ecx
.pdpt2m:
        mov eax, ecx
        shl eax, 12
        add eax, 0x92000
        or eax, 3
        stosd
        xor eax, eax
        stosd
        inc ecx
        cmp ecx, 4
        jb .pdpt2m
        mov edi, 0x92000               ; 2048 páginas de 2MB = 0..4GB
        xor ebx, ebx
        mov ecx, 2048
.fillpd:
        mov eax, ebx
        or eax, 0x83
        stosd
        xor eax, eax
        stosd
        add ebx, 0x200000
        loop .fillpd

.pat_setup:
        mov ecx, 0x277                  ; PAT: entrada 4 = Write-Combining
        rdmsr
        and edx, 0xFFFFFF00
        or edx, 0x01
        wrmsr

        ; LFB em WC se a região NÃO for RAM (varre o E820)
        mov esi, [vesa_lfb]
        test esi, esi
        jz .lfb_extra
        movzx ecx, word [0x5F0]
        mov edi, 0x600
.e820_scan:
        test ecx, ecx
        jz .lfb_wc
        cmp dword [edi+4], 0
        jne .next_e820
        mov eax, [edi+0]
        mov ebx, eax
        add ebx, [edi+8]
        cmp esi, eax
        jb .next_e820
        cmp esi, ebx
        jae .next_e820
        cmp dword [edi+16], 1          ; RAM?
        je .lfb_extra                  ; RAM: sem WC
        jmp .lfb_wc
.next_e820:
        add edi, 24
        dec ecx
        jmp .e820_scan

.lfb_wc:
        test dword [pdpe1gb], 1 << 26
        jnz .wc_1g
        mov eax, esi
        shr eax, 30
        mov edi, 0x92000
        mov edx, eax
        shl edx, 12
        add edi, edx
        mov eax, esi
        shr eax, 21
        and eax, 0x1FF
        shl eax, 3
        add edi, eax
        or dword [edi], 0x1000         ; bit 12 = PAT
        jmp .lfb_extra
.wc_1g:
        mov eax, esi
        shr eax, 30
        mov edi, 0x91000
        shl eax, 3
        add edi, eax
        or dword [edi], 0x1000

.lfb_extra:
        test dword [pdpe1gb], 1 << 26
        jnz .longmode                  ; 1GB cobre 0..512GB
        cmp dword [vesa_lfb+4], 0
        jne .need_extra
        jmp .longmode                  ; < 4GB já coberto
.need_extra:                            ; LFB >= 4GB no modo 2MB
        mov esi, [vesa_lfb]
        mov eax, esi
        shr eax, 30
        mov edi, 0x91000
        mov edx, eax
        shl edx, 3
        add edi, edx
        mov dword [edi], 0x96003
        mov dword [edi+4], 0
        mov edi, 0x96000
        mov ebx, esi
        and ebx, 0xC0000000
        mov ecx, 512
.fill_extra:
        mov eax, ebx
        or eax, 0x83
        stosd
        mov eax, esi
        shr eax, 2
        stosd
        add ebx, 0x200000
        loop .fill_extra

.longmode:
        mov eax, cr4
        or eax, 1 << 5                 ; PAE
        or eax, 1 << 4                 ; PSE
        or eax, 1 << 9                 ; OSFXSR
        or eax, 1 << 10                ; OSXMMEXCPT
        mov cr4, eax
        mov ecx, 0xC0000080            ; EFER.LME
        rdmsr
        or eax, 1 << 8
        wrmsr
        mov eax, 0x90000
        mov cr3, eax
        mov eax, cr0
        or eax, 0x80000000             ; PG
        mov cr0, eax
        jmp 0x18:lm_entry

; ---------------------------------------------------------------------------
; Modo longo 64-bit
; ---------------------------------------------------------------------------
use64
default abs
lm_entry:
        xor eax, eax
        mov ax, 0x10
        mov ds, ax
        mov es, ax
        mov ss, ax
        mov fs, ax
        mov gs, ax

        mov dx, 0x3FD                  ; serial "[L]"
.w:
        in al, dx
        test al, 0x20
        jz .w
        mov dx, 0x3F8
        mov al, 'L'
        out dx, al

        ; copia o KERNEL.BIN (entrada 0 do CEFS) para 0x100000
        mov rsi, IMG_BASE + CEFS_OFF
        cmp dword [rsi], 0x53464543    ; "CEFS"
        jne lm_err
        movzx ecx, word [rsi+6]
        test ecx, ecx
        jz lm_err
        mov eax, [rsi+16+24]           ; size da entrada 0
        test eax, eax
        jz lm_err
        mov r8d, [rsi+8]               ; data_start
        mov edx, [rsi+16+20]           ; offset da entrada 0
        add rsi, r8
        add esi, edx
        mov edi, 0x100000
        mov ecx, [IMG_BASE + CEFS_OFF + 16 + 24]
        cld
        rep movsb

        mov rax, 0x100000
        cmp dword [rax], 0x31304543    ; "CE01"
        jne lm_err
        mov r8d, [rax+8]               ; entry RVA
        add r8, rax
        mov rdi, BP
        mov rsp, 0x9F000
        jmp r8

lm_err:
        hlt
        jmp lm_err

pdpe1gb: dd 0
