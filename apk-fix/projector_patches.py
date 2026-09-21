"""Private app API: fingerprint exact preprocessed vision input without copying pixels.
Pinned mtmd metadata intentionally omits pixels AND anyres geometry; neither
filename, source ID nor serialization alone is an adequate reusable cache key.
No compute, precision, normalization, crop or batching algorithm is changed.
"""
DECL='MTMD_API int32_t mtmd_gguf_image_fingerprint(const mtmd_input_chunk * chunk, unsigned char out[32]);'
IMPL=r'''
// GGUF exact projector cache key v1. Context/model ownership is the app's Engine.
extern "C" {
#include "hash/sha256/sha256.h"
}
int32_t mtmd_gguf_image_fingerprint(const mtmd_input_chunk * chunk, unsigned char out[32]) {
    if(!chunk || !out || chunk->type!=MTMD_INPUT_CHUNK_TYPE_IMAGE ||
       !chunk->tokens_image || chunk->is_placeholder())return -1;
    try {
        mtmd_serialization ser(MTMD_SERIALIZATION_VERSION);
        chunk->serialize(ser); // small metadata only; no image payload copy
        sha256_t hash;sha256_init(&hash);
        const char domain[]="GGUF-PREPARED-VISION-1";
        sha256_update(&hash,reinterpret_cast<const unsigned char *>(domain),sizeof(domain));
        sha256_update(&hash,reinterpret_cast<const unsigned char *>(ser.data.data()),ser.data.size());
        for(const auto &image:chunk->tokens_image->batch_f32.entries) {
            // anyres is NOT in mtmd's placeholder serialization. Hash fields
            // individually, never struct padding/uninitialized object bytes.
            const int32_t geometry[]={image.anyres.grid_x,image.anyres.grid_y,
                image.anyres.orig_nx,image.anyres.orig_ny};
            sha256_update(&hash,reinterpret_cast<const unsigned char *>(geometry),sizeof(geometry));
            const auto &pixels=image.get_ro_buf();
            const uint64_t count=pixels.size();
            sha256_update(&hash,reinterpret_cast<const unsigned char *>(&count),sizeof(count));
            if(!pixels.empty())sha256_update(&hash,reinterpret_cast<const unsigned char *>(pixels.data()),pixels.size()*sizeof(float));
        }
        sha256_final(&hash,out);return 0;
    } catch(const std::exception &) {return -1;} // cache is optional
}
'''

def patch_projector(source):
    header=source/'tools/mtmd/mtmd.h';s=header.read_text()
    if DECL not in s:
        marker='// save/load an input chunk to/from a buffer (useful for KV save/load)'
        assert s.count(marker)==1;s=s.replace(marker,DECL+'\n\n'+marker);header.write_text(s)
    cpp=source/'tools/mtmd/mtmd.cpp';s=cpp.read_text()
    if 'GGUF exact projector cache key v1' not in s:cpp.write_text(s+'\n'+IMPL)
    else:assert IMPL.strip() in s, 'Stale projector fingerprint patch; do not silently reuse it'
