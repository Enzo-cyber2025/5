#pragma once
// Diagnostic-only: keep GGUF bytes intact; expand immutable weights ON VULKAN.
// No CPU inference/dequant fallback. Engine owns the extra device allocations.
#include "llama-model.h"
#include "ggml-alloc.h"
#include "ggml-backend.h"
#include <cstdlib>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <unordered_set>
#include <vector>

inline bool expanded_flag(const char *name) {
    const char *s=std::getenv(name);return s && std::strcmp(s,"1")==0;
}
inline bool expandable_type(ggml_type t) {
    return t==GGML_TYPE_Q5_0 || t==GGML_TYPE_Q8_0 || t==GGML_TYPE_Q4_K || t==GGML_TYPE_Q6_K;
}
struct ExpandedWeights {
    struct Allocation {
        ggml_context *context=nullptr;
        ggml_backend_buffer_t buffer=nullptr;
        ggml_tensor *original=nullptr,*expanded=nullptr;
        ~Allocation(){if(buffer)ggml_backend_buffer_free(buffer);if(context)ggml_free(context);}
    };
    std::vector<std::unique_ptr<Allocation>> allocations;
    size_t extra_bytes=0,verified_bytes=0;
    static constexpr size_t experimental_limit=size_t(1024)*1024*1024;
    void prepare(llama_model *model,ggml_backend_dev_t device,bool verify,bool repack=false) {
        if(!device || std::strcmp(ggml_backend_dev_name(device),"Vulkan0")!=0)
            throw std::runtime_error("Expansão experimental exige Vulkan0; sem fallback CPU");
        if(!allocations.empty())throw std::runtime_error("Expansão duplicada");
        std::vector<ggml_tensor *> tensors;std::unordered_set<ggml_tensor *> seen;
        size_t planned=0;
        for(const auto &entry:llama_internal_get_tensor_map(model)) {
            auto *t=entry.second;
            if(!seen.insert(t).second || !(repack ? t->type==GGML_TYPE_Q5_0 : expandable_type(t->type)))continue;
            if(t->view_src || !ggml_is_contiguous(t) || t->ne[2]!=1 || t->ne[3]!=1 || t->ne[1]<=1)
                throw std::runtime_error("Layout de peso não qualificado para expansão");
            if(!t->buffer || ggml_backend_buft_get_device(ggml_backend_buffer_get_type(t->buffer))!=device)
                throw std::runtime_error("Peso fora do dispositivo Vulkan selecionado");
            const auto n=ggml_nelements(t);
            if(n<=0 || size_t(n)>experimental_limit/sizeof(float) || size_t(n)*sizeof(float)>experimental_limit-planned)
                throw std::runtime_error("Experimento excede 1 GiB adicional; modelo não foi reduzido");
            planned+=size_t(n)*sizeof(float);tensors.push_back(t);
        }
        if(tensors.empty())throw std::runtime_error("Nenhum peso elegível para o experimento");
        std::unique_ptr<ggml_backend,decltype(&ggml_backend_free)> backend(ggml_backend_dev_init(device,nullptr),ggml_backend_free);
        if(!backend)throw std::runtime_error("Backend de expansão indisponível");
        // Transactional: do not alter ANY model tensor until every allocation,
        // GPU conversion and (when requested) independent value check succeeds.
        for(auto *src:tensors) {
            auto owner=std::make_unique<Allocation>();owner->original=src;
            const size_t meta=ggml_tensor_overhead()*8+ggml_graph_overhead_custom(8,false)+4096;
            owner->context=ggml_init({meta,nullptr,true});
            if(!owner->context)throw std::runtime_error("Sem memória para metadados da expansão");
            ggml_tensor *ids=nullptr,*operation=nullptr;
            if(repack) {
                owner->expanded=ggml_new_tensor(owner->context,GGML_TYPE_Q8_0,4,src->ne);
                operation=ggml_cpy(owner->context,src,owner->expanded);
            } else {
                ids=ggml_new_tensor_1d(owner->context,GGML_TYPE_I32,src->ne[1]);
                owner->expanded=ggml_get_rows(owner->context,src,ids);operation=owner->expanded;
            }
            auto *dst=owner->expanded;
            if(dst->type!=(repack?GGML_TYPE_Q8_0:GGML_TYPE_F32) || !ggml_are_same_shape(src,dst))
                throw std::runtime_error("Expansão alteraria a forma dos pesos");
            if(!ggml_backend_supports_op(backend.get(),operation))
                throw std::runtime_error("GPU não suporta expansão deste tipo; sem fallback");
            owner->buffer=ggml_backend_alloc_ctx_tensors(owner->context,backend.get());
            if(!owner->buffer)throw std::runtime_error("GPU sem memória para expansão opcional");
            if(ids) {
                std::vector<int32_t> rows(size_t(src->ne[1]));
                for(size_t i=0;i<rows.size();++i)rows[i]=int32_t(i); // host orchestration, not weight math
                ggml_backend_tensor_set(ids,rows.data(),0,rows.size()*sizeof(int32_t));
            }
            auto *graph=ggml_new_graph_custom(owner->context,8,false);ggml_build_forward_expand(graph,operation);
            if(ggml_backend_graph_compute(backend.get(),graph)!=GGML_STATUS_SUCCESS)
                throw std::runtime_error("Conversão Vulkan falhou");
            if(verify) {
                // DIAGNOSTIC ONLY, outside all measured generation intervals.
                // Original encoded bytes -> independent CPU reference; NEVER
                // used as inference weights. Compare every float bit, not text.
                std::vector<unsigned char> encoded(ggml_nbytes(src));
                std::vector<float> reference(size_t(ggml_nelements(src))),actual(reference.size());
                ggml_backend_tensor_get(src,encoded.data(),0,encoded.size());
                const auto *traits=ggml_get_type_traits(src->type);
                if(!traits || !traits->to_float)throw std::runtime_error("Referência de desquantização ausente");
                traits->to_float(encoded.data(),reference.data(),ggml_nelements(src));
                if(repack) {
                    std::vector<unsigned char> encoded_target(ggml_nbytes(dst));
                    ggml_backend_tensor_get(dst,encoded_target.data(),0,encoded_target.size());
                    // GPU-produced encoded bytes are interpreted independently;
                    // the original half-scale bits must be retained verbatim.
                    const size_t blocks=size_t(ggml_nelements(src))/32;
                    for(size_t i=0;i<blocks;++i) {
                        const auto *old=encoded.data()+i*22,*result=encoded_target.data()+i*34;
                        if(std::memcmp(old,result,2)!=0)
                            throw std::runtime_error("Repack alterou a escala original");
                        uint32_t high=0;std::memcpy(&high,old+2,4);
                        for(unsigned lane=0;lane<32;++lane) {
                            const unsigned low=(old[6+lane%16]>>(lane<16?0:4))&15;
                            const int value=int(low|(((high>>lane)&1)<<4))-16;
                            if(result[2+lane]!=static_cast<unsigned char>(value))
                                throw std::runtime_error("Repack alterou o inteiro original");
                        }
                    }
                    ggml_get_type_traits(GGML_TYPE_Q8_0)->to_float(encoded_target.data(),actual.data(),ggml_nelements(dst));
                } else ggml_backend_tensor_get(dst,actual.data(),0,actual.size()*sizeof(float));
                if(std::memcmp(reference.data(),actual.data(),actual.size()*sizeof(float))!=0)
                    throw std::runtime_error(std::string("Expansão difere dos valores originais: ")+src->name);
                verified_bytes+=actual.size()*sizeof(float);
            }
            ggml_backend_buffer_set_usage(owner->buffer,GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
            extra_bytes+=ggml_backend_buffer_get_size(owner->buffer);
            allocations.push_back(std::move(owner));
        }
        // Original tensor identity/names/shapes remain intact, including aliases
        // held by architecture objects. Context/graphs have not been created yet.
        for(const auto &p:allocations) {
            p->original->type=p->expanded->type;
            std::memcpy(p->original->nb,p->expanded->nb,sizeof(p->original->nb));
            p->original->data=p->expanded->data;p->original->buffer=p->expanded->buffer;
        }
    }
};
