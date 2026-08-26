/* NovaLinux El Torito BIOS loader.
 * Loads bzImage from the ISO and jumps to the real-mode setup.
 * Linked at 0x7C00. */
.code16
.global _start

.set BUF,      0x7000
.set SETUP,    0x90000
.set PMKERN,   0x100000
.set CMDLINE,  0x9E000

_start:
    cli
    xor     %ax, %ax
    mov     %ax, %ds
    mov     %ax, %es
    mov     %ax, %ss
    mov     $0x6FFE, %sp
    mov     %dl, boot_drive
    cld
    sti

    mov     $msg, %si
    call    puts

    /* A20 via fast gate */
    in      $0x92, %al
    or      $2, %al
    out     %al, $0x92

    call    unreal

    /* First 2048-byte CD sector of the kernel */
    movl    kernel_lba, %eax
    call    read_cd
    jc      fail

    /* setup_sects at +0x1F1; real-mode blob is (sects+1)*512 */
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
    call    read_cd
    jc      fail

    /* progress every 64 CD sectors */
    movl    file_sec, %eax
    andl    $63, %eax
    jnz     8f
    mov     $dot, %si
    call    puts
8:

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
    /* remainder of this CD sector belongs to the PM kernel */
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
    /* heap_end_ptr @ 0x224 — keep heap below the command line */
    addr32 movw $0x8E00, 0x224(%edi)
    /* loadflags |= CAN_USE_HEAP */
    addr32 movb 0x211(%edi), %al
    orb     $0x80, %al
    addr32 movb %al, 0x211(%edi)
    /* cmd_line_ptr @ 0x228 — MUST be outside the setup blob */
    addr32 movl $CMDLINE, 0x228(%edi)
    /* type_of_loader */
    addr32 movb $0xFF, 0x210(%edi)
    /* vid_mode @ 0x1FA = VESA 1024x768x32 so VirtualBox BIOS gets a FB */
    addr32 movw $0x0318, 0x1FA(%edi)

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

/* EAX = ISO 2048-byte LBA. Reads one CD sector into BUF.
 * SeaBIOS CD int 13h AH=42 uses 2048-byte sectors for the boot CD. */
read_cd:
    pushal
    movl    %eax, dap_lba
    movw    $BUF, dap_off
    movw    $0, dap_seg
    mov     boot_drive, %dl
    mov     $dap, %si
    mov     $0x42, %ah
    int     $0x13
    popal
    ret

/* ECX bytes from linear ESI to linear EDI. Needs unreal DS/ES. */
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

/* Enter big-real (unreal) mode and KEEP the 4GB DS/ES limits.
 * Reloading DS/ES after clearing PE would collapse the limit to 64K
 * and every copy to 0x100000 would wrap — black screen. */
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
    /* DS/ES still cached with 4GB limits — do not reload them. */
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
dot:      .asciz "."
msg_ok:   .asciz "\r\nStarting kernel.\r\n"
msg_fail: .asciz "\r\nDisk read failed.\r\n"
cmdline:  .asciz "console=tty0 earlyprintk=vga loglevel=7 vga=791 mitigations=off intel_idle.max_cstate=4"

    .align  4
    /* file offset of these two dwords is patched by mkiso */
kernel_lba:
    .long   0xA1B2C3D4
kernel_bytes:
    .long   0xE5F60718
