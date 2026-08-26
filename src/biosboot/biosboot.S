/* NovaLinux El Torito BIOS loader — load bzImage via unreal mode. */
.code16
.global _start

.set BUF,     0x7000
.set SETUP,   0x90000
.set PMKERN,  0x100000
.set CMDLINE, 0x93000

_start:
    cli
    xor     %ax, %ax
    mov     %ax, %ds
    mov     %ax, %es
    mov     %ax, %ss
    mov     $0x6FFE, %sp
    mov     %dl, boot_drive
    sti

    mov     $msg, %si
    call    puts

    /* A20 */
    in      $0x92, %al
    or      $2, %al
    out     %al, $0x92

    call    unreal

    /* first 2048 bytes of kernel */
    movl    kernel_lba, %eax
    mov     $BUF, %di
    call    read_cd
    jc      fail

    movb    BUF + 0x1F1, %al
    test    %al, %al
    jnz     1f
    mov     $4, %al
1:
    movzbl  %al, %ecx
    inc     %ecx
    shl     $9, %ecx
    movl    %ecx, setup_bytes

    movl    $BUF, %esi
    movl    $SETUP, %edi
    movl    $2048, %ecx
    call    copy32

    movl    $1, file_sec
    movl    $2048, copied

load_loop:
    movl    copied, %eax
    cmpl    kernel_bytes, %eax
    jae     loaded

    movl    kernel_lba, %eax
    addl    file_sec, %eax
    mov     $BUF, %di
    call    read_cd
    jc      fail

    movl    copied, %eax
    movl    setup_bytes, %ebx
    cmpl    %ebx, %eax
    jae     to_high

    movl    $2048, %ecx
    movl    %ebx, %edx
    subl    %eax, %edx
    cmpl    %edx, %ecx
    jbe     2f
    movl    %edx, %ecx
2:
    movl    $BUF, %esi
    movl    $SETUP, %edi
    addl    %eax, %edi
    call    copy32
    addl    %ecx, copied
    incl    file_sec
    cmpl    $2048, %ecx
    je      load_loop
    movl    $BUF, %esi
    addl    %ecx, %esi
    movl    $PMKERN, %edi
    movl    $2048, %edx
    subl    %ecx, %edx
    movl    %edx, %ecx
    call    copy32
    addl    %ecx, copied
    incl    file_sec
    jmp     load_loop

to_high:
    movl    $BUF, %esi
    movl    $PMKERN, %edi
    addl    %eax, %edi
    subl    %ebx, %edi
    movl    $2048, %ecx
    movl    kernel_bytes, %edx
    subl    %eax, %edx
    cmpl    %edx, %ecx
    jbe     3f
    movl    %edx, %ecx
3:
    call    copy32
    addl    %ecx, copied
    incl    file_sec
    jmp     load_loop

loaded:
    movl    $SETUP, %edi
    addr32 movw $0x8E00, 0x224(%edi)
    addr32 movb 0x211(%edi), %al
    orb     $0x80, %al
    addr32 movb %al, 0x211(%edi)
    addr32 movl $CMDLINE, 0x228(%edi)
    addr32 movb $0xFF, 0x210(%edi)

    mov     $cmdline, %si
    movl    $CMDLINE, %edi
4:
    lodsb
    addr32 movb %al, (%edi)
    incl    %edi
    test    %al, %al
    jnz     4b

    mov     $msg_ok, %si
    call    puts
    ljmp    $0x9020, $0x0000

fail:
    mov     $msg_fail, %si
    call    puts
hang:
    hlt
    jmp     hang

/* EAX = ISO LBA (2048), ES:DI = dest */
read_cd:
    pushal
    movl    %eax, dap_lba
    movw    %di, dap_off
    movw    $0, dap_seg
    mov     boot_drive, %dl
    xor     %ah, %ah
    int     $0x13
    mov     $dap, %si
    mov     boot_drive, %dl
    mov     $0x42, %ah
    int     $0x13
    popal
    ret

/* ECX bytes ESI -> EDI (unreal, 32-bit addresses) */
copy32:
    pushal
    pushf
    cli
1:
    testl   %ecx, %ecx
    jz      2f
    addr32 movb (%esi), %al
    addr32 movb %al, (%edi)
    incl    %esi
    incl    %edi
    decl    %ecx
    jmp     1b
2:
    popf
    popal
    ret

unreal:
    cli
    lgdt    gdt_desc
    movl    %cr0, %eax
    orb     $1, %al
    movl    %eax, %cr0
    mov     $8, %bx
    mov     %bx, %ds
    mov     %bx, %es
    movl    %cr0, %eax
    andb    $0xFE, %al
    movl    %eax, %cr0
    xor     %ax, %ax
    mov     %ax, %ds
    mov     %ax, %es
    sti
    ret

puts:
    lodsb
    test    %al, %al
    jz      1f
    mov     $0x0E, %ah
    mov     $0x0007, %bx
    int     $0x10
    jmp     puts
1:  ret

    .align 8
gdt:
    .quad   0
    .word   0xFFFF, 0x0000
    .byte   0x00, 0x92, 0xCF, 0x00
gdt_desc:
    .word   gdt_end - gdt - 1
    .long   gdt
gdt_end:

dap:
    .byte   16, 0
    .word   1
dap_off:
    .word   0
dap_seg:
    .word   0
dap_lba:
    .quad   0

boot_drive: .byte 0
    .align  4
setup_bytes: .long 0
file_sec:    .long 0
copied:      .long 0

msg:      .asciz "NovaLinux BIOS loader...\r\n"
msg_ok:   .asciz "Starting kernel.\r\n"
msg_fail: .asciz "Read failed. VirtualBox: System > Motherboard > Enable EFI\r\n"
cmdline:  .asciz "console=tty0 earlyprintk=vga loglevel=7 mitigations=off intel_idle.max_cstate=4"

    .align  4
    /* file offset of these two dwords is patched by mkiso */
kernel_lba:
    .long   0xA1B2C3D4
kernel_bytes:
    .long   0xE5F60718
