#pragma once
#include "windows.h"
inline long ShellExecuteW(void*, const wchar_t*, const wchar_t*, const wchar_t*, const wchar_t*, int) { return 0; }
#ifndef SW_SHOWNORMAL
#define SW_SHOWNORMAL 1
#endif
