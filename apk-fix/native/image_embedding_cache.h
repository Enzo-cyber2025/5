#pragma once
#include <array>
#include <cstddef>
#include <list>
#include <new>
#include <vector>
#include <utility>

// Per-Engine exact prepared-image embeddings. Optional bounded RAM cache, not
// an image/input quota. Caller owns the Engine mutex and consumes a returned
// pointer before another store/clear. Cache failure never changes inference.
class ImageEmbeddingCache {
public:
    using Key = std::array<unsigned char,32>;
    static constexpr size_t capacity_bytes = 16*1024*1024;
    static constexpr size_t capacity_entries = 128;
private:
    struct Entry { Key key; std::vector<float> values; bool current_request; };
    std::list<Entry> entries;
    size_t used=0;
public:
    size_t bytes() const { return used; }
    size_t size() const { return entries.size(); }
    void clear() { entries.clear();used=0; }
    void begin_request() {for(auto &entry:entries)entry.current_request=false;}
    float * find(const Key &key,size_t count) {
        for(auto it=entries.begin();it!=entries.end();++it) {
            if(it->key==key && it->values.size()==count) {
                it->current_request=true;
                entries.splice(entries.begin(),entries,it);
                return entries.front().values.data();
            }
        }
        return nullptr;
    }
    bool store(const Key &key,const float *data,size_t count) {
        if(!data || !count || count>capacity_bytes/sizeof(float))return false;
        if(find(key,count))return true;
        // Scan resistance: do not evict an entry already used/admitted in this
        // request. Otherwise a cyclic scan larger than the cache misses forever,
        // worse than retaining the first subset. Refusal affects caching only.
        size_t available=capacity_bytes-used,slots=capacity_entries-entries.size();
        for(const auto &entry:entries)if(!entry.current_request) {
            available+=entry.values.size()*sizeof(float);slots++;
        }
        if(available<count*sizeof(float) || !slots)return false;
        try {
            // Allocate first: failure cannot leave partially replaced entries.
            Entry candidate{key,std::vector<float>(data,data+count),true};
            entries.push_front(std::move(candidate));used+=count*sizeof(float);
            auto it=entries.end();
            while(it!=entries.begin() && (used>capacity_bytes || entries.size()>capacity_entries)) {
                --it;
                if(!it->current_request) {used-=it->values.size()*sizeof(float);it=entries.erase(it);}
            }
            return true;
        } catch(const std::bad_alloc &) {clear();return false;}
    }
};
