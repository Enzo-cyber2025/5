#pragma once
#include <algorithm>
#include <cstddef>
#include <vector>

// Plan only: the caller must still trim real KV memory successfully. Leave at
// least the final input token for decode so logits belong to the current prompt.
// Never reuse recurrent/hybrid state, media embeddings or an evicted SWA prefix.
template<class Token>
size_t reusable_prefix(const std::vector<Token> &cached, const std::vector<Token> &input,
                       bool supported, int pos_min, int pos_max) {
    if (!supported || input.size() < 2 || cached.empty() || pos_min != 0 ||
        pos_max < static_cast<int>(cached.size()) - 1) return 0;
    size_t n = 0, limit = std::min(cached.size(), input.size() - 1);
    while (n < limit && cached[n] == input[n]) ++n;
    return n;
}
