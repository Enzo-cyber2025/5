; =============================================================================
;  EnzoOS — kernel/cpu.inc: detecção de CPU (CPUID) e recursos
; =============================================================================
%ifndef CPU_INC
%define CPU_INC

section .ktext

; -----------------------------------------------------------------------------
k_cpu_init:
        ; marca máxima de CPUID
        xor eax, eax
        cpuid
        mov [cpuid_max], eax
        ; marca estendida
        mov eax, 0x80000000
        cpuid
        mov [cpuid_max_ext], eax
        ; string de marca do fabricante
        mov eax, [cpuid_max_ext]
        cmp eax, 0x80000004
        jb .no_brand
        mov eax, 0x80000002
        cpuid
        mov [cpu_brand], eax
        mov [cpu_brand+4], ebx
        mov [cpu_brand+8], ecx
        mov [cpu_brand+12], edx
        mov eax, 0x80000003
        cpuid
        mov [cpu_brand+16], eax
        mov [cpu_brand+20], ebx
        mov [cpu_brand+24], ecx
        mov [cpu_brand+28], edx
        mov eax, 0x80000004
        cpuid
        mov [cpu_brand+32], eax
        mov [cpu_brand+36], ebx
        mov [cpu_brand+40], ecx
        mov [cpu_brand+44], edx
.no_brand:
        ; recursos: CPUID.1 EDX/ECX
        mov eax, 1
        cpuid
        mov [feat_edx1], edx
        mov [feat_ecx1], ecx
        ; PDPE1GB e lahf: CPUID.80000001h EDX
        mov eax, [cpuid_max_ext]
        cmp eax, 0x80000001
        jb .no_ext
        mov eax, 0x80000001
        cpuid
        mov [feat_edx81], edx
.no_ext:
        ; núcleos lógicos via CPUID leaf 0xB (Intel)
        mov dword [cpu_cores], 1
        mov eax, [cpuid_max]
        cmp eax, 0xB
        jb .no_cores
        xor ecx, ecx
        mov eax, 0xB
        cpuid
        test ebx, ebx
        jz .no_cores
        mov eax, 1
        mov ecx, 1                    ; nível 1 = núcleos lógicos
        cpuid
        mov [cpu_cores], ebx
.no_cores:
        ret

section .kdata
cpuid_max:     dd 0
cpuid_max_ext: dd 0
cpu_brand:     times 49 db 0
feat_edx1:     dd 0
feat_ecx1:     dd 0
feat_edx81:    dd 0
cpu_cores:     dd 1

%endif
