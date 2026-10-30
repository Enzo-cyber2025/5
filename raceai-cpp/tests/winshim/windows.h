// windows.h **falso** — só para checar tipos/sintaxe do src/app/main.cpp no
// Linux (o build de verdade acontece no Windows, com a API real).
#pragma once

#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cwchar>

using wchar_t_ = wchar_t;
typedef wchar_t* LPWSTR;
typedef wchar_t* PWSTR;
typedef const wchar_t* LPCWSTR;
typedef char* LPSTR;
typedef const char* LPCSTR;

typedef void* HWND;
typedef void* HDC;
typedef void* HINSTANCE;
typedef void* HMODULE;
typedef void* HMENU;
typedef void* HFONT;
typedef void* HBRUSH;
typedef void* HPEN;
typedef void* HGDIOBJ;
typedef void* HBITMAP;
typedef void* HANDLE;
typedef void* HICON;
typedef void* HCURSOR;
typedef unsigned int UINT;
typedef unsigned long DWORD;
typedef int BOOL;
typedef long LONG;
typedef unsigned long long ULONG_PTR;
typedef long long LONG_PTR;
typedef ULONG_PTR UINT_PTR;
typedef ULONG_PTR WPARAM;
typedef long long LPARAM;
typedef long long LRESULT;
typedef unsigned short WORD;
typedef unsigned char BYTE;
typedef DWORD COLORREF;
typedef int HFILE;
typedef void* LPRECT;

#define WINAPI
#define CALLBACK
#define TRUE 1
#define FALSE 0

struct POINT { LONG x, y; };
struct RECT { LONG left, top, right, bottom; };
struct SIZE { LONG cx, cy; };
struct PAINTSTRUCT { HDC hdc; BOOL fErase; RECT rcPaint; };
struct MSG { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; };
struct WNDCLASSEXW {
    UINT cbSize, style;
    LRESULT (*lpfnWndProc)(HWND, UINT, WPARAM, LPARAM);
    int cbClsExtra, cbWndExtra;
    HINSTANCE hInstance;
    HICON hIcon;
    HCURSOR hCursor;
    HBRUSH hbrBackground;
    LPCWSTR lpszMenuName, lpszClassName;
    HICON hIconSm;
};
struct INITCOMMONCONTROLSEX { DWORD dwSize, dwICC; };
struct OPENFILENAMEW {
    DWORD lStructSize;
    HWND hwndOwner;
    HINSTANCE hInstance;
    LPCWSTR lpstrFilter;
    LPWSTR lpstrCustomFilter;
    DWORD nMaxCustFilter, nFilterIndex;
    LPWSTR lpstrFile;
    DWORD nMaxFile;
    LPWSTR lpstrFileTitle;
    DWORD nMaxFileTitle;
    LPCWSTR lpstrInitialDir, lpstrTitle;
    DWORD Flags;
    WORD nFileOffset, nFileExtension;
    LPCWSTR lpstrDefExt;
    LPARAM lCustData;
    void* lpfnHook;
    LPCWSTR lpTemplateName;
};
struct CREATESTRUCTW { void* lpCreateParams; HINSTANCE hInstance; HMENU hMenu; HWND hwndParent;
                       int cy, cx, y, x; LONG style; LPCWSTR lpszName, lpszClass; DWORD dwExStyle; };

// constantes usadas pelo main.cpp
static const UINT WM_CREATE = 0x0001, WM_DESTROY = 0x0002, WM_PAINT = 0x000F,
                  WM_TIMER = 0x0113, WM_HSCROLL = 0x0114, WM_COMMAND = 0x0111,
                  WM_KEYDOWN = 0x0100, WM_MOUSEWHEEL = 0x020A, WM_ERASEBKGND = 0x0014,
                  WM_SETFONT = 0x0030;
