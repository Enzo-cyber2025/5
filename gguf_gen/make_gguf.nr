# =============================================================================
#  make_gguf.nr - Gerador de GGUF escrito NA LINGUAGEM NEURA
# =============================================================================
#  Cria um modelo GGUF v3 de ~300M de parametros com pesos aleatorios,
#  arquitetura estilo LLaMA, PROFUNDA e ESTREITA (85 camadas x 512).
#
#  Executar:  NeuraStudio.exe  ->  abrir este arquivo  ->  F5
#  ou pelo interpretador de linha de comando:  neura make_gguf.nr
#
#  O arquivo e escrito em dois passes, exatamente como manda o formato:
#    pass 1 - calcula o tamanho do cabecalho e os offsets de cada tensor
#    pass 2 - grava cabecalho e depois os pesos, um tensor por vez
# =============================================================================

# -----------------------------------------------------------------------------
# CONFIGURACAO
# -----------------------------------------------------------------------------
seja SAIDA     = "deep-narrow-300m.gguf"
seja N_LAYER   = 85        # PROFUNDO
seja N_EMBD    = 512       # ESTREITO
seja N_HEAD    = 8
seja N_KV_HEAD = 4
seja N_FF      = 1536
seja N_VOCAB   = 32000
seja N_CTX     = 4096
seja ROPE_BASE = 10000.0
seja NORM_EPS  = 0.00001
seja SEMENTE   = 1337

# tipo de dado dos pesos: 0 = f32, 1 = f16, 2 = bf16
seja DTYPE     = 1
seja ALINHAR   = 32

seja HEAD_DIM = N_EMBD / N_HEAD
seja KV_DIM   = HEAD_DIM * N_KV_HEAD

# codigos GGML  (0=F32, 1=F16, 30=BF16)
seja GGML_F32  = 0
seja GGML_TIPO = 0
se DTYPE == 1 { GGML_TIPO = 1 }
se DTYPE == 2 { GGML_TIPO = 30 }

seja BYTES_PESO = 4
se DTYPE > 0 { BYTES_PESO = 2 }

# codigos de tipo de valor de metadado
seja VT_U32 = 4
seja VT_I32 = 5
seja VT_F32 = 6
seja VT_BOOL = 7
seja VT_STR = 8
seja VT_ARR = 9

# -----------------------------------------------------------------------------
# CONTAGEM DE PARAMETROS
# -----------------------------------------------------------------------------
func params_por_camada() {
    seja atencao = N_EMBD * N_EMBD + N_EMBD * KV_DIM + N_EMBD * KV_DIM + N_EMBD * N_EMBD
    seja ffn = 3 * N_EMBD * N_FF
    seja normas = 2 * N_EMBD
    retorna atencao + ffn + normas
}

func params_total() {
    seja emb = N_VOCAB * N_EMBD * 2
    retorna emb + N_EMBD + N_LAYER * params_por_camada()
}

func alinhar(x) {
    seja resto = x % ALINHAR
    se resto == 0 { retorna x }
    retorna x + (ALINHAR - resto)
}

# -----------------------------------------------------------------------------
# CABECALHO: relatorio da arquitetura
# -----------------------------------------------------------------------------
imprime("========================================================")
imprime(" GERADOR DE GGUF EM NEURA - profundo e estreito")
imprime("========================================================")
imprime("  camadas          :", N_LAYER, "  <- profundo")
imprime("  hidden size      :", N_EMBD, "  <- estreito")
imprime("  razao prof/larg  :", N_LAYER / N_EMBD)
imprime("  cabecas (q / kv) :", N_HEAD, "/", N_KV_HEAD, " head_dim =", HEAD_DIM)
imprime("  feed-forward     :", N_FF)
imprime("  vocabulario      :", N_VOCAB)
imprime("  params/camada    :", params_por_camada())
imprime("  PARAMETROS TOTAIS:", params_total())
imprime("  precisao         :", BYTES_PESO, "bytes por peso")
imprime("  tamanho estimado :", arred(params_total() * BYTES_PESO / 1048576), "MiB")
imprime("========================================================")
imprime("")

# -----------------------------------------------------------------------------
# TABELA DE TENSORES
#
# Cada tensor tem: nome, papel, e as dimensoes ne[0], ne[1] na ordem GGUF
# (invertida em relacao ao PyTorch: um peso (saidas, entradas) vira [in, out]).
#
# papel: 0 = norma (tudo 1.0, sempre F32)
#        1 = embedding  (desvio 0.02)
#        2 = projecao de entrada
#        3 = projecao residual (desvio reduzido pela profundidade)
# -----------------------------------------------------------------------------
seja nomes  = lista()
seja papeis = lista()
seja ne0    = lista()
seja ne1    = lista()

