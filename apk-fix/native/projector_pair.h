#pragma once
#include "mtmd.h"
#include <memory>
#include <stdexcept>
#include <climits>

// A bounded pair of pure vision encodes. The batch owns its copied output until
// the next image is consumed; text/positions/LLM evaluation stay in original order.
class ProjectorPair {
    std::unique_ptr<mtmd_batch,decltype(&mtmd_batch_free)> batch{nullptr,mtmd_batch_free};
    const mtmd_input_chunk * pending=nullptr;
public:
    bool ready(const mtmd_input_chunk *chunk) const {return pending==chunk && pending;}
    float * output(const mtmd_input_chunk *chunk) {
        if(!batch)return nullptr;
        auto *p=mtmd_batch_get_output_embd(batch.get(),chunk);
        if(!p)throw std::runtime_error("Projetor não devolveu o recorte do lote");
        return p;
    }
    bool start(mtmd_context *ctx,const mtmd_input_chunk *first,const mtmd_input_chunk *second) {
        if(pending)throw std::runtime_error("Lote visual anterior ainda não consumido");
        if(!second)return false;
        const auto a=mtmd_input_chunk_get_n_tokens(first),b=mtmd_input_chunk_get_n_tokens(second);
        if(a>(size_t)INT_MAX || b>(size_t)INT_MAX-a)return false; // upstream adds int32 token counts
        batch.reset(mtmd_batch_init(ctx));
        if(!batch || mtmd_batch_add_chunk(batch.get(),first)!=0)
            throw std::runtime_error("Falha ao iniciar lote visual");
        const int result=mtmd_batch_add_chunk(batch.get(),second);
        if(result==2 || result==3) {batch.reset();return false;} // single GPU encode, NOT CPU fallback
        if(result!=0)throw std::runtime_error("Recorte incompatível com o projetor");
        if(mtmd_batch_encode(batch.get())!=0)
            throw std::runtime_error("Falha no lote do projetor Vulkan; sem fallback CPU");
        pending=second;return true;
    }
    void consumed(const mtmd_input_chunk *chunk) {
        if(ready(chunk)) {pending=nullptr;batch.reset();}
    }
};
