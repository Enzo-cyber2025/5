#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <signal.h>
#include <execinfo.h>

/* header do llama.cpp 0.22.0 (mesmo ABI do libllama.so do APK) */
#include "llama.h"

static void handler(int sig, siginfo_t *si, void *uc){
    fprintf(stderr, "\n>>> CRASH: sinal %d (%s) em RIP=0x%lx\n", sig, strsignal(sig), (unsigned long)si->si_addr);
    void *bt[16]; int n = backtrace(bt, 16);
    char **syms = backtrace_symbols(bt, n);
    Dl_info info;
    for(int i=0;i<n;i++){
        if (dladdr(bt[i], &info) && info.dli_fname){
            long off = (char*)bt[i] - (char*)info.dli_fbase;
            fprintf(stderr, "    #%d %s +0x%lx [%s +0x%lx]\n", i,
                info.dli_sname?info.dli_sname:"?", (char*)bt[i]-(char*)info.dli_saddr, info.dli_fname, off);
        } else fprintf(stderr, "    #%d %s\n", i, syms? syms[i]:"?");
    }
    fflush(stderr); _exit(128+sig);
}

static void *sym(void *h, const char *name){
    void *p = dlsym(h, name);
    if(!p) fprintf(stderr, "dlsym FALHOU: %s\n", name);
    return p;
}

