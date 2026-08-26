/* Stage2 HDD loader — 512-byte sectors, linked at 0x8000. */
.code16
.global _start

.set BUF,      0x7000
.set BUFSZ,    8192
.set NSEC,     16
.set SETUP,    0x90000
.set PMKERN,   0x100000
.set CMDLINE,  0x9E000

_start:
    cli
    xor     %ax, %ax
    mov     %ax, %ds
    mov     %ax, %ss
    mov     $0x6FFE, %sp
    mov     %dl, boot_drive
    cld
    sti

    mov     $msg, %si
    call    puts

    in      $0x92, %al
    or      $2, %al
    out     %al, $0x92
    call    unreal

    movl    $0, copied
    movl    $0, file_sec

load_loop:
    movl    copied, %eax
    cmpl    kernel_bytes, %eax
    jae     loaded

    /* how many 512-byte sectors this round */
    movl    kernel_bytes, %eax
    subl    copied, %eax
    addl    $511, %eax
    shr     $9, %eax
    cmpl    $NSEC, %eax
    jbe     1f
    movl    $NSEC, %eax
1:
    movw    %ax, dap_count
    movl    kernel_lba, %ebx
    addl    file_sec, %ebx
    movl    %ebx, dap_lba
    call    read_disk
    jc      fail

    movl    file_sec, %eax
    andl    $127, %eax
    jnz     8f
    mov     $dot, %si
    call    puts
8:

    /* copy this chunk into setup and/or PM kernel */
    movl    copied, %eax
    movl    setup_need, %ebx
    /* first time, setup_need is 0 — read it from the first sector */
    testl   %ebx, %ebx
    jnz     4f
    movb    BUF + 0x1F1, %bl
    test    %bl, %bl
    jnz     3f
    mov     $4, %bl
3:
    movzbl  %bl, %ebx
    inc     %ebx
    shl     $9, %ebx
    movl    %ebx, setup_need
4:
    movzwl  dap_count, %ecx
    shl     $9, %ecx              /* bytes in this read */
    movl    $BUF, %esi

copy_chunk:
    testl   %ecx, %ecx
    jz      next_read
    movl    copied, %eax
    movl    setup_need, %ebx
    cmpl    %ebx, %eax
    jae     copy_high

    movl    %ebx, %edx
    subl    %eax, %edx            /* bytes still needed in setup */
    cmpl    %ecx, %edx
    jbe     5f
    movl    %ecx, %edx
5:
    movl    $SETUP, %edi
    addl    %eax, %edi
    /* copy EDX bytes, save ECX */
    pushl   %ecx
    movl    %edx, %ecx
    call    copy32
    popl    %ecx
    addl    %edx, copied
    addl    %edx, %esi
    subl    %edx, %ecx
    jmp     copy_chunk

copy_high:
    movl    $PMKERN, %edi
    addl    %eax, %edi
    subl    %ebx, %edi
    pushl   %ecx
    call    copy32
    popl    %ecx
    addl    %ecx, copied
    xor     %ecx, %ecx
    jmp     copy_chunk

next_read:
    movzwl  dap_count, %eax
    addl    %eax, file_sec
    jmp     load_loop

loaded:
    movl    $SETUP, %edi
    addr32 movw $0x8E00, 0x224(%edi)
    addr32 movb 0x211(%edi), %al
    orb     $0x80, %al
    addr32 movb %al, 0x211(%edi)
    addr32 movl $CMDLINE, 0x228(%edi)
    addr32 movb $0xFF, 0x210(%edi)
    addr32 movw $0x0318, 0x1FA(%edi)

    mov     $cmdline, %si
    movl    $CMDLINE, %edi
6:
    lodsb
    addr32 movb %al, (%edi)
    incl    %edi
    test    %al, %al
    jnz     6b

    mov     $msg_ok, %si
    call    puts
    ljmp    $0x9020, $0x0000

fail:
    mov     $msg_fail, %si
    call    puts
hang:
    hlt
    jmp     hang

read_disk:
    pushal
    mov     boot_drive, %dl
    mov     $dap, %si
    mov     $0x42, %ah
    int     $0x13
    popal
    ret

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
    ljmp    $0, $unreal_rm
unreal_rm:
    xor     %ax, %ax
    mov     %ax, %ss
    mov     $0x6FFE, %sp
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
gdt_end:
gdt_desc:
    .word   gdt_end - gdt - 1
    .long   gdt

dap:
    .byte   16, 0
dap_count:
    .word   16
    .word   BUF, 0
dap_lba:
    .quad   0

boot_drive: .byte 0
    .align  4
setup_need:  .long 0
file_sec:    .long 0
copied:      .long 0

msg:      .asciz "HDD loader...\r\n"
dot:      .asciz "."
msg_ok:   .asciz "\r\nStarting kernel.\r\n"
msg_fail: .asciz "\r\nDisk read failed.\r\n"
cmdline:  .asciz "console=tty0 earlyprintk=vga loglevel=7 vga=791 mitigations=off intel_idle.max_cstate=4"

    .align  4
kernel_lba:
    .long   0xA1B2C3D4
kernel_bytes:
    .long   0xE5F60718
