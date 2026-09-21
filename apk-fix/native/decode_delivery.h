#pragma once

// Submit only a token which was actually sampled. This is NOT speculative decode.
// Keep first-text delivery immediate; overlap later GPU work with JNI/UI work.
// Never decode the final emitted token just to discard its output.
template<class Decode, class Deliver>
static inline void decode_and_deliver(bool gpu, bool first, bool has_next,
                                      Decode decode, Deliver deliver) {
    if (gpu && !first && has_next) {
        decode();
        deliver();
    } else {
        deliver();
        if (has_next) decode();
    }
}