static const DWORD WS_CHILD = 0x40000000L, WS_VISIBLE = 0x10000000L, WS_TABSTOP = 0x00010000L,
                   WS_VSCROLL = 0x00200000L, WS_HSCROLL = 0x00100000L,
                   WS_OVERLAPPEDWINDOW = 0x00CF0000L, WS_EX_CLIENTEDGE = 0x00000200L;
static const DWORD SS_LEFT = 0x0000L, CBS_DROPDOWNLIST = 0x0003L,
                   CBS_OWNERDRAWFIXED = 0x0010L,
                   ES_AUTOHSCROLL = 0x0080, ES_MULTILINE = 0x0004L, ES_WANTRETURN = 0x1000L, ES_AUTOVSCROLL = 0x0040L,
                   ES_READONLY = 0x0800L, CS_HREDRAW = 0x0002, CS_VREDRAW = 0x0001,
                   TBS_AUTOTICKS = 0x0001;
static const int CW_USEDEFAULT = -2147483648;
static const int SW_SHOW = 5, SW_HIDE = 0;
static const int COLOR_WINDOW = 5;
static const UINT MB_OK = 0, MB_ICONERROR = 0x10, MB_ICONINFORMATION = 0x40;
static const UINT ICC_BAR_CLASSES = 4, ICC_WIN95_CLASSES = 0xFF;
static const UINT TBM_GETPOS = 0x400, TBM_SETPOS = 0x405, TBM_SETRANGE = 0x406;
static const UINT CB_ADDSTRING = 0x143, CB_SETCURSEL = 0x14E, CB_GETCURSEL = 0x147,
                  CBN_SELCHANGE = 1;
static const UINT OFN_OVERWRITEPROMPT = 2, OFN_FILEMUSTEXIST = 0x1000,
                  OFN_PATHMUSTEXIST = 0x800, OFN_HIDEREADONLY = 4,
                  OFN_EXPLORER = 0x80000, OFN_ENABLESIZING = 0x800000;
static const int TRANSPARENT = 1, OPAQUE = 2;
static const int PS_SOLID = 0, PS_DOT = 2, PS_NULL = 5;
static const int VK_ESCAPE = 27, VK_LEFT = 37, VK_UP = 38, VK_RIGHT = 39, VK_DOWN = 40,
                  VK_TAB = 9, VK_OEM_PLUS = 0xBB, VK_OEM_MINUS = 0xBD, VK_ADD = 0x6B,
                  VK_SUBTRACT = 0x6D;
static const DWORD MAX_PATH = 260;
static const int DEFAULT_CHARSET = 1, OUT_DEFAULT_PRECIS = 0, CLIP_DEFAULT_PRECIS = 0,
                 DEFAULT_QUALITY = 0, DEFAULT_PITCH = 0, FIXED_PITCH = 1, FW_NORMAL = 400,
                 FW_BOLD = 700;

#define RGB(r, g, b) ((COLORREF)(((BYTE)(r) | ((WORD)((BYTE)(g)) << 8)) | (((DWORD)(BYTE)(b)) << 16)))
#define MAKELONG(a, b) ((LONG)(((WORD)(a)) | ((DWORD)((WORD)(b))) << 16))
#define LOWORD(x) ((WORD)((ULONG_PTR)(x) & 0xffff))
#define HIWORD(x) ((WORD)((ULONG_PTR)(x) >> 16))
#define GET_WHEEL_DELTA_WPARAM(w) ((short)HIWORD(w))
#define ZeroMemory(p, n) std::memset((p), 0, (n))
#define GetModuleHandle GetModuleHandleW
#define CreateWindow CreateWindowW
#define SendMessage SendMessageW
#define TRACKBAR_CLASSW L"msctls_trackbar32"

inline HICON LoadCursor(void*, const wchar_t*) { return nullptr; }
inline HMODULE GetModuleHandleW(const wchar_t*) { return nullptr; }
inline HWND CreateWindowExW(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU,
                            HINSTANCE, void*) { return nullptr; }
