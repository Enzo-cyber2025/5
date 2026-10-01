package com.ggufchat.app;

import java.util.regex.Pattern;

/** Decide se uma pergunta PRECISA de dados recentes da web.
 *
 * Bug "o app pesquisa sem precisar": antes, qualquer envio com Busca ligada
 * disparava uma requisição HTTP antes de o modelo começar a responder. Isso
 * atrasa TODA resposta (o teto é de 12 s) mesmo para perguntas que o modelo
 * sabe de cor ("oi", "explique recursão", "3 fatos sobre cachorros"). Agora a
 * busca prévia só corre quando a pergunta tem indicadores claros de dado
 * externo/recente; caso contrário, o modelo responde direto e o botão "Parar"
 * já funciona antes da rede. Quando a ferramenta está ligada, o prompt de
 * sistema diz como pedir busca sob demanda.
 */
public final class SearchGating {
    private static final String TAG="GGUFGating";

    private SearchGating(){}

    /** Palavras/expressões que indicam dado atual, evento ou fato externo que o
     *  modelo não tem em pesos. Propositalmente curto; falsos positivos aqui
     *  são piores que falsos negativos (o usuário sempre pode tocar Busca).
     *
     * Gatilhos em PORTUGUÊS e INGLÊS: os testes do harness usam prompts em
     * inglês (news headlines, current price of Brent) e os prompts do usuário
     * podem chegar em qualquer dos dois idiomas. */
    private static final Pattern TRIGGERS=Pattern.compile(
        "(?i)(\\b(hoje|agora|neste momento|atualmente|atual|últim[ao]s?|recentement[e]?|ontem|amanhã|esta semana|esse ano|neste ano|nesse ano|em 202[4-9]|202[4-9])\\b"
        +"|\\b(today|now|right now|current(ly)?|latest|recent|yesterday|tomorrow|this week|this year|in 202[4-9])\\b"
        +"|\\b(notícias?|noticia|preço d[eo]|cotação|cota[cç]ão|resultado d[eo]|placar d[eo]|temperatura|clima|tempo agora|previsão do tempo)\\b"
        +"|\\b(news|headlines?|price of|stock price|share price|exchange rate|weather|forecast|score of|result of|current price)\\b"
        +"|\\b(quem (é|eh|foi) o atual|quem é o presidente|resultado do jogo|quanto (est[aá]|custa|vale) )"
        +"|\\b(who is the current|president (of|now)|stock of|bitcoin price|brent (oil )?price)"
        +"|\\b(link d[eo]|site d[eo]|página d[eo]|pagina d[eo]|fonte d[eo]|referência|referencia d[eo])"
        +"|\\b(wikipedia|wikipédia|site oficial|fonte oficial|leia mais|artigo)\\b"
        +"|\\bcite (the )?sources|fonte[s]?\\b)"
    );

    /** Quando o envio é manual (botão Busca = ON), a busca prévia só corre se
     *  a pergunta realmente pedir dado externo. Sem isso, responde do peso. */
    public static boolean needsWeb(String text){
        if(text==null)return false;
        String t=text.trim();
        if(t.length()<4)return false;
        // Perguntas de conversa curta, código e explicação geral não devem
        // esperar por HTTP. O limite é propositalmente conservador.
        if(t.length()<12 && !t.contains("?"))return false;
        return TRIGGERS.matcher(t).find();
    }
}