func add_tensor(nome, papel, d0, d1) {
    adiciona(nomes, nome)
    adiciona(papeis, papel)
    adiciona(ne0, d0)
    adiciona(ne1, d1)
}

add_tensor("token_embd.weight", 1, N_EMBD, N_VOCAB)

seja i = 0
enquanto i < N_LAYER {
    seja p = "blk." + i + "."
    add_tensor(p + "attn_norm.weight",   0, N_EMBD, 1)
    add_tensor(p + "attn_q.weight",      2, N_EMBD, N_EMBD)
    add_tensor(p + "attn_k.weight",      2, N_EMBD, KV_DIM)
    add_tensor(p + "attn_v.weight",      2, N_EMBD, KV_DIM)
    add_tensor(p + "attn_output.weight", 3, N_EMBD, N_EMBD)
    add_tensor(p + "ffn_norm.weight",    0, N_EMBD, 1)
    add_tensor(p + "ffn_gate.weight",    2, N_EMBD, N_FF)
    add_tensor(p + "ffn_up.weight",      2, N_EMBD, N_FF)
    add_tensor(p + "ffn_down.weight",    3, N_FF,   N_EMBD)
    i += 1
}

add_tensor("output_norm.weight", 0, N_EMBD, 1)
add_tensor("output.weight",      1, N_EMBD, N_VOCAB)

seja N_TENSORES = tamanho(nomes)
imprime("[1/4] tabela montada:", N_TENSORES, "tensores")

# -----------------------------------------------------------------------------
# TAMANHO EM BYTES DE CADA TENSOR
# -----------------------------------------------------------------------------
func bytes_do_tensor(idx) {
    seja n = ne0[idx] * ne1[idx]
    se papeis[idx] == 0 {
        retorna n * 4            # normas sempre em F32
    }
    retorna n * BYTES_PESO
}

# offsets acumulados, com alinhamento
seja offsets = lista()
seja acc = 0
seja k = 0
enquanto k < N_TENSORES {
    adiciona(offsets, acc)
    acc = alinhar(acc + bytes_do_tensor(k))
    k += 1
}
imprime("[2/4] offsets calculados - bloco de dados:", acc, "bytes")

# -----------------------------------------------------------------------------
# METADADOS (chave, tipo, valor)
# -----------------------------------------------------------------------------
seja mk = lista()      # chaves
seja mt = lista()      # tipos
seja mv = lista()      # valores

func meta(chave, tipo, valor) {
    adiciona(mk, chave)
    adiciona(mt, tipo)
    adiciona(mv, valor)
}

seja FTYPE = 0
se DTYPE == 1 { FTYPE = 1 }
se DTYPE == 2 { FTYPE = 32 }

meta("general.architecture", VT_STR, "llama")
meta("general.quantization_version", VT_U32, 2)
meta("general.alignment", VT_U32, ALINHAR)
meta("general.name", VT_STR, "deep-narrow-300m-neura")
meta("general.file_type", VT_U32, FTYPE)
meta("llama.block_count", VT_U32, N_LAYER)
meta("llama.context_length", VT_U32, N_CTX)
meta("llama.embedding_length", VT_U32, N_EMBD)
meta("llama.feed_forward_length", VT_U32, N_FF)
meta("llama.attention.head_count", VT_U32, N_HEAD)
meta("llama.attention.head_count_kv", VT_U32, N_KV_HEAD)
meta("llama.attention.key_length", VT_U32, HEAD_DIM)
meta("llama.attention.value_length", VT_U32, HEAD_DIM)
meta("llama.attention.layer_norm_rms_epsilon", VT_F32, NORM_EPS)
meta("llama.rope.dimension_count", VT_U32, HEAD_DIM)
meta("llama.rope.freq_base", VT_F32, ROPE_BASE)
meta("llama.vocab_size", VT_U32, N_VOCAB)

# metadados escalares do tokenizer (os arrays sao escritos a parte)
seja N_META = tamanho(mk) + 9

# -----------------------------------------------------------------------------
# CALCULO DO TAMANHO DO CABECALHO (pass 1)
#
# Precisamos saber o tamanho exato do cabecalho antes de escrever, porque os
# offsets dos tensores sao relativos ao inicio do bloco de dados.
# -----------------------------------------------------------------------------
func bytes_str(s) {
    retorna 8 + tamanho(s)      # u64 de tamanho + conteudo
}

seja hdr = 4 + 4 + 8 + 8        # magic + versao + n_tensores + n_kv

