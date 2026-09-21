#pragma once
#include "media_prefix.h"
#include "llama.h"
#include "mtmd.h"
#include <cstring>
#include <cstdlib>
#include <new>
#include <stdexcept>

inline bool media_prefix_opt_in() {
    const char *value=std::getenv("GGUF_MEDIA_PREFIX");
    return value && std::strcmp(value,"1")==0;
}
inline bool media_prefix_model(const llama_model *model) {
    // Start narrowly: no recurrent, encoder, hybrid, SWA or position variants.
    // Caller additionally checks its existing architecture and device policy.
    char arch[32]{},swa[32]{},causal[32]{};
    if(llama_model_meta_val_str(model,"general.architecture",arch,sizeof(arch))!=5 ||
       std::strcmp(arch,"llama")!=0)return false;
    const int c=llama_model_meta_val_str(model,"llama.attention.causal",causal,sizeof(causal));
    if(c>=0 && !(c==4 && std::strcmp(causal,"true")==0))return false;
    const int n=llama_model_meta_val_str(model,"llama.attention.sliding_window",swa,sizeof(swa));
    return n<0 || (n==1 && std::strcmp(swa,"0")==0);
}
inline bool media_prefix_describe(mtmd_context *ctx,const mtmd_input_chunks *chunks,
                                  std::vector<MediaPrefixChunk> &out) {
    out.clear();
    if(mtmd_decode_use_mrope(ctx))return false;
    try {
        const auto count=mtmd_input_chunks_size(chunks);
        for(size_t i=0;i<count;++i) {
            const auto *chunk=mtmd_input_chunks_get(chunks,i);
            const auto type=mtmd_input_chunk_get_type(chunk);
            MediaPrefixChunk d;d.count=mtmd_input_chunk_get_n_tokens(chunk);
            if(!d.count || d.count>size_t(INT32_MAX) ||
               mtmd_input_chunk_get_n_pos(chunk)!=int64_t(d.count) ||
               mtmd_decode_use_non_causal(ctx,chunk))return false;
            if(type==MTMD_INPUT_CHUNK_TYPE_IMAGE) {
                d.image=true;
                if(mtmd_gguf_image_fingerprint(chunk,d.pixels.data())!=0)return false;
            } else if(type==MTMD_INPUT_CHUNK_TYPE_TEXT) {
                size_t n=0;const auto *tokens=mtmd_input_chunk_get_tokens_text(chunk,&n);
                if(!tokens || n!=d.count)return false;
                d.text.assign(tokens,tokens+n);
            } else return false;
            out.push_back(std::move(d));
        }
        return !out.empty() && !out.back().image;
    } catch(const std::bad_alloc &) {out.clear();return false;} // optional optimization
}
inline std::vector<uint8_t> media_prefix_snapshot(llama_context *ctx) {
    llama_synchronize(ctx);
    const auto size=llama_state_seq_get_size(ctx,0);
    if(!size)throw std::runtime_error("Estado KV indisponível para verificação");
    std::vector<uint8_t> data(size);
    if(llama_state_seq_get_data(ctx,data.data(),data.size(),0)!=size)
        throw std::runtime_error("Leitura incompleta do estado KV");
    return data;
}
