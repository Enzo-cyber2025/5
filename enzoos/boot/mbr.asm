; =============================================================================
;  EnzoOS — boot/mbr.asm
;  MBR híbrido para a ISO (boot por USB/disco). 100% Assembly.
;
;  O mkiso.py grava este setor em LBA 0 da ISO e cria uma partição do
;  tipo 0x17 cobrindo a imagem toda (estilo isohybrid). O código:
;    1. copia a si mesmo para 0x600
;    2. lê o setor (image_lba*4) — início da imagem de boot do EnzoOS —
;       para 0x7C00 via INT 13h AH=42h (LBA)
;    3. salta para 0:0x7C00 (a parte A do stage1 assume o controle)
;
;  Patch do mkiso.py (offset 0x1B0 do setor):
;    +0x1B0  u32 LBA (em setores de 512) do início da imagem de boot
;    +0x1B4  u32 assinatura 0x5A5AA5A5
; =============================================================================
BITS 16
section .text vstart=0x7C00

start:
        cli
        xor ax, ax
        mov ds, ax
        mov es, ax
        mov ss, ax
        mov sp, 0x7A00
        sti
        cld

        ; valida patch
        cmp dword [0x7C00+0x1B4], 0x5A5AA5A5
        jne fail

        ; --- copia a si mesmo para 0x600 ---
        mov si, 0x7C00
        mov di, 0x0600
        mov cx, 256
        rep movsw
        push word 0
        push word cont
        retf

cont:
        ; --- extensões INT 13h ---
        mov dl, [0x0600 + (bdrv - start)]
        mov ah, 0x41
        mov bx, 0x55AA
        int 0x13
        jc fail
        cmp bx, 0xAA55
        jne fail

        ; --- lê 1 setor (512) do início da imagem de boot para 0x7C00 ---
        mov word [0x0500], 0x0010     ; tamanho do DAP
        mov word [0x0502], 1          ; 1 setor
        mov word [0x0504], 0x7C00     ; offset
        mov word [0x0506], 0x0000     ; segmento
        mov eax, [0x0600 + (patch_lba512 - start)]
        mov [0x0508], eax
        mov dword [0x050C], 0

        mov si, 0x0500
        mov dl, [0x0600 + (bdrv - start)]
        mov ah, 0x42
        int 0x13
        jc fail

        ; entrega para a parte A do EnzoOS
        push word 0
        push word 0x7C00
        retf

fail:
        mov si, mbrmsg
.print:
        lodsb
        test al, al
        jz .halt
        mov ah, 0x0E
        mov bx, 0x0007
        int 0x10
        jmp .print
.halt:
        hlt
        jmp .halt

mbrmsg: db "MBR EnzoOS: erro de leitura", 0
bdrv:   db 0

times 0x1B0-($-$$) db 0
patch_lba512: dd 0
patch_sig:    dd 0x5A5AA5A5

; --- tabela de partições: 1 partição oculta tipo 0x17 do LBA 0 ---
times 0x1BE-($-$$) db 0
        db 0x80                       ; bootável
        db 0, 0, 0                    ; CHS inicial (dummy)
        db 0x17                       ; tipo: ISO9660 oculto
        db 0, 0, 0                    ; CHS final (dummy)
        dd 0                          ; LBA inicial (patch: 0)
        dd 0                          ; setores (patch: tamanho da ISO/512)
        times 48 db 0                 ; entradas 2..4 vazias
        dw 0xAA55
