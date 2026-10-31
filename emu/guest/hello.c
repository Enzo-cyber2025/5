/* A real Windows executable's entry point, written to be translatable.
 *
 * This file is compiled by mingw-w64 in CI into an ordinary PE - real headers, real
 * sections, a real import table for kernel32 - and the linker is told to make
 * guest_main the image entry point with -nostartfiles, so what the translator is
 * pointed at is compiler-generated code rather than a CRT startup that this subset
 * cannot follow.
 *
 * Every construct here was chosen against the measured subset, not against style:
 *
 *   - Only imported functions are called. A call to an imported function compiles to
 *     `call qword ptr [rip+IAT]` (FF 15), which the translator resolves through the
 *     import table. A call to another function in this file would compile to
 *     `call rel32` (E8), which is refused - there is no runtime dispatcher yet, and
 *     that refusal is the single largest reason a real downloaded executable does not
 *     run. Keeping this file to imported calls only is what makes it a test of the
 *     import path instead of a test of the dispatcher.
 *   - No local variables. mingw allocates 32 bytes of shadow space before a call
 *     regardless, so `sub rsp,32` appears anyway, but nothing else touches the guest
 *     stack and no address of a local is taken.
 *   - The message is a file-scope const array, so the guest reaches it with a
 *     RIP-relative `lea` into the image's own .rdata, which is the access form the
 *     bounds check already covers.
 *   - The length is `sizeof msg - 1`, which the compiler folds to an immediate, so no
 *     strlen call and no loop.
 *
 * Nothing here is Windows-specific beyond the three APIs, and the file contains no
 * third-party code. */

#include <windows.h>

static const char msg[] =
    "REAL PE RAN: an open-source Windows executable built by mingw-w64, its entry "
    "point pre-translated to AArch64, persisted, reloaded from the cache and "
    "executed, calling GetStdHandle and WriteFile through the host ABI bridge\r\n";

/* Non-static and named other than `main`: the linker's --entry points at it, and GCC
 * does not insert a call to __main in a function it does not believe is main. */
int guest_main(void)
{
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);

    /* lpOverlapped and lpNumberOfBytesWritten are both NULL, so the fourth argument
     * is a zeroed register (xor r9d,r9d, the idiom the translator already models)
     * rather than the address of a local. */
    WriteFile(h, msg, (DWORD)(sizeof msg - 1u), NULL);

    /* Returns rather than calling ExitProcess. A real entry point would not return -
     * the CRT would call ExitProcess - but the harness that runs the translated code
     * needs control back to collect a result, and the shim for ExitProcess does not
     * terminate either. Stated here rather than left to look faithful. */
    return 0;
}
