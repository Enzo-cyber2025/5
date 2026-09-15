package com.ggufchat.app;

import android.content.Context;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;
import java.util.Locale;

/** Native token counters, not characters, words, or UI callback counts.
 * Decode wall time starts AFTER prompt/image prefill; includes sampling and delivery.
 * Thread-local ownership prevents a failed/new request inheriting previous metrics. */
public final class GenerationStats {
    private static final ThreadLocal<String> RESULT=new ThreadLocal<>();
    private static final ThreadLocal<Long> NOTICE=new ThreadLocal<>();
    public static void begin(){RESULT.remove();NOTICE.remove();}
    public static void measured(long tokens,long decodeNs,long prefillNs,boolean completed){
        try {
            JSONObject j=new JSONObject();j.put("tokens",tokens);j.put("decodeNs",decodeNs);
            j.put("prefillNs",prefillNs);j.put("completed",completed);j.put("version",1);
            RESULT.set(j.toString());
        } catch(Exception e){RESULT.remove();}
    }
    public static boolean notifyNow(){
        long now=System.nanoTime();Long before=NOTICE.get();
        if(before!=null&&now-before<1000000000L)return false;
        NOTICE.set(now);return true;
    }
    public static String preview(StringBuilder text){return text.substring(0,Math.min(80,text.length()));}
    public static void attach(Object message){
        String value=RESULT.get();RESULT.remove();NOTICE.remove();
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
    public static String label(String value){
        if(value==null)return "— tokens/s · sem medição";
        try {
            JSONObject j=new JSONObject(value);long tokens=j.getLong("tokens"),ns=j.getLong("decodeNs");
            if(tokens<=0||ns<=0)return "— tokens/s · sem amostra";
            double rate=tokens*1e9/(double)ns;
            if(Double.isNaN(rate)||Double.isInfinite(rate))return "— tokens/s · sem medição";
            return String.format(Locale.getDefault(),"%.1f tokens/s · %d tokens%s",rate,tokens,j.optBoolean("completed",false)?"":" · interrompida");
        }catch(Exception e){return "— tokens/s · sem medição";}
    }
    public static void caption(Context c,LinearLayout column,Object message){
        if(message==null)return;
        try {
            if(!"assistant".equals(message.getClass().getField("role").get(message)))return;
            String value=(String)message.getClass().getField("generationMetrics").get(message);
            TextView view=new TextView(c);view.setText(label(value));view.setTextSize(11);
            view.setTextColor(0xff9cafa6);view.setContentDescription("Velocidade da resposta");
            int pad=Math.round(4*c.getResources().getDisplayMetrics().density);
            view.setPadding(pad,pad,pad,pad);column.addView(view);
        }catch(Exception e){throw new IllegalStateException("Não foi possível exibir a medição",e);}
    }
}
