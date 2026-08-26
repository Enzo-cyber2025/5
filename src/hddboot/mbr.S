/* Volume boot MBR — load stage2 from LBA 1 into 0x8000 and jump.
 * Linked at 0x7C00, must be 512 bytes with 0x55AA. */
.code16
.global _start

_start:
    cli
    xor     %ax, %ax
    mov     %ax, %ds
    mov     %ax, %es
    mov     %ax, %ss
    mov     $0x7C00, %sp
    mov     %dl, drive
    sti

    mov     $msg, %si
    call    puts

    mov     $dap, %si
    mov     drive, %dl
    mov     $0x42, %ah
    int     $0x13
    jc      fail

    mov     drive, %dl
    ljmp    $0x0000, $0x8000

fail:
    mov     $err, %si
    call    puts
1:  hlt
    jmp     1b

puts:
    lodsb
    test    %al, %al
    jz      1f
    mov     $0x0E, %ah
    mov     $0x0007, %bx
    int     $0x10
    jmp     puts
1:  ret

msg:  .asciz "NovaLinux\r\n"
err:  .asciz "MBR read fail\r\n"
drive: .byte 0

    .align 4
dap:
    .byte   16, 0
    .word   8              /* 8 sectors = 4 KiB stage2 */
    .word   0x8000, 0      /* dest 0x0000:0x8000 */
    .quad   1              /* LBA 1 */

    .org    446
    /* partition 1 filled in by mkhdd.py */
    .org    510
    .byte   0x55, 0xAA