int main(int argc, char **argv){
    struct sigaction sa; memset(&sa,0,sizeof sa);
    sa.sa_sigaction=handler; sa.sa_flags=SA_SIGINFO;
    sigaction(SIGTRAP,&sa,0); sigaction(SIGILL,&sa,0); sigaction(SIGABRT,&sa,0);
    sigaction(SIGSEGV,&sa,0); sigaction(SIGBUS,&sa,0); sigaction(SIGFPE,&sa,0);

    setvbuf(stdout,NULL,_IONBF,0); setvbuf(stderr,NULL,_IONBF,0);

    void *h = dlopen("libllama.so", RTLD_NOW|RTLD_GLOBAL);
    if(!h){ fprintf(stderr,"dlopen libllama.so FALHOU: %s\n", dlerror()); return 2; }
    printf(">>> libllama.so REAL do APK carregado\n");

    void (*llama_backend_init)(void) = sym(h,"llama_backend_init");
    struct llama_model_params (*llama_model_default_params)(void) = sym(h,"llama_model_default_params");
    struct llama_model *(*llama_model_load_from_file)(const char*, struct llama_model_params) = sym(h,"llama_model_load_from_file");
    int32_t (*llama_model_desc)(const struct llama_model*,char*,size_t) = sym(h,"llama_model_desc");
    const struct llama_vocab *(*llama_model_get_vocab)(const struct llama_model*) = sym(h,"llama_model_get_vocab");
    uint32_t (*llama_model_n_ctx_train)(const struct llama_model*) = sym(h,"llama_model_n_ctx_train");
    struct llama_context_params (*llama_context_default_params)(void) = sym(h,"llama_context_default_params");
    struct llama_context *(*llama_init_from_model)(struct llama_model*, struct llama_context_params) = sym(h,"llama_init_from_model");
    int32_t (*llama_tokenize)(const struct llama_vocab*,const char*,int32_t,llama_token*,int32_t,bool,bool) = sym(h,"llama_tokenize");
    int32_t (*llama_decode)(struct llama_context*, struct llama_batch) = sym(h,"llama_decode");
    int32_t (*llama_token_to_piece)(const struct llama_vocab*,llama_token,char*,int32_t,int32_t,bool) = sym(h,"llama_token_to_piece");
    float *(*llama_get_logits_ith)(struct llama_context*,int32_t) = sym(h,"llama_get_logits_ith");
    llama_token (*llama_vocab_eos)(const struct llama_vocab*) = sym(h,"llama_vocab_eos");
    uint32_t (*llama_vocab_n_tokens)(const struct llama_vocab*) = sym(h,"llama_vocab_n_tokens");
    void (*llama_model_free)(struct llama_model*) = sym(h,"llama_model_free");
    void (*llama_free)(struct llama_context*) = sym(h,"llama_free");
    void (*llama_backend_free)(void) = sym(h,"llama_backend_free");
    void (*llama_set_n_threads)(struct llama_context*,int32_t,int32_t) = sym(h,"llama_set_n_threads");

    if(!llama_backend_init||!llama_model_load_from_file||!llama_init_from_model||!llama_decode||!llama_tokenize||!llama_get_logits_ith||!llama_vocab_eos||!llama_vocab_n_tokens||!llama_model_default_params||!llama_context_default_params){
        fprintf(stderr,"faltando símbolo\n"); return 3;
    }

    printf(">>> llama_backend_init() ...\n");
    llama_backend_init();
    printf(">>> backend init OK\n");

    const char *path = argc>1 ? argv[1] : "/tmp/tiny-llama-022.gguf";
    printf(">>> llama_model_load_from_file(%s)\n", path);
    struct llama_model_params mp = llama_model_default_params();
    mp.load_mode = LLAMA_LOAD_MODE_NONE;   /* evita o caminho mmap (host/glibc difere do bionic) */
    mp.n_gpu_layers = 0;                   /* só CPU neste host */
    struct llama_model *model = llama_model_load_from_file(path, mp);
    if(!model){ fprintf(stderr,">>> model_load FALHOU\n"); return 4; }

    char desc[512]; llama_model_desc(model, desc, sizeof desc);
    printf(">>> modelo carregado: %s\n", desc);
    printf(">>> n_ctx_train=%u\n", (unsigned)llama_model_n_ctx_train(model));

    struct llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = 64;
    printf(">>> llama_init_from_model (contexto, n_ctx=64) ...\n");
    struct llama_context *ctx = llama_init_from_model(model, cparams);
    if(!ctx){ fprintf(stderr,">>> context FALHOU\n"); return 5; }
    llama_set_n_threads(ctx, 2, 2);
    printf(">>> contexto criado OK\n");

    const struct llama_vocab *vocab = llama_model_get_vocab(model);
    printf(">>> n_vocab=%u eos=%d\n", (unsigned)llama_vocab_n_tokens(vocab), (int)llama_vocab_eos(vocab));

    printf(">>> montando prompt com tokens fixos (BOS=1 + bytes 6,6,6) ...\n");
    llama_token toks[64];
    toks[0]=1; toks[1]=6; toks[2]=6; toks[3]=6;
    int32_t n = 4;
    for(int i=0;i<n;i++){ char piece[64]; int32_t pl=llama_token_to_piece(vocab,toks[i],piece,sizeof piece-1,0,true); piece[pl>0?pl:0]=0; printf("   tok[%d]=%d '%s'\n", i, toks[i], piece); }

    printf(">>> llama_decode(prompt, %d tokens) ...\n", n);
    llama_pos pos[64]; llama_seq_id seq[64]; llama_seq_id *seqp[64]; int32_t n_seq_id[64];
    for(int i=0;i<n;i++){ pos[i]=i; seq[i]=0; seqp[i]=&seq[i]; n_seq_id[i]=1; }
    struct llama_batch b = { n, toks, NULL, pos, n_seq_id, seqp, NULL };
    int32_t r = llama_decode(ctx, b);
    printf(">>> decode prompt ret=%d %s\n", r, r==0?"OK":"ERRO");

    printf(">>> geração greedy (4 tokens) ...\n");
    llama_token nxt = toks[n-1]; llama_token eos = llama_vocab_eos(vocab);
    uint32_t nvocab = llama_vocab_n_tokens(vocab);
    for(int step=0; step<4; step++){
        llama_pos p = n+step; llama_seq_id s=0; llama_seq_id *sp=&s; int32_t ns=1;
        struct llama_batch gb = {1, &nxt, NULL, &p, &ns, &sp, NULL};
        int32_t gr = llama_decode(ctx, gb);
        if(gr!=0){ printf("   decode gen ret=%d\n", gr); break; }
        float *lg = llama_get_logits_ith(ctx, 0);
        llama_token best=0; float bestv=lg[0];
        for(uint32_t i=1;i<nvocab;i++) if(lg[i]>bestv){ bestv=lg[i]; best=i; }
        char piece[64]; int32_t pl = llama_token_to_piece(vocab, best, piece, sizeof piece-1, 0, true);
        piece[pl>0?pl:0]=0;
        printf("   token %d = '%s' (logit %.3f)\n", best, piece, bestv);
        if(best==eos){ printf("   <eos>\n"); break; }
        nxt = best;
    }

    printf(">>> cleanup ...\n");
    llama_free(ctx); llama_model_free(model); llama_backend_free();
    printf(">>> OK: execução REAL do motor do APK concluída sem crash\n");
    return 0;
}
