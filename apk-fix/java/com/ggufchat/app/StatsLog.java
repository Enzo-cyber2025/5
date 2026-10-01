package com.ggufchat.app;

import android.util.Log;
import java.util.Locale;

/** Linha de medição no logcat, fora de GenerationStats de propósito: a aritmética
 * de taxa precisa continuar compilável e testável sem o Android (o teste de host
 * compila esse arquivo sozinho). A taxa é calculada a partir dos inteiros nativos
 * de tokens e nanossegundos; o texto formatado não é a fonte de nenhum número. */
public final class StatsLog {
    private static final String TAG="GGUFStats";

    private StatsLog(){}

    public static void emit(long tokens,long decodeNs,long prefillNs,double rate,
                            long firstTokenNs,long promptTokens,long reusedTokens,boolean completed){
        Log.i(TAG,String.format(Locale.US,
            "GGUF_GENERATION_STATS tokens=%d decode_ns=%d prefill_ns=%d tokens_s=%.3f "
            +"first_token_ns=%d prompt_tokens=%d reused_tokens=%d completed=%d version=3",
            tokens,decodeNs,prefillNs,rate,firstTokenNs,promptTokens,reusedTokens,completed?1:0));
    }
}