inline HWND CreateWindowW(LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE,
                          void*) { return nullptr; }
inline int ShowWindow(HWND, int) { return 0; }
inline int UpdateWindow(HWND) { return 0; }
inline int InvalidateRect(HWND, const RECT*, BOOL) { return 0; }
inline int GetClientRect(HWND, RECT*) { return 0; }
inline int FillRect(HDC, const RECT*, HBRUSH) { return 0; }
inline HDC BeginPaint(HWND, PAINTSTRUCT*) { return nullptr; }
inline int EndPaint(HWND, const PAINTSTRUCT*) { return 0; }
inline HFONT CreateFontW(int, int, int, int, int, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD,
                         DWORD, DWORD, LPCWSTR) { return nullptr; }
inline HBRUSH CreateSolidBrush(COLORREF) { return nullptr; }
inline HPEN CreatePen(int, int, COLORREF) { return nullptr; }
inline HGDIOBJ SelectObject(HDC, HGDIOBJ) { return nullptr; }
inline int DeleteObject(HGDIOBJ) { return 0; }
inline int Polygon(HDC, const POINT*, int) { return 0; }
inline int Rectangle(HDC, int, int, int, int) { return 0; }
inline int MoveToEx(HDC, int, int, POINT*) { return 0; }
inline int LineTo(HDC, int, int) { return 0; }
inline int SetTextColor(HDC, COLORREF) { return 0; }
inline int SetBkMode(HDC, int) { return 0; }
inline COLORREF SetBkColor(HDC, COLORREF) { return 0; }
inline int TextOutW(HDC, int, int, LPCWSTR, int) { return 0; }
inline LRESULT SendMessageW(HWND, UINT, WPARAM, LPARAM) { return 0; }
inline int SetWindowTextW(HWND, LPCWSTR) { return 0; }
inline int GetWindowTextW(HWND, LPWSTR, int) { return 0; }
inline HWND GetDlgItem(HWND, int) { return nullptr; }
inline unsigned short RegisterClassExW(const WNDCLASSEXW*) { return 1; }
inline int GetMessageW(MSG*, HWND, UINT, UINT) { return 0; }
inline int TranslateMessage(const MSG*) { return 0; }
inline long DispatchMessageW(const MSG*) { return 0; }
inline LRESULT DefWindowProcW(HWND, UINT, WPARAM, LPARAM) { return 0; }
inline void PostQuitMessage(int) {}
inline UINT_PTR SetTimer(HWND, UINT_PTR, UINT, void*) { return 1; }
inline int KillTimer(HWND, UINT_PTR) { return 0; }
inline int GetAsyncKeyState(int) { return 0; }
inline int MessageBoxW(HWND, LPCWSTR, LPCWSTR, UINT) { return 1; }
inline DWORD GetModuleFileNameW(HMODULE, LPWSTR, DWORD) { return 0; }
inline int SetEnvironmentVariableW(LPCWSTR, LPCWSTR) { return 1; }
inline int SetCurrentDirectoryW(LPCWSTR) { return 1; }
inline int InitCommonControlsEx(const INITCOMMONCONTROLSEX*) { return 1; }
inline int GetSaveFileNameW(OPENFILENAMEW*) { return 0; }
inline int GetOpenFileNameW(OPENFILENAMEW*) { return 0; }
inline int MultiByteToWideChar(UINT, DWORD, LPCSTR, int, LPWSTR, int) { return 0; }
inline int WideCharToMultiByte(UINT, DWORD, LPCWSTR, int, LPSTR, int, LPCSTR, BOOL*) { return 0; }
inline COLORREF GetSysColor(int) { return 0; }

