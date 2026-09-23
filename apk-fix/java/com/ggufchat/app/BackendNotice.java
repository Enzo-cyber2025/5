package com.ggufchat.app;

import android.app.Activity;
import android.util.Log;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.Map;

/** Aviso visível do backend que realmente executa a geração.
 * Nada de fallback silencioso: quando o Vulkan disponível é um driver por
 * software (mais lento que a CPU), o app usa a CPU e mostra isso na conversa. */
public final class BackendNotice {
    private static final String TAG="GGUFBackendNotice";
    private static final Map<Activity,Boolean> SHOWN=new IdentityHashMap<Activity,Boolean>();

    private BackendNotice(){}

    /** Implementado no nativo (libaijni). Vazio enquanto nenhum modelo foi carregado. */
    public static native String read();

    public static void show(Activity activity){
        if(activity==null||SHOWN.containsKey(activity))return;
        String notice;
        try{
            notice=read();
        }catch(Throwable ignored){
            return; // biblioteca ainda não carregada: tenta de novo no primeiro token
        }
        if(notice==null||notice.length()==0)return;
        SHOWN.put(activity,Boolean.TRUE);
        Log.i(TAG,"GGUF_BACKEND_NOTICE_UI "+notice);
        try{
            Field field=activity.getClass().getDeclaredField("statusLine");
            field.setAccessible(true);
            Object status=field.get(activity);
            if(status instanceof TextView){
                TextView view=(TextView)status;
                view.setText("Backend: "+notice);
                view.setContentDescription("Backend em uso");
            }
        }catch(Exception ex){
            Log.i(TAG,"GGUF_BACKEND_NOTICE_UI_SKIPPED "+ex.getClass().getSimpleName());
        }
    }
}
