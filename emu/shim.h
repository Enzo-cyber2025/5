#ifndef EMU_SHIM_H
#define EMU_SHIM_H

/* Host implementations of Win32 functions a translated guest can call, plus the glue
 * that lets the translator reach them through the guest's OWN import table.
 *
 * The shape follows the operating system being imitated rather than inventing one. A
 * Windows loader walks the import directory and writes each resolved function's
 * address into the module's IAT; the compiled code then calls through that slot with
 * `call [rip+IAT]`. This does the same: shim_fill_iat writes host shim addresses into
 * the mapped image's IAT slots, and the translator emits a call that loads its target
 * out of the slot at run time. Nothing absolute is baked into the emitted code, so a
 * cached translation stays valid in any process that maps the same image and fills the
 * same slots. */

#include <stddef.h>
#include <stdint.h>

#include "pe_load.h"
#include "translate.h"

/* How many IAT slots this layer will fill. A bound so a large import table cannot
 * exhaust memory; slots past it are simply left unresolved and reported. */
#define SHIM_MAX_SLOTS 4096u

/* Writes host shim addresses into the mapped image's IAT slots for every imported
 * function this layer implements. `image` is the mapping pe_map_image produced and
 * `base_va` the guest address it stands for, so a slot's RVA becomes a pointer.
 *
 * Returns the number of slots filled and, through the out parameters, how many
 * imported functions were recognised and how many were not. An import this layer does
 * not implement is left exactly as the file had it, which is why the counts are
 * reported separately: filling 3 of 400 is the normal case and should not look like
 * either success or failure.
 *
 * Also records the mapping so the shims can translate a guest pointer into a host
 * one. That state is file-scope, and it has to be: the host ABI bridge marshals four
 * arguments and a shim's signature is fixed by the guest's call, so there is no
 * parameter left to carry a context. One guest module is loaded at a time and the
 * harness runs each function in a forked child, which is what makes a single mapping
 * the right amount of state rather than a shortcut. */
size_t shim_fill_iat(const pe_image *im, uint8_t *image, size_t image_len,
                     uint64_t base_va, size_t *out_known, size_t *out_unknown);

/* A tr_resolve_fn. Answers an IAT slot's guest VA with the slot's RVA tagged
 * TR_ABI_HOST | TR_ABI_INDIRECT, but only for a slot shim_fill_iat actually filled.
 * Anything else returns 0, which the translator reports as TRR_NEEDS_TARGET rather
 * than guessing at - an unresolved import must stay visibly unresolved.
 *
 * Answers TR_Q_IMPORT_CELL only; asked TR_Q_CALL_TARGET it returns 0, because a
 * Win32 function is host code and has no call-table slot to be given.
 *
 * `user` is ignored; the mapping recorded by shim_fill_iat is the context. */
uint64_t shim_resolve(uint64_t guest_iat_va, tr_question q, void *user);

/* Number of distinct Win32 functions this layer implements, for reporting. */
size_t shim_count(void);

#endif /* EMU_SHIM_H */