# metadados escalares
seja j = 0
enquanto j < tamanho(mk) {
    hdr += bytes_str(mk[j]) + 4
    seja tp = mt[j]
    se tp == VT_STR {
        hdr += bytes_str(mv[j])
    } senao {
        hdr += 4
    }
    j += 1
}

# tokenizer: os tokens sao "<unk>", "<s>", "</s>", "<pad>", 256 bytes crus,
# e o resto preenchido com tokens sinteticos "tkN".
func bytes_token(idx) {
    se idx == 0 { retorna bytes_str("<unk>") }
    se idx == 1 { retorna bytes_str("<s>") }
    se idx == 2 { retorna bytes_str("</s>") }
    se idx == 3 { retorna bytes_str("<pad>") }
    se idx < 260 { retorna bytes_str("<0x00>") }
    retorna 8 + 5 + tamanho(texto(idx - 260))   # marcador U+2581 (3 bytes) + "tk" + numero
}

seja bytes_tokens = 0
seja q = 0
enquanto q < N_VOCAB {
    bytes_tokens += bytes_token(q)
    q += 1
}

# tokenizer.ggml.model / .pre  (strings)
hdr += bytes_str("tokenizer.ggml.model") + 4 + bytes_str("llama")
hdr += bytes_str("tokenizer.ggml.pre") + 4 + bytes_str("default")
# tokens (array de strings): chave + tipo + tipo_elem + n + conteudo
hdr += bytes_str("tokenizer.ggml.tokens") + 4 + 4 + 8 + bytes_tokens
# scores (array f32)
hdr += bytes_str("tokenizer.ggml.scores") + 4 + 4 + 8 + N_VOCAB * 4
# token_type (array i32)
hdr += bytes_str("tokenizer.ggml.token_type") + 4 + 4 + 8 + N_VOCAB * 4
# ids especiais (4 x u32)
hdr += bytes_str("tokenizer.ggml.unknown_token_id") + 4 + 4
hdr += bytes_str("tokenizer.ggml.bos_token_id") + 4 + 4
hdr += bytes_str("tokenizer.ggml.eos_token_id") + 4 + 4
hdr += bytes_str("tokenizer.ggml.padding_token_id") + 4 + 4

# tabela de tensores: nome + n_dim + dims + tipo + offset
seja z = 0
enquanto z < N_TENSORES {
    seja ndim = 2
    se papeis[z] == 0 { ndim = 1 }
    hdr += bytes_str(nomes[z]) + 4 + ndim * 8 + 4 + 8
    z += 1
}

seja INICIO_DADOS = alinhar(hdr)
imprime("[3/4] cabecalho:", hdr, "bytes -> dados comecam em", INICIO_DADOS)

# -----------------------------------------------------------------------------
# ESCRITA (pass 2)
# -----------------------------------------------------------------------------
seja f = abrir(SAIDA, "wb")

esc_bytes(f, "GGUF")
esc_u32(f, 3)                    # versao
esc_u64(f, N_TENSORES)
esc_u64(f, N_META)

# --- metadados escalares ---
seja j2 = 0
enquanto j2 < tamanho(mk) {
    esc_texto(f, mk[j2])
    esc_u32(f, mt[j2])
    seja tp2 = mt[j2]
    se tp2 == VT_STR {
        esc_texto(f, mv[j2])
    } senao se tp2 == VT_F32 {
        esc_f32(f, mv[j2])
    } senao {
        esc_u32(f, mv[j2])
    }
    j2 += 1
}

# --- tokenizer ---
esc_texto(f, "tokenizer.ggml.model")
esc_u32(f, VT_STR)
esc_texto(f, "llama")

esc_texto(f, "tokenizer.ggml.pre")
esc_u32(f, VT_STR)
esc_texto(f, "default")

# tokens
esc_texto(f, "tokenizer.ggml.tokens")
esc_u32(f, VT_ARR)
esc_u32(f, VT_STR)
esc_u64(f, N_VOCAB)

seja HEXA = "0123456789ABCDEF"
seja t2 = 0
enquanto t2 < N_VOCAB {
    se t2 == 0 {
        esc_texto(f, "<unk>")
    } senao se t2 == 1 {
        esc_texto(f, "<s>")
    } senao se t2 == 2 {
        esc_texto(f, "</s>")
    } senao se t2 == 3 {
        esc_texto(f, "<pad>")
    } senao se t2 < 260 {
        seja b = t2 - 4
        seja hi = piso(b / 16)
        seja lo = b % 16
        esc_texto(f, "<0x" + HEXA[hi] + HEXA[lo] + ">")
    } senao {
        # 0xE2 0x96 0x81 = U+2581, o marcador de espaco do SentencePiece
        seja s = texto(t2 - 260)
        esc_u64(f, 5 + tamanho(s))
        esc_u8(f, 226)
        esc_u8(f, 150)
        esc_u8(f, 129)
        esc_bytes(f, "tk")
        esc_bytes(f, s)
    }
    t2 += 1
}

