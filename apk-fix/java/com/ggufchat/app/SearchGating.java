package com.ggufchat.app;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Decide quando uma pergunta precisa de web.
 *
 * Agora também EXTRAI PALAVRAS-CHAVE da pergunta para exibir no painel e
 * liberar o modelo para disparar busca sob demanda quando ele encontrar um
 * fato que não tem em pesos.
 */
public final class SearchGating {
    private static final String TAG="GGUFGating";
    private SearchGating(){}

    private static final Pattern TRIGGERS=Pattern.compile(
        "(?i)(\\b(hoje|agora|neste momento|atualmente|atual|últim[ao]s?|recentement[e]?|ontem|amanhã|esta semana|esse ano|neste ano|nesse ano|em 202[4-9]|202[4-9])\\b"
        +"|\\b(today|now|right now|current(ly)?|latest|recent|yesterday|tomorrow|this week|this year|in 202[4-9])\\b"
        +"|\\b(notícias?|noticia|preço d[eo]|cotação|cota[cç]ão|resultado d[eo]|placar d[eo]|temperatura|clima|tempo agora|previsão do tempo)\\b"
        +"|\\b(news|headlines?|price of|stock price|share price|exchange rate|weather|forecast|score of|result of|current price)\\b"
        +"|\\b(quem (é|eh|foi) o atual|quem é o presidente|resultado do jogo|quanto (est[aá]|custa|vale) )"
        +"|\\b(who is the current|president (of|now)|stock of|bitcoin price|brent (oil )?price)"
        +"|\\b(link d[eo]|site d[eo]|página d[eo]|pagina d[eo]|fonte d[eo]|referência|referencia d[eo])"
        +"|\\b(wikipedia|wikipédia|site oficial|fonte oficial|leia mais|artigo)\\b"
        +"|\\b(pesquise|pesquisa|search|google|busca|search for|look up|procure)\\b"
        +"|\\bcite (the )?sources|fonte[s]?\\b"
        // Perguntas factuais começando com "qual", "quem", "quant", "onde", "how many", "who", "what is the"
        +"|^(qual|quais|quem|quant[oa]s?|onde|como está|qual é|qual eh|que dia|que horas?)\\b"
        +"|^(who|what|where|when|how (many|much|old|tall|far))\\b)"
    );

    /** Gatilhos de NÃO-busca: saudações, código simples, explicação de conceitos. */
    private static final Pattern SKIP=Pattern.compile(
        "(?i)^(oi|olá|ola|e aí|eai|bom dia|boa tarde|boa noite|hey|hi|hello|obrigad[oa]|valeu|tchau)"
        +"|^(explique|defina|resuma|explain|define|summarize)\\b"
        +"|\\b(código|codigo|função|funcao|classe|método|metodo|bug|compile|java|python|kotlin|c\\+\\+)\\b"
    );

    public static boolean needsWeb(String text){
        if(text==null)return false;
        String t=text.trim();
        if(t.length()<4)return false;
        if(t.length()<12 && !t.contains("?") && !t.contains("?"))return false;
        if(SKIP.matcher(t).find())return false;
        return TRIGGERS.matcher(t).find();
    }

    /** Extrai palavras-chave da pergunta: remove stopwords, pega os 5 tokens mais
     *  relevantes (sem números/símbolos). É o que aparece no painel. */
    public static List<String> keywords(String text){
        ArrayList<String> out=new ArrayList<String>();
        if(text==null)return out;
        HashSet<String> stops=new HashSet<String>(Arrays.asList(
            "a","o","os","as","um","uma","uns","umas","de","do","da","dos","das","em","no","na","nos","nas",
            "que","qual","quais","como","onde","quando","quem","por","para","porque","porquê","pq",
            "e","ou","mas","se","é","eh","foi","era","ser","está","esta","estao","estão","são","sao",
            "the","a","an","is","are","was","were","of","in","on","at","to","for","with","and","or","but",
            "me","te","se","lhe","eu","tu","ele","ela","nós","nos","você","voce","vocês","voces",
            "minha","meu","sua","seu","essa","esse","isso","isto","aquilo","aquele","aquela",
            "tem","vai","vou","ir","fazer","fez","faz","sabe","diz","diga","me","mim"
        ));
        Matcher m=Pattern.compile("[\\p{L}][\\p{L}\\p{N}'-]{2,}").matcher(text.toLowerCase(Locale.ROOT));
        HashSet<String> seen=new HashSet<String>();
        while(m.find() && out.size()<6){
            String w=m.group();
            if(!stops.contains(w) && !seen.contains(w) && w.length()>2 && !w.matches("\\d+")){
                out.add(w); seen.add(w);
            }
        }
        return out;
    }
}
