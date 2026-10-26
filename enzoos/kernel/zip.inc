; =============================================================================
;  EnzoOS — kernel/zip.inc: contêiner ZIP, runner de APK (AndroidManifest.xml
;  AXML, classes.dex, lib/*/lib*.so), scripts .run e visualizador de texto.
; =============================================================================
%ifndef ZIP_INC
%define ZIP_INC

section .ktext

; -----------------------------------------------------------------------------
; utilitários de console
; -----------------------------------------------------------------------------
co_str:                           ; rdi=str
        push rdi
        call k_strlen
        mov rsi, rax
        pop rdi
        jmp conout_write

co_nl:
        mov rdi, s_con_nl
        mov esi, 1
        jmp conout_write

co_dec:                           ; edi=valor
        push rdi
        lea rsi, [numbuf3]
        mov edx, 10
        call k_utoa
        mov rsi, rax
        lea rdi, [numbuf3]
        call conout_write
        pop rdi
        ret

co_hex16:                         ; edi=valor (16 dígitos)
        push rdi
        lea rsi, [numbuf3]
        mov edx, 16
        call k_utoa
        mov rsi, rax
        lea rdi, [numbuf3]
        call conout_write
        pop rdi
        ret

; -----------------------------------------------------------------------------
; ZIP
; -----------------------------------------------------------------------------
; zip_find: rdi=zip, rsi=tamanho, rdx=nome -> rax=entrada do CD ou 0
zip_find:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi                    ; base
        mov r15, rdx                    ; nome alvo
        ; fim
        mov rax, r12
        add rax, rsi
        mov r13, rax                    ; fim
        ; procura EOCD
        mov r14, r13
        sub r14, 22
        cmp r14, r12
        jb .no
        mov rbx, r13
        sub rbx, 1024
        cmp rbx, r12
        jae .scan
        mov rbx, r12
.scan:
        cmp rbx, r14
        ja .no
        cmp dword [rbx], 0x06054B50
        je .found
        inc rbx
        jmp .scan
.found:
        movzx eax, word [rbx+16]
        mov [zp_count], eax
        mov eax, [rbx+20]
        add rax, r12
        mov rbx, rax                    ; cursor no CD
        xor r14d, r14d                  ; índice
.ent:
        cmp r14d, [zp_count]
        jae .no
        cmp dword [rbx], 0x02014B50
        jne .no
        ; comprimento do alvo
        mov rdi, r15
        call k_strlen
        mov r13d, eax                   ; len alvo
        movzx ecx, word [rbx+28]        ; nlen
        cmp ecx, r13d
        jne .next
        ; compara byte a byte (caixa ignorada)
        lea r8, [rbx+46]
        xor edx, edx
.cmp:
        cmp edx, r13d
        jae .hit
        mov al, [r8 + rdx]
        mov cl, [r15 + rdx]
        ; upcase ambos
        cmp al, 'a'
        jb .k1
        cmp al, 'z'
        ja .k1
        sub al, 32
.k1:
        cmp cl, 'a'
        jb .k2
        cmp cl, 'z'
        ja .k2
        sub cl, 32
.k2:
        cmp al, cl
        jne .next
        inc edx
        jmp .cmp
.hit:
        mov rax, rbx
        jmp .out
.next:
        movzx edx, word [rbx+28]
        add edx, 46
        movzx eax, word [rbx+30]
        add edx, eax
        movzx eax, word [rbx+32]
        add edx, eax
        add rbx, rdx
        inc r14d
        jmp .ent
.no:
        xor rax, rax
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; zip_data: rdi=zip, rsi=entrada CD -> rax=ptr dos dados comprimidos
zip_data:
        mov eax, [rsi + 42]             ; local header offset
        add rax, rdi
        movzx ecx, word [rax+26]        ; nlen local
        movzx edx, word [rax+28]        ; elen local
        lea rax, [rax + 30]
        add rax, rcx
        add rax, rdx
        ret

; zip_load: rdi=zip, rsi=size, rdx=nome -> rax=buf (heap) e rdx=len; 0=falha
zip_load:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        mov r13, rsi
        mov r14, rdx
        call zip_find
        test rax, rax
        jz .no
        mov r15, rax
        ; dados comprimidos e método
        mov rdi, r12
        mov rsi, r15
        call zip_data
        mov rbx, rax
        movzx eax, word [r15+10]
        mov [zload_method], eax
        mov r13d, [r15+24]              ; usize
        test r13d, r13d
        jz .empty
        mov rdi, r13
        add rdi, 4095
        and rdi, -4096
        call k_alloc
        test rax, rax
        jz .no
        mov [zload_buf], rax
        cmp dword [zload_method], 0
        je .stored
        cmp dword [zload_method], 8
        je .deflate
        jmp .bad
.stored:
        mov rdi, [zload_buf]
        mov rsi, rbx
        mov rdx, r13
        call k_memcpy
        jmp .ok
.deflate:
        mov rdi, rbx
        mov rsi, [zload_buf]
        mov edx, r13d
        call inflate
        test rax, rax
        jnz .bad
.ok:
        mov rax, [zload_buf]
        mov rdx, r13
        jmp .out
.empty:
        mov rax, z_empty
        xor edx, edx
        jmp .out
.bad:
        mov rdi, [zload_buf]
        mov rsi, r13
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
.no:
        xor rax, rax
        xor edx, edx
.out:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; zip_name: rsi=entrada CD, rdi=buf (máx 64) -> rax=len
zip_name:
        movzx ecx, word [rsi+28]
        cmp ecx, 63
        jbe .ok
        mov ecx, 63
.ok:
        lea r8, [rsi+46]
        xor edx, edx
.cp:
        cmp edx, ecx
        jae .done
        mov al, [r8 + rdx]
        mov [rdi + rdx], al
        inc edx
        jmp .cp
.done:
        mov byte [rdi + rdx], 0
        mov rax, rdx
        ret

; -----------------------------------------------------------------------------
; APK — string pool do AXML
; -----------------------------------------------------------------------------
; axml_pool: rdi=buf (chunk do pool) — prepara globals
axml_pool:
        ; cabeçalho: type u16, hdrSize u16, size u32, stringCount u32,
        ; styleCount u32, flags u32, stringsStart u32, stylesStart u32
        mov eax, [rdi+8]
        mov [sp_count], eax
        mov eax, [rdi+16]
        and eax, 0x100
        mov [sp_utf8], eax
        lea rax, [rdi+28]               ; offsets
        mov [sp_offsets], rax
        mov eax, [rdi+20]               ; stringsStart
        add rax, rdi
        mov [sp_strings], rax
        ret

; sp_get: edi=índice -> rax=ptr (sp_buf), rdx=len
sp_get:
        cmp edi, [sp_count]
        jb .ok
        mov rax, sp_buf
        mov byte [rax], 0
        xor edx, edx
        ret
.ok:
        mov eax, [sp_offsets + rdi*4]
        add rax, [sp_strings]           ; ptr da string bruta
        ; UTF-8?
        cmp dword [sp_utf8], 0
        jne .utf8
        ; UTF-16LE: len u16
        movzx ecx, word [rax]
        test ecx, 0x8000
        jz .u16len
        ; comprimento estendido: mais um u16
        movzx edx, word [rax+2]
        and ecx, 0x7FFF
        shl edx, 15
        or ecx, edx
        add rax, 4
        jmp .u16cp
.u16len:
        add rax, 2
.u16cp:
        ; converte até 126 chars para Latin-1
        xor edx, edx
.l:
        cmp edx, ecx
        jae .d
        cmp edx, 126
        jae .d
        mov r8d, [rax + rdx*2]
        mov [sp_buf + rdx], r8b
        inc edx
        jmp .l
.d:
        mov byte [sp_buf + rdx], 0
        mov rax, sp_buf
        ret
.utf8:
        ; 1º comprimento (unidades UTF-16) — pode ocupar 2 bytes
        movzx ecx, byte [rax]
        test ecx, 0x80
        jz .u8a
        inc rax
.u8a:
        inc rax
        ; 2º comprimento (bytes UTF-8) — pode ocupar 2 bytes
        movzx ecx, byte [rax]
        test ecx, 0x80
        jz .u8b
        and ecx, 0x7F
        inc rax
        movzx edx, byte [rax]
        shl ecx, 7
        or ecx, edx
.u8b:
        inc rax
        ; copia
        xor edx, edx
.l8:
        cmp edx, ecx
        jae .d8
        cmp edx, 126
        jae .d8
        mov r8b, [rax + rdx]
        mov [sp_buf + rdx], r8b
        inc edx
        jmp .l8
.d8:
        mov byte [sp_buf + rdx], 0
        mov rax, sp_buf
        ret

; -----------------------------------------------------------------------------
; axml_run: rdi=buf, rsi=size — extrai dados do manifesto
; -----------------------------------------------------------------------------
axml_run:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        mov r13, rsi
        ; zera estado
        mov byte [ap_package], 0
        mov byte [ap_version], 0
        mov byte [ap_label], 0
        mov byte [ap_activity], 0
        mov dword [ap_perms], 0
        mov dword [ap_minsdk], 0
        mov dword [ap_app], 0
        ; valida
        movzx eax, word [r12]
        cmp eax, 0x0003
        jne .done
        ; pool de strings = primeiro chunk após o cabeçalho (8 bytes)
        lea rdi, [r12+8]
        movzx eax, word [rdi]
        cmp eax, 0x0001
        jne .done
        call axml_pool
        ; varre chunks a partir do fim do pool
        mov rbx, r12
        add rbx, 8
        mov eax, [rbx+4]
        add rbx, rax                    ; próximo chunk
.chunk:
        ; fim?
        mov rax, r12
        add rax, r13
        cmp rbx, rax
        jae .done
        movzx eax, word [rbx]
        cmp eax, 0x0102
        je .start_elem
        cmp eax, 0x0101
        je .skip_chunk
        jmp .skip_chunk
.start_elem:
        ; nome do elemento = pool[dword[rbx+20]]
        mov edi, [rbx+20]
        call sp_get
        ; rax=ptr, rdx=len
        ; compara com os elementos de interesse
        lea rdi, [sp_buf]
        lea rsi, [s_el_manifest]
        call k_strcmp
        test rax, rax
        jz .is_manifest
        lea rdi, [sp_buf]
        lea rsi, [s_el_application]
        call k_strcmp
        test rax, rax
        jz .is_application
        lea rdi, [sp_buf]
        lea rsi, [s_el_activity]
        call k_strcmp
        test rax, rax
        jz .is_activity
        lea rdi, [sp_buf]
        lea rsi, [s_el_permission]
        call k_strcmp
        test rax, rax
        jz .is_permission
        lea rdi, [sp_buf]
        lea rsi, [s_el_uses_sdk]
        call k_strcmp
        test rax, rax
        jz .is_sdk
        jmp .skip_chunk
.is_manifest:
        call axml_scan_package
        jmp .skip_chunk
.is_application:
        mov dword [ap_app], 1
        call axml_scan_label
        jmp .skip_chunk
.is_activity:
        cmp byte [ap_activity], 0
        jne .skip_chunk
        call axml_scan_activity
        jmp .skip_chunk
.is_permission:
        inc dword [ap_perms]
        jmp .skip_chunk
.is_sdk:
        call axml_scan_sdk
        jmp .skip_chunk
.skip_chunk:
        mov eax, [rbx+4]                ; tamanho do chunk
        test eax, eax
        jz .done
        add rbx, rax
        jmp .chunk
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; axml_attr: rbx=chunk, rdi=nome do atributo -> rax=ptr do valor (axml_val_*),
;             CF=1 se achou; valor em sp_val (string) ou eax (inteiro)
axml_attr:
        push rbx
        push r12
        push r13
        mov r12, rdi
        ; varre atributos
        movzx edx, word [rbx+28]        ; attrCount
        test edx, edx
        jz .no
        movzx ecx, word [rbx+24]        ; attrStart
        lea r13, [rbx + rcx]            ; primeiro atributo
.scan:
        test edx, edx
        jz .no
        ; nome do atributo = pool[dword[r13+4]]
        push rdx
        mov edi, [r13+4]
        call sp_get
        lea rdi, [sp_buf]
        mov rsi, r12
        call k_strcmp
        pop rdx
        test rax, rax
        jz .found
        add r13, 20
        dec edx
        jmp .scan
.found:
        ; valor: rawValue ou tipado
        mov eax, [r13+8]                ; rawValue (idx ou -1)
        cmp eax, -1
        je .typed
        mov edi, eax
        call sp_get
        mov rax, sp_buf
        mov dword [axml_val_type], 1    ; string
        clc
        jmp .out
.typed:
        movzx eax, byte [r13+15]        ; dataType
        mov [axml_val_type], eax
        mov eax, [r13+16]               ; data
        mov [axml_val_int], eax
        mov rax, axml_val_int
        clc
        jmp .out
.no:
        stc
.out:
        pop r13
        pop r12
        pop rbx
        ret

axml_scan_package:
        lea rdi, [s_at_package]
        call axml_attr
        jc .done
        ; copia para ap_package
        cmp dword [axml_val_type], 1
        jne .done
        lea rdi, [ap_package]
        mov rsi, rax
        mov ecx, 63
.cp:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .done
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
.done:
        ret

axml_scan_label:
        lea rdi, [s_at_label]
        call axml_attr
        jc .done
        cmp dword [axml_val_type], 1
        jne .ref
        lea rdi, [ap_label]
        mov rsi, rax
        mov ecx, 63
.cp:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .done
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
        ret
.ref:
        ; referência a recurso: @0xXXXXXXXX
        mov rax, [axml_val_int]
        mov [ap_label_ref], eax
        mov dword [ap_label_isref], 1
.done:
        ret

axml_scan_activity:
        lea rdi, [s_at_name]
        call axml_attr
        jc .done
        cmp dword [axml_val_type], 1
        jne .done
        lea rdi, [ap_activity]
        mov rsi, rax
        mov ecx, 63
.cp:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .done
        inc rsi
        inc rdi
        dec ecx
        jnz .cp
.done:
        ret

axml_scan_sdk:
        lea rdi, [s_at_minsdk]
        call axml_attr
        jc .done
        cmp dword [axml_val_type], 0x10
        jne .done
        mov eax, [axml_val_int]
        mov [ap_minsdk], eax
.done:
        ret

; -----------------------------------------------------------------------------
; dex_report: rdi=buf, rsi=size — resume classes.dex
; -----------------------------------------------------------------------------
dex_report:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        ; magic "dex\n"
        cmp dword [r12], 0x0A786564
        jne .done
        mov r13d, [r12+96]              ; class_defs_size
        mov r14d, [r12+100]             ; class_defs_off
        ; string_ids
        mov r15d, [r12+56]
        ; imprime contagem
        mov rdi, s_dex_classes
        call co_str
        mov edi, r13d
        call co_dec
        mov rdi, s_dex_strs
        call co_str
        mov edi, r15d
        call co_dec
        call co_nl
        ; lista até 8 classes
        xor ecx, ecx
.cls:
        cmp ecx, r13d
        jae .done
        cmp ecx, 8
        jae .done
        ; class def
        mov eax, r14d
        lea rbx, [r12 + rax]
        mov eax, ecx
        shl eax, 5
        add rbx, rax
        mov edi, [rbx]                  ; class_idx
        ; string_ids[class_idx] -> dword offset em r12+string_ids_off
        mov eax, [r12+60]               ; string_ids_off
        lea rax, [r12 + rax]
        mov edi, [rax + rdi*4]          ; string_data_off
        lea r8, [r12 + rdi]
        ; pula uleb128 do comprimento
.uleb:
        mov al, [r8]
        inc r8
        test al, 0x80
        jnz .uleb
        ; nome: Lfoo/bar/Baz; — copia sem o L e o ;
        mov rdi, s_class_line
        call co_str
        lea rdi, [sp_buf2]
        xor edx, edx
.cp:
        mov al, [r8 + rdx]
        test al, al
        jz .cd
        cmp al, ';'
        je .cd
        cmp al, '/'
        jne .nosep
        mov al, '.'
.nosep:
        mov [rdi], al
        inc rdi
        inc rdx
        cmp edx, 60
        jb .cp
.cd:
        mov byte [rdi], 0
        lea rdi, [sp_buf2]
        call co_str
        call co_nl
        inc ecx
        jmp .cls
.done:
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; -----------------------------------------------------------------------------
; apk_run: rdi=zip, rsi=size, rdx=nome -> rax=0
; -----------------------------------------------------------------------------
apk_run:
        push rbx
        push r12
        push r13
        push r14
        push r15
        mov r12, rdi
        mov r13, rsi
        mov r14, rdx
        ; cabeçalho
        mov rdi, s_apk_hdr1
        call co_str
        mov rdi, r14
        call co_str
        mov rdi, s_apk_hdr2
        call co_str
        mov edi, r13d
        call co_dec
        call co_nl
        ; manifesto
        mov rdi, r12
        mov rsi, r13
        lea rdx, [s_f_manifest]
        call zip_load
        test rax, rax
        jz .no_manifest
        mov rbx, rax
        mov r15, rdx
        mov rdi, rbx
        mov rsi, r15
        call axml_run
        mov rdi, rbx
        mov rsi, r15
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
        ; relatório
        mov rdi, s_ap_package
        call co_str
        mov rdi, ap_package
        call co_str
        call co_nl
        mov rdi, s_ap_version
        call co_str
        mov rdi, ap_version
        call co_str
        call co_nl
        mov rdi, s_ap_label
        call co_str
        cmp dword [ap_label_isref], 0
        je .lbl_str
        mov rdi, s_at_ref
        call co_str
        mov edi, [ap_label_ref]
        call co_hex16
        call co_nl
        jmp .lbl_done
.lbl_str:
        mov rdi, ap_label
        call co_str
        call co_nl
.lbl_done:
        cmp byte [ap_activity], 0
        je .no_act
        mov rdi, s_ap_activity
        call co_str
        mov rdi, ap_activity
        call co_str
        call co_nl
.no_act:
        mov rdi, s_ap_perms
        call co_str
        mov edi, [ap_perms]
        call co_dec
        call co_nl
        cmp dword [ap_minsdk], 0
        je .no_sdk
        mov rdi, s_ap_minsdk
        call co_str
        mov edi, [ap_minsdk]
        call co_dec
        call co_nl
.no_sdk:
        jmp .dex
.no_manifest:
        mov rdi, s_apk_nomanifest
        call co_str
.dex:
        ; classes.dex
        mov rdi, r12
        mov rsi, r13
        lea rdx, [s_f_dex]
        call zip_load
        test rax, rax
        jz .no_dex
        mov rbx, rax
        mov r15, rdx
        mov rdi, rbx
        mov rsi, r15
        call dex_report
        mov rdi, rbx
        mov rsi, r15
        add rsi, 4095
        and rsi, -4096
        call k_free_bytes
.no_dex:
        ; bibliotecas nativas
        call apk_scan_libs
        mov rdi, s_apk_done
        call co_str
        xor rax, rax
        pop r15
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; apk_scan_libs: r12=zip, r13=size — lista lib/*/lib*.so
apk_scan_libs:
        push rbx
        ; acha EOCD de novo
        mov rax, r12
        add rax, r13
        mov rcx, rax
        sub rcx, 22
        mov rbx, rax
        sub rbx, 1024
        cmp rbx, r12
        jae .scan
        mov rbx, r12
.scan:
        cmp rbx, rcx
        ja .done
        cmp dword [rbx], 0x06054B50
        je .found
        inc rbx
        jmp .scan
.found:
        movzx eax, word [rbx+16]
        mov [zp_count], eax
        mov eax, [rbx+20]
        add rax, r12
        mov rbx, rax
        xor r14d, r14d
.ent:
        cmp r14d, [zp_count]
        jae .done
        cmp dword [rbx], 0x02014B50
        jne .done
        lea rdi, [sp_buf2]
        mov rsi, rbx
        call zip_name
        ; começa com "lib/"?
        lea rdi, [sp_buf2]
        lea rsi, [s_f_lib]
        call k_strcasecmp
        test rax, rax
        jnz .next
        ; termina com ".so"?
        lea rdi, [sp_buf2]
        call k_strlen
        cmp rax, 4
        jb .next
        lea rdi, [sp_buf2]
        add rdi, rax
        sub rdi, 3
        lea rsi, [s_f_so]
        call k_strcasecmp
        test rax, rax
        jnz .next
        ; imprime
        mov rdi, s_apk_lib
        call co_str
        lea rdi, [sp_buf2]
        call co_str
        call co_nl
.next:
        movzx edx, word [rbx+28]
        add edx, 46
        movzx eax, word [rbx+30]
        add edx, eax
        movzx eax, word [rbx+32]
        add edx, eax
        add rbx, rdx
        inc r14d
        jmp .ent
.done:
        pop rbx
        ret

; -----------------------------------------------------------------------------
; sh_run: rdi=buf, rsi=size, rdx=nome — script simples de linhas "exec X"
; -----------------------------------------------------------------------------
sh_run:
        push rbx
        push r12
        push r13
        push r14
        mov r12, rdi
        mov r13, rsi
        mov r14, rdx
        mov rdi, s_sh_hdr
        call co_str
        mov rdi, r14
        call co_str
        call co_nl
        ; linha a linha
        mov rbx, r12
        mov rax, r12
        add rax, r13
        mov [sh_end], rax
.line:
        cmp rbx, [sh_end]
        jae .done
        ; copia até \n em sh_line (máx 62)
        lea rdi, [sh_line]
        xor ecx, ecx
.cp:
        cmp rbx, [sh_end]
        jae .cd
        mov al, [rbx]
        cmp al, 10
        je .cd
        cmp al, 13
        je .skip_ch
        cmp ecx, 62
        jae .skip_ch
        mov [rdi], al
        inc rdi
        inc ecx
.skip_ch:
        inc rbx
        jmp .cp
.cd:
        inc rbx                        ; come o \n
        mov byte [rdi], 0
        ; processa
        lea rdi, [sh_line]
        call sh_trim
        ; vazia ou comentário?
        cmp byte [sh_line], 0
        je .line
        cmp byte [sh_line], '#'
        je .line
        ; "exec X"?
        lea rdi, [sh_line]
        lea rsi, [s_sh_exec]
        call k_strcasecmp
        test rax, rax
        jnz .plain
        ; nome depois de "exec "
        lea rdi, [sh_line + 5]
        call k_exec
        jmp .line
.plain:
        ; tenta executar como nome de arquivo
        lea rdi, [sh_line]
        call k_exec
        jmp .line
.done:
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

; sh_trim: rdi=sh_line — remove espaços do início/fim
sh_trim:
        ; início
.l:
        cmp byte [rdi], ' '
        jne .s
        inc rdi
        jmp .l
.s:
        ; move para o início
        mov rsi, rdi
        lea rdi, [sh_line]
        ; se rsi == rdi, nada a fazer
        cmp rsi, rdi
        je .tail
.mv:
        mov al, [rsi]
        mov [rdi], al
        test al, al
        jz .tail
        inc rsi
        inc rdi
        jmp .mv
.tail:
        ; corta espaços do fim
        mov rdi, sh_line
        call k_strlen
        lea rdi, [sh_line]
        add rdi, rax
        dec rdi
        ; rdi aponta o último char
        cmp rdi, sh_line
        jb .fin
        cmp byte [rdi], ' '
        jne .fin
        mov byte [rdi], 0
        jmp .tail
.fin:
        ret

; -----------------------------------------------------------------------------
; txt_run: rdi=buf, rsi=size, rdx=nome — mostra o conteúdo
; -----------------------------------------------------------------------------
txt_run:
        push rbx
        push r12
        push r13
        push r14
        mov r12, rdi
        mov r13, rsi
        mov r14, rdx
        mov rdi, s_txt_hdr1
        call co_str
        mov rdi, r14
        call co_str
        mov rdi, s_txt_hdr2
        call co_str
        mov edi, r13d
        call co_dec
        call co_nl
        ; até 24 linhas
        mov rbx, r12
        mov rax, r12
        add rax, r13
        mov [sh_end], rax
        xor r15d, r15d
.line:
        cmp rbx, [sh_end]
        jae .done
        cmp r15d, 24
        jae .more
        lea rdi, [sh_line]
        xor ecx, ecx
.cp:
        cmp rbx, [sh_end]
        jae .cd
        mov al, [rbx]
        cmp al, 10
        je .cd
        cmp ecx, 62
        jae .skip
        mov [rdi], al
        inc rdi
        inc ecx
.skip:
        inc rbx
        jmp .cp
.cd:
        inc rbx
        mov byte [rdi], 0
        lea rdi, [sh_line]
        call co_str
        call co_nl
        inc r15d
        jmp .line
.more:
        mov rdi, s_txt_more
        call co_str
        call co_nl
.done:
        pop r14
        pop r13
        pop r12
        pop rbx
        ret

section .kdata
zload_buf: dq 0
zload_method: dd 0
z_empty:  db 0
zp_count: dd 0
zp_cdir:  dq 0
numbuf3:  times 40 db 0

; string pool do AXML
sp_count:   dd 0
sp_utf8:    dd 0
sp_offsets: dq 0
sp_strings: dq 0
sp_buf:     times 128 db 0
sp_buf2:    times 128 db 0

; estado do APK
ap_package:  times 64 db 0
ap_version:  times 64 db 0
ap_label:    times 64 db 0
ap_activity: times 64 db 0
ap_perms:    dd 0
ap_minsdk:   dd 0
ap_app:      dd 0
ap_label_ref: dd 0
ap_label_isref: dd 0
axml_val_type: dd 0
axml_val_int:  dd 0

sh_end:  dq 0
sh_line: times 64 db 0

s_con_nl:  db 10
s_el_manifest:    db "manifest", 0
s_el_application: db "application", 0
s_el_activity:    db "activity", 0
s_el_permission:  db "uses-permission", 0
s_el_uses_sdk:    db "uses-sdk", 0
s_at_package: db "package", 0
s_at_label:   db "label", 0
s_at_name:    db "name", 0
s_at_minsdk:  db "minSdkVersion", 0
s_at_ref:     db "@0x", 0
s_f_manifest: db "AndroidManifest.xml", 0
s_f_dex:      db "classes.dex", 0
s_f_lib:      db "lib/", 0
s_f_so:       db ".so", 0
s_dex_classes: db "dex: ", 0
s_dex_strs:    db " classes, ", 0
s_class_line:  db "  classe: ", 0
s_apk_hdr1: db "APK: ", 0
s_apk_hdr2: db " (", 0
s_apk_done: db "APK analisado com sucesso.", 0
s_apk_nomanifest: db "APK: sem AndroidManifest.xml", 0
s_ap_package:  db "pacote.....: ", 0
s_ap_version:  db "versao.....: ", 0
s_ap_label:    db "rotulo.....: ", 0
s_ap_activity: db "activity...: ", 0
s_ap_perms:    db "permissoes.: ", 0
s_ap_minsdk:   db "minSdk.....: ", 0
s_apk_lib:     db "lib........: ", 0
s_sh_hdr:   db "== script ", 0
s_sh_exec:  db "exec ", 0
s_txt_hdr1: db "== ", 0
s_txt_hdr2: db " (", 0
s_txt_more: db "... (truncado)", 0

%endif
