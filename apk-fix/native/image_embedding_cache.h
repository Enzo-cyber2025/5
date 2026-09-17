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
    struct Entry { Key key; std::vector<float> values; };
    std::list<Entry> entries;
    size_t used=0;
public:
    size_t bytes() const { return used; }
    size_t size() const { return entries.size(); }
    void clear() { entries.clear();used=0; }
    float * find(const Key &key,size_t count) {
        for(auto it=entries.begin();it!=entries.end();++it) {
            if(it->key==key && it->values.size()==count) {
                entries.splice(entries.begin(),entries,it);
                return entries.front().values.data();
            }
        }
        return nullptr;
    }
    bool store(const Key &key,const float *data,size_t count) {
        if(!data || !count || count>capacity_bytes/sizeof(float))return false;
        if(find(key,count))return true;
        try {
            // Allocate first: failure cannot leave partially replaced entries.
            Entry candidate{key,std::vector<float>(data,data+count)};
            entries.push_front(std::move(candidate));used+=count*sizeof(float);
            while(used>capacity_bytes || entries.size()>capacity_entries) {
                used-=entries.back().values.size()*sizeof(float);entries.pop_back();
            }
            return true;
        } catch(const std::bad_alloc &) {clear();return false;}
    }
};
