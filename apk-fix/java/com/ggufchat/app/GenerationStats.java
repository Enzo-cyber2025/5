package com.ggufchat.app;

import org.json.JSONObject;
import java.util.Locale;

/** Native token counters, not characters, words, or UI callback counts.
 * Decode wall time starts AFTER prompt/image prefill; includes sampling and delivery.
 * Thread-local ownership prevents a failed/new request inheriting previous metrics. */
public final class GenerationStats {
    private static final ThreadLocal<String> RESULT=new ThreadLocal<>();
    private static final ThreadLocal<Long> NOTICE=new ThreadLocal<>();
    private static final ThreadLocal<long[]> LATENCY=new ThreadLocal<>();
    public static void begin(){RESULT.remove();NOTICE.remove();LATENCY.remove();}
    public static void latency(long firstTokenNs,long promptTokens,long reusedTokens){
        LATENCY.set(new long[]{firstTokenNs,promptTokens,reusedTokens});
    }
    public static void measured(long tokens,long decodeNs,long prefillNs,boolean completed){
        try {
            JSONObject j=new JSONObject();j.put("tokens",tokens);j.put("decodeNs",decodeNs);
            j.put("prefillNs",prefillNs);j.put("completed",completed);j.put("version",3);j.put("timingScope","prefill_synchronized_before_decode");
            long[] latency=LATENCY.get();
            if(latency!=null){j.put("firstTokenNs",latency[0]);j.put("promptTokens",latency[1]);j.put("reusedPromptTokens",latency[2]);}
            LATENCY.remove();
            RESULT.set(j.toString());
            // Contadores nativos auditáveis no logcat: tokens e tempo real de
            // decodificação, sem estimativa. É isso que o teste no emulador lê.
            // A chamada é por reflexão para que este arquivo continue sem Android.
            long first=latency==null?-1:latency[0],prompt=latency==null?0:latency[1],reused=latency==null?0:latency[2];
            try{
                Class.forName("com.ggufchat.app.StatsLog")
                    .getMethod("emit",long.class,long.class,long.class,double.class,
                               long.class,long.class,long.class,boolean.class)
                    .invoke(null,tokens,decodeNs,prefillNs,rate(tokens,decodeNs),first,prompt,reused,completed);
            }catch(Throwable ignored){}
        } catch(Exception e){RESULT.remove();}
    }
    public static boolean notifyNow(){
        long now=System.nanoTime();Long before=NOTICE.get();
        if(before!=null&&now-before<1000000000L)return false;
        NOTICE.set(now);return true;
    }
    public static String preview(StringBuilder text){return text.substring(0,Math.min(PreviewCadence.PREFIX_LENGTH,text.length()));}
    public static void attach(Object message){
        String value=RESULT.get();RESULT.remove();NOTICE.remove();LATENCY.remove();
        try{message.getClass().getField("generationMetrics").set(message,value);}
        catch(Exception e){throw new IllegalStateException("Campo de medição ausente",e);}
    }
    public static void read(Object message,JSONObject json) throws Exception {
        JSONObject value=json.optJSONObject("generationMetrics");
        message.getClass().getField("generationMetrics").set(message,value==null?null:value.toString());
    }
    public static void write(Object message,JSONObject json) throws Exception {
        String value=(String)message.getClass().getField("generationMetrics").get(message);
        if(value!=null)json.put("generationMetrics",new JSONObject(value));
    }
    public static double rate(long tokens,long ns){return tokens>0&&ns>0?tokens*1e9/(double)ns:Double.NaN;}
    public static String label(String value){
        if(value==null)return "— tokens/s · sem medição";
        try {
            JSONObject j=new JSONObject(value);long tokens=j.getLong("tokens"),ns=j.getLong("decodeNs");
            if(tokens<=0||ns<=0)return "— tokens/s · sem amostra";
            double rate=rate(tokens,ns);
            if(Double.isNaN(rate)||Double.isInfinite(rate))return "— tokens/s · sem medição";
            return String.format(Locale.getDefault(),"%.1f tokens/s · %d tokens%s",rate,tokens,j.optBoolean("completed",false)?"":" · interrompida");
        }catch(Exception e){return "— tokens/s · sem medição";}
    }
}
