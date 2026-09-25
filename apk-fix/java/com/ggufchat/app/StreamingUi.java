package com.ggufchat.app;

import android.app.Activity;
import android.util.Log;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.Map;

/** Token routing during generation: reasoning goes to the panel above, the answer
 * keeps flowing to the incremental renderer (fences, language, bold). No timer,
 * no batching and no change to tokens/s: the same chunks are shown as they arrive. */
public final class StreamingUi {
    private static final Map<TextView,Integer> ANSWER=new IdentityHashMap<TextView,Integer>();
    private static final Map<TextView,StringBuilder> RAW=new IdentityHashMap<TextView,StringBuilder>();

    private StreamingUi(){}

    public static void token(Activity activity,TextView answer,String chunk){
        if(answer==null||chunk==null||chunk.length()==0)return;
        StringBuilder buffer=RAW.get(answer);
        if(buffer==null){buffer=new StringBuilder();RAW.put(answer,buffer);}
        buffer.append(chunk);
        String raw=buffer.toString();
        String[] parts=ThinkingView.split(raw);
        if(parts[0].length()>0)ThinkingView.reasoning(CodeBlocks.column(answer),parts[0]);
        int done=ANSWER.containsKey(answer)?ANSWER.get(answer):0;
        String full=parts[1];
        if(full.length()<done){ANSWER.remove(answer);done=0;}
        if(full.length()>done){
            if(done==0)BackendNotice.show(activity);
            CodeBlocks.append(answer,full.substring(done));
            ANSWER.put(answer,full.length());
            answer.setContentDescription("Resposta");
        }
    }

    public static void finish(Activity activity){
        try{
            Object view=field(activity,"streamingView");
            if(view instanceof TextView){ANSWER.remove(view);RAW.remove(view);}
        }catch(Exception ex){}
    }

    /** Mostra na linha de status que a busca foi pedida antes da geração começar. */
    public static void announce(Activity activity){
        BackendNotice.show(activity);
        try{
            Object chat=field(activity,"chat");
            boolean search=chat!=null&&Boolean.TRUE.equals(field(chat,"webSearch"));
            Object status=field(activity,"statusLine");
            if(search&&status instanceof TextView){
                // O teto aparece junto: "Pesquisando" sem limite era o que fazia a
                // espera parecer travada.
                int budget=SearchBudget.configuredMs();
                ((TextView)status).setText("Pesquisando na web (até "+(budget/1000)+" s) antes de responder…");
                ((TextView)status).setContentDescription("Pesquisando na web");
                Log.i("GGUFSearch","GGUF_SEARCH_ANNOUNCED query_pending=1 budget_ms="+budget);
            }
        }catch(Exception ex){
            Log.i("GGUFSearch","GGUF_SEARCH_ANNOUNCE_SKIPPED "+ex.getClass().getSimpleName());
        }
    }

    private static Object field(Object target,String name) throws Exception {
        Field field=target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
    }
}
