#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

// Metadata only. KV stays in the existing per-Engine selected-device context.
// Complete chunk boundaries preserve upstream attention/position/batch semantics.
struct MediaPrefixChunk {
    bool image=false;
    size_t count=0;
    std::array<unsigned char,32> pixels{};
    std::vector<int32_t> text;
    bool valid() const {
        return count>0 && count<=size_t(std::numeric_limits<int32_t>::max()) &&
               (image?text.empty():text.size()==count);
    }
    bool operator==(const MediaPrefixChunk &other) const {
        return image==other.image && count==other.count &&
               (image?pixels==other.pixels:text==other.text);
    }
};
struct MediaPrefixPlan {size_t chunks=0,tokens=0;};
inline MediaPrefixPlan media_prefix_plan(const std::vector<MediaPrefixChunk> &cached,
        const std::vector<MediaPrefixChunk> &input,bool supported,int pos_min,int pos_max) {
    if(!supported || cached.empty() || input.size()<2 || pos_min!=0 || pos_max<0 ||
       input.back().image)return {};
    size_t old_tokens=0;
    for(const auto &c:cached) {
        if(!c.valid() || c.count>size_t(INT32_MAX)-old_tokens)return {};
        old_tokens+=c.count;
    }
    for(const auto &c:input)if(!c.valid())return {};
    if(old_tokens>size_t(pos_max)+1)return {}; // incomplete/evicted KV: cold path
    MediaPrefixPlan plan;
    // Always replay the full final TEXT chunk, even for an identical prompt.
    // This obtains current logits and never splits an image/attention block.
    const auto limit=std::min(cached.size(),input.size()-1);
    for(size_t i=0;i<limit && cached[i]==input[i];++i) {
        if(input[i].count>size_t(INT32_MAX)-plan.tokens)return {};
        plan.tokens+=input[i].count;plan.chunks++;
    }
    return plan;
}
