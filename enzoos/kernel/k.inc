; =============================================================================
;  EnzoOS — kernel/k.inc: constantes, macros e deslocamentos de estruturas
; =============================================================================
%ifndef K_INC
%define K_INC

; ---- layout de memória -----------------------------------------------------
%define KBASE        0x100000        ; kernel
%define HEAP_START   0x400000        ; heap (bitmap + alocações)
%define HEAP_MAX     0x20000000      ; limite superior do heap (512 MB)
%define PE_BASE      0x10000000      ; imagens PE (.exe/.dll)
%define PE_BASE_MAX  0x18000000
%define ELF_BASE     0x18000000      ; imagens ELF (.run/.so)
%define ELF_BASE_MAX 0x1C000000
%define FSTACK_BASE  0x1C000000      ; pilhas de processos estrangeiros
%define FSTACK_SIZE  0x00100000      ; 1 MB por processo

; ---- boot params (offsets a partir de 0xE00) -------------------------------
%define BP_LFB       0x08            ; u64
%define BP_W         0x10
%define BP_H         0x14
%define BP_BPP       0x18
%define BP_PITCH     0x1C
%define BP_IMG       0x20            ; base da imagem de boot
%define BP_CEFS      0x24            ; offset do CEFS
%define BP_IMGSIZE   0x28
%define BP_E820N     0x2C
%define BP_E820P     0x30

; ---- CEFS ------------------------------------------------------------------
%define CEFS_HDR     16              ; tamanho do cabeçalho CEFS
%define CEFS_ENT     32              ; tamanho da entrada
%define CEN_NAME     0               ; +0  nome[20]
%define CEN_OFF      20              ; +20 u32 offset
%define CEN_SIZE     24              ; +24 u32 tamanho
%define CEN_FLAGS    28              ; +28 u32 flags

; ---- interface de janela ---------------------------------------------------
%define TITLE_H      28
%define TASKBAR_H    44
%define MAX_WND      16
%define MAX_APPS     16
%define MAX_FILES    32              ; arquivos no CEFS

; ---- estrutura Window (96 bytes) -------------------------------------------
%define W_NEXT       0               ; qword
%define W_PREV       8               ; qword
%define W_X          16              ; dword
%define W_Y          20
%define W_W          24
%define W_H          28
%define W_BUF        32              ; qword ptr
%define W_TITLE      40              ; char[32]
%define W_APP        72              ; dword slot (0xFFFFFFFF = sem app)
%define W_FLAGS      76              ; bit0 drag, bit1 minimizado, bit2 capture
%define W_DRAGDX     80
%define W_DRAGDY     84
%define W_SIZE       96

; ---- estrutura AppSlot (64 bytes) ------------------------------------------
%define A_USED       0               ; dword
%define A_IMG        8               ; qword
%define A_SIZE       16              ; qword
%define A_ENTRY      24              ; qword
%define A_NAME       32              ; char[20]
%define A_WND        56              ; qword
%define A_PRIV       56              ; (mesmo campo: janela) — priv fica no app
%define A_SIZEOF     64

; ---- cabeçalho .ce (Certamente Executável) ---------------------------------
%define CE_MAGIC     0x31304543      ; "CE01"
%define CE_HDRSZ     64
%define CE_FLAGS     6               ; +6  u16
%define CE_ENTRY     8               ; +8  u32
%define CE_ISIZE     12              ; +12 u32
%define CE_APIVER    20              ; +20 u32

; ---- eventos ---------------------------------------------------------------
%define EV_INIT      1
%define EV_PAINT     2
%define EV_MOUSE     3
%define EV_KEY       4
%define EV_TICK      5
%define EV_QUIT      6

; ---- cores (0x00RRGGBB) ----------------------------------------------------
%define COL_BG       0x0B1220
%define COL_PANEL    0x101726
%define COL_PANEL2   0x18223A
%define COL_TITLE    0x1D3A6E
%define COL_TITLE_D  0x1A2233
%define COL_ACCENT   0x10A372
%define COL_ACCENT2  0x2D9CDB
%define COL_WHITE    0xF2F5FA
%define COL_GRAY     0x8FA0B8
%define COL_DGRAY    0x445066
%define COL_RED      0xE05555
%define COL_CONBG    0x0A0E18
%define COL_YELLOW   0xE8C558
%define COL_CYAN     0x56C8D8

; ---- eventos / especiais ---------------------------------------------------
%define TICK_MS     50
%define SP_BACK     0x80
%define SP_CTRL     0x81
%define SP_LSHIFT   0x82
%define SP_LALT     0x83
%define SP_CAPS     0x84
%define SP_ESC      0x85
%define SP_UP       0x86
%define SP_DOWN     0x87
%define SP_LEFT     0x88
%define SP_RIGHT    0x89
%define SP_HOME     0x8A
%define SP_END      0x8B
%define SP_PGUP     0x8C
%define SP_PGDN     0x8D
%define SP_DEL      0x8E
%define SP_INS      0x8F
%define SP_F1       0x90
%define SP_F2       0x91
%define SP_F3       0x92
%define SP_F4       0x93
%define SP_F5       0x94
%define SP_F6       0x95
%define SP_F7       0x96
%define SP_F8       0x97
%define SP_F9       0x98
%define SP_F10      0x99
%define SP_F11      0x9A
%define SP_F12      0x9B

; boot params em 0xE00 (gravados pelo stage1)
boot_params equ 0x0E00

; ---- macros utilitárias ----------------------------------------------------
%macro ZERO64 1
        xor eax, eax
        mov %1, rax
%endmacro

%endif ; K_INC