// modo terminal do jogo (RaceAI2D.exe com argumentos)
static const DWORD ATTACH_PARENT_PROCESS = ((DWORD)-1);
inline int AttachConsole(DWORD) { return 1; }
inline int GetEnvironmentVariableW(LPCWSTR, LPWSTR, DWORD) { return 0; }
inline int CreateDirectoryW(LPCWSTR, void*) { return 1; }
static int __argc_shim = 1;
static char* __argv_shim[1] = {nullptr};
#define __argc __argc_shim
#define __argv __argv_shim

static const UINT CP_UTF8 = 65001;
#define MAKEINTRESOURCEW(i) ((LPWSTR)((ULONG_PTR)((WORD)(i))))
#define IDC_ARROW MAKEINTRESOURCEW(32512)

// --- usados pela checagem de sintaxe no Linux (API real no Windows) ---
#ifndef FILE_ATTRIBUTE_DIRECTORY
#define FILE_ATTRIBUTE_DIRECTORY 0x00000010
#endif
#ifndef INVALID_FILE_ATTRIBUTES
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#endif
#ifndef ICC_STANDARD_CLASSES
#define ICC_STANDARD_CLASSES 0x00004000
#endif
#ifndef SPI_GETWORKAREA
#define SPI_GETWORKAREA 0x0030
#endif
#ifndef PS_DASH
#define PS_DASH 1
#define PS_DOT 2
#endif
#ifndef VK_F2
#define VK_F2 0x71
#define VK_F3 0x72
#endif
#ifndef WM_GETMINMAXINFO
#define WM_GETMINMAXINFO 0x0024
#endif
#ifndef FORMAT_MESSAGE_ALLOCATE_BUFFER
#define FORMAT_MESSAGE_ALLOCATE_BUFFER 0x00000100
#define FORMAT_MESSAGE_FROM_SYSTEM      0x00001000
#define FORMAT_MESSAGE_IGNORE_INSERTS   0x00000200
#endif
struct MINMAXINFO { POINT ptReserved, ptMaxSize, ptMaxPosition, ptMinTrackSize, ptMaxTrackSize; };
inline DWORD GetFileAttributesW(LPCWSTR) { return INVALID_FILE_ATTRIBUTES; }
inline DWORD GetLastError() { return 0; }
inline void* LocalFree(void* p) { return p; }
inline DWORD FormatMessageW(DWORD, const void*, DWORD, DWORD, LPWSTR, DWORD, void*) { return 0; }
inline BOOL SystemParametersInfoW(UINT, UINT, void*, UINT) { return 0; }

// --- desenho da chave (owner-drawn) e controles novos ---
#ifndef BS_OWNERDRAW
#define BS_OWNERDRAW     0x0000000B
#define BS_AUTOCHECKBOX  0x00000003
#define BM_SETCHECK      0x00F1
#define BM_GETCHECK      0x00F0
#define BST_CHECKED      1
#define BST_UNCHECKED    0
#define WM_DRAWITEM      0x002B
#endif
#ifndef CB_RESETCONTENT
#define CB_RESETCONTENT 0x014B
#endif
#ifndef DT_CENTER
#define DT_LEFT     0x00000000
#define DT_CENTER   0x00000001
#define DT_VCENTER  0x00000004
#define DT_SINGLELINE 0x00000020
#endif
#ifndef SRCCOPY
#define SRCCOPY ((DWORD)0x00CC0020)
#endif
#ifndef WM_MEASUREITEM
#define WM_MEASUREITEM 0x002C
#endif
#ifndef DT_END_ELLIPSIS
#define DT_END_ELLIPSIS 0x8000
#endif
#ifndef CB_GETLBTEXT
#define CB_GETLBTEXT   0x0148
#define CB_ERR         (-1)
#endif
#ifndef EN_CHANGE
#define EN_CHANGE     0x0300
#endif
#ifndef WM_CTLCOLORSTATIC
#define WM_CTLCOLORSTATIC 0x0138
#define WM_CTLCOLOREDIT   0x0133
#define WM_CTLCOLORLISTBOX 0x0134
#define WM_CTLCOLORBTN    0x0135
#endif
#ifndef ODT_COMBOBOX
#define ODT_COMBOBOX   3
#endif
#ifndef ODT_BUTTON
#define ODT_BUTTON     4
#define ODS_SELECTED   0x0001
#define ODS_GRAYED     0x0002
#define ODS_DISABLED   0x0004
#define ODS_FOCUS      0x0010
#endif
#ifndef WS_CLIPCHILDREN
#define WS_CLIPCHILDREN 0x02000000
#endif
#ifndef CLEARTYPE_QUALITY
#define CLEARTYPE_QUALITY 5
#endif
#ifndef FW_SEMIBOLD
#define FW_SEMIBOLD 600
#endif
#ifndef OPAQUE
#define OPAQUE 2
#endif
struct MEASUREITEMSTRUCT { UINT CtlType, CtlID, itemID, itemWidth, itemHeight;
                           ULONG_PTR itemData; };