# scores
esc_texto(f, "tokenizer.ggml.scores")
esc_u32(f, VT_ARR)
esc_u32(f, VT_F32)
esc_u64(f, N_VOCAB)
seja s2 = 0
enquanto s2 < N_VOCAB {
    esc_f32(f, 0 - s2)
    s2 += 1
}

# token_type: 2=UNKNOWN, 3=CONTROL, 6=BYTE, 1=NORMAL
esc_texto(f, "tokenizer.ggml.token_type")
esc_u32(f, VT_ARR)
esc_u32(f, VT_I32)
esc_u64(f, N_VOCAB)
seja y = 0
enquanto y < N_VOCAB {
    se y == 0 {
        esc_u32(f, 2)
    } senao se y < 4 {
        esc_u32(f, 3)
    } senao se y < 260 {
        esc_u32(f, 6)
    } senao {
        esc_u32(f, 1)
    }
    y += 1
}

esc_texto(f, "tokenizer.ggml.unknown_token_id")
esc_u32(f, VT_U32)
esc_u32(f, 0)
esc_texto(f, "tokenizer.ggml.bos_token_id")
esc_u32(f, VT_U32)
esc_u32(f, 1)
esc_texto(f, "tokenizer.ggml.eos_token_id")
esc_u32(f, VT_U32)
esc_u32(f, 2)
esc_texto(f, "tokenizer.ggml.padding_token_id")
esc_u32(f, VT_U32)
esc_u32(f, 3)

# --- tabela de tensores ---
seja w = 0
enquanto w < N_TENSORES {
    esc_texto(f, nomes[w])
    se papeis[w] == 0 {
        esc_u32(f, 1)
        esc_u64(f, ne0[w])
        esc_u32(f, GGML_F32)
    } senao {
        esc_u32(f, 2)
        esc_u64(f, ne0[w])
        esc_u64(f, ne1[w])
        esc_u32(f, GGML_TIPO)
    }
    esc_u64(f, offsets[w])
    w += 1
}

# confere se o calculo do pass 1 bateu com a realidade
seja pos = posicao(f)
se pos != hdr {
    imprime("ERRO: cabecalho previsto", hdr, "mas escrito", pos)
} senao {
    imprime("      cabecalho confere:", pos, "bytes")
}
esc_zeros(f, INICIO_DADOS - pos)

# -----------------------------------------------------------------------------
# PESOS
#
# Inicializacao escalada pela profundidade: as projecoes que escrevem no
# residual usam desvio dividido por raiz(2 * n_layer), senao 85 camadas
# empilhadas fazem a variancia do residual explodir.
# -----------------------------------------------------------------------------
imprime("[4/4] gerando e gravando os pesos...")
semente(SEMENTE)

seja escala_residual = raiz(2 * N_LAYER)
seja total_bytes = 0
seja c = 0

enquanto c < N_TENSORES {
    seja papel = papeis[c]
    seja d0 = ne0[c]
    seja d1 = ne1[c]

    # o tensor e criado no formato (linhas=ne1, colunas=ne0), que corresponde
    # a ordem em que os bytes devem sair: ne[0] varia mais rapido
    seja t = tensor(d1, d0)

    se papel == 0 {
        constante(t, 1.0)
        total_bytes += esc_tensor(f, t, 0)      # normas em F32
    } senao {
        seja sd = 0.02
        se papel == 2 {
            sd = raiz(2 / (5 * d0))
        }
        se papel == 3 {
            sd = raiz(2 / (5 * d0)) / escala_residual
        }
        preenche(t, sd)
        total_bytes += esc_tensor(f, t, DTYPE)
    }

    se c % 100 == 0 {
        imprime("      ", c, "/", N_TENSORES, " - ", arred(total_bytes / 1048576), "MiB")
    }
    c += 1
}

fechar(f)

imprime("")
imprime("========================================================")
imprime(" CONCLUIDO")
imprime("   arquivo    :", SAIDA)
imprime("   tensores   :", N_TENSORES)
imprime("   parametros :", params_total())
imprime("   bytes pesos:", total_bytes)
imprime("   tamanho    :", arred((INICIO_DADOS + total_bytes) / 1048576), "MiB")
imprime("========================================================")
