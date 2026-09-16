#pragma once
#include <cstdint>
// Linux AArch64 HWCAP bits: baseline probe never executes optional instructions.
// Require FP16 scalar/vector + dot product for both optimized builds.
static inline int cpu_variant(uint64_t hwcap, uint64_t hwcap2) {
    constexpr uint64_t required=(1ULL<<9)|(1ULL<<10)|(1ULL<<20);
    if ((hwcap & required)!=required) return 0;
    return (hwcap2 & (1ULL<<13)) ? 2 : 1;
}