typedef MEASUREITEMSTRUCT* LPMEASUREITEMSTRUCT;
struct DRAWITEMSTRUCT { UINT CtlType, CtlID, itemID, itemAction, itemState;
                        HWND hwndItem; HDC hDC; RECT rcItem; ULONG_PTR itemData; };
inline HDC CreateCompatibleDC(HDC) { return nullptr; }
inline HBITMAP CreateCompatibleBitmap(HDC, int, int) { return nullptr; }
#ifndef FILE_TYPE_CHAR
#define FILE_TYPE_CHAR 0x0002
#define FILE_TYPE_DISK 0x0001
#define FILE_TYPE_PIPE 0x0003
#endif
#ifndef STD_OUTPUT_HANDLE
#define STD_OUTPUT_HANDLE ((DWORD)-11)
#endif
inline DWORD GetFileType(HANDLE) { return FILE_TYPE_CHAR; }
inline HANDLE GetStdHandle(DWORD) { return nullptr; }
inline BOOL DeleteDC(HDC) { return 1; }
inline BOOL BitBlt(HDC, int, int, int, int, HDC, int, int, DWORD) { return 1; }
inline BOOL RoundRect(HDC, int, int, int, int, int, int) { return 1; }
inline int DrawTextW(HDC, LPCWSTR, int, RECT*, UINT) { return 0; }

// ---- extras usados pelo slider próprio e pelas caixas de marcação ----
#ifndef WM_USER
#define WM_USER 0x0400
#endif
#ifndef WM_NCDESTROY
#define WM_NCDESTROY   0x0082
#define WM_LBUTTONDOWN 0x0201
#define WM_LBUTTONUP   0x0202
#define WM_MOUSEMOVE   0x0200
#define WM_CAPTURECHANGED 0x0215
#endif
#ifndef GWL_STYLE
#define GWL_STYLE      (-16)
#define GWLP_USERDATA  (-21)
#endif
#ifndef BS_CHECKBOX
#define BS_CHECKBOX    0x0002
#define BS_3STATE      0x0005
#define BS_AUTO3STATE  0x0006
#endif
#ifndef ODS_CHECKED
#define ODS_CHECKED    0x0008
#endif
#ifndef GET_X_LPARAM
#define GET_X_LPARAM(lp) ((int)(short)LOWORD(lp))
#endif
#ifndef VK_HOME
#define VK_HOME 0x24
#define VK_END  0x23
#define VK_LEFT 0x25
#define VK_RIGHT 0x27
#endif
inline LONG_PTR GetWindowLongPtrW(HWND, int) { return 0; }
inline LONG_PTR SetWindowLongPtrW(HWND, int, LONG_PTR) { return 0; }
inline HWND SetCapture(HWND) { return nullptr; }
inline HWND SetFocus(HWND) { return nullptr; }
inline HWND GetParent(HWND) { return nullptr; }
inline BOOL ReleaseCapture() { return 1; }
inline BOOL Ellipse(HDC, int, int, int, int) { return 1; }
