package com.ggufchat.app;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.util.Log;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/** Aquecimento do prefixo do próximo envio, no tempo ocioso da conversa.
 *
 * O primeiro envio paga o prefill do bloco system antes de escrever a primeira
 * palavra. Esse prefixo já é conhecido antes do envio: esta classe o monta com o
 * MESMO caminho do aplicativo (`PromptBuilder.buildMessages` +
 * `SystemPrompts.apply` + `PromptBuilder.renderPrompt`) e o nativo o pré-preenche
 * no KV. Quando o usuário envia, só os tokens ainda não processados são
 * decodificados.
 *
 * Dois momentos, ambos antes do envio:
 *  1. a conversa abre: aquece o bloco system (serve até para quem cola e envia);
 *  2. o usuário digita: a cada pausa, aquece o prompt inteiro com o texto que
 *     está no campo — o KV cresce junto com a digitação.
 *
 * Garantias:
 *  - o resultado não muda: o aquecimento não produz logits nem consome token de
 *    saída; o KV só recebe tokens idênticos aos que o envio real vai produzir, e
 *    o nativo sempre deixa o último token para a decodificação real;
 *  - um envio real tem prioridade: o nativo cede a vez entre blocos;
 *  - falha de aquecimento é registrada e ignorada — o envio segue o caminho normal;
 *  - nenhum rótulo, texto de interface ou conteúdo do usuário é alterado.
 */
public final class ResponseWarmup {
    private static final String TAG="GGUFWarmup";
    private static final Map<Activity,Boolean> STARTED=new IdentityHashMap<Activity,Boolean>();
    private static final Object TURN=new Object(); // um aquecimento por vez
    private static final long POLL_MS=250;
    private static final int MODEL_POLLS=120;   // até 30 s esperando o modelo
    private static final int INPUT_POLLS=40;    // até 10 s esperando o campo de texto
    private static final long DEBOUNCE_MS=700;
    private static final int MAX_PREFIX_CHARS=120000;

    private ResponseWarmup(){}

    /** Implementado no nativo (libaijni): pré-preenche o prefixo e o mantém no KV. */
    public static native boolean nativeWarmup(long handle,String prompt);

    /** Chamado assim que a conversa é montada, antes de qualquer envio. */
    public static void install(Activity activity){
        if(activity==null)return;
        synchronized(STARTED){
            if(STARTED.containsKey(activity))return;
            STARTED.put(activity,Boolean.TRUE);
        }
        start("gguf-warmup-base",new Runnable(){public void run(){warmBase(activity);}});
        attachWatcher(activity,0);
    }

    private static void warmBase(Activity activity){
        try{
            Object[] ready=await(activity,MODEL_POLLS);
            if(ready==null){Log.i(TAG,"GGUF_WARMUP_SKIPPED reason=sem_modelo");return;}
            long handle=(Long)ready[0];
            String prefix=prefix(activity,ready[1],handle,null);
            if(prefix==null||prefix.isEmpty()){Log.i(TAG,"GGUF_WARMUP_SKIPPED reason=sem_prefixo");return;}
            boolean ok=run(handle,prefix);
            Log.i(TAG,"GGUF_WARMUP_UI ok="+(ok?1:0)+" chars="+prefix.length());
        }catch(Throwable error){
            Log.i(TAG,"GGUF_WARMUP_SKIPPED reason="+error.getClass().getSimpleName());
        }
    }

    private static void warmTyped(Activity activity,String text){
        try{
            if(text==null||text.trim().isEmpty())return;
            long handle=engineHandle();
            Object chat=field(activity,"chat");
            if(handle==0||chat==null)return;
            if(Boolean.TRUE.equals(field(activity,"loading")))return;
            String prefix=prefix(activity,chat,handle,text);
            if(prefix==null||prefix.isEmpty())return;
            boolean ok=run(handle,prefix);
            Log.i(TAG,"GGUF_WARMUP_TEXT ok="+(ok?1:0)+" chars="+text.length());
        }catch(Throwable error){
            Log.i(TAG,"GGUF_WARMUP_SKIPPED reason="+error.getClass().getSimpleName());
        }
    }

    private static boolean run(long handle,String prefix){
        synchronized(TURN){return nativeWarmup(handle,prefix);}
    }

    /** Espera o modelo ficar pronto e devolve {handle, chat}; nulo se não chegar. */
    private static Object[] await(Activity activity,int polls){
        for(int attempt=0;attempt<polls;attempt++){
            long handle=engineHandle();
            Object chat=field(activity,"chat");
            if(handle!=0 && chat!=null && !Boolean.TRUE.equals(field(activity,"loading")))
                return new Object[]{Long.valueOf(handle),chat};
            if(!sleep())return null;
        }
        return null;
    }

    private static boolean sleep(){
        try{Thread.sleep(POLL_MS);return true;}
        catch(InterruptedException interrupted){Thread.currentThread().interrupt();return false;}
    }

    /** Prefixo do próximo envio, montado com as funções do próprio aplicativo.
     *
     * `typed` nulo devolve só o bloco system (mais o histórico); com texto, a
     * linha do usuário entra no fim, exatamente como o envio real monta.
     */
    private static String prefix(Activity activity,Object chat,long handle,String typed) throws Exception {
        Class<?> builder=Class.forName("com.ggufchat.app.PromptBuilder");
        Class<?> chatClass=Class.forName("com.ggufchat.app.Chat");
        Method build=builder.getMethod("buildMessages",chatClass,String.class,boolean.class,String.class);
        Object search=field(chat,"webSearch");
        boolean webSearch=search instanceof Boolean&&((Boolean)search).booleanValue();
        @SuppressWarnings("unchecked")
        List<String[]> rows=(List<String[]>)build.invoke(null,chat,"",Boolean.valueOf(webSearch),null);
        if(rows==null){return null;}
        List<String[]> planned=new ArrayList<String[]>(rows);
        if(typed!=null&&!typed.isEmpty())planned.add(new String[]{"user",typed});
        // Mesma transformação do envio: o prompt de sistema resolvido substitui o
        // padrão exatamente uma vez (e lança se o formato for inesperado).
        SystemPrompts.apply(activity,chat,planned);
        Method render=builder.getMethod("renderPrompt",long.class,List.class);
        Object prompt=render.invoke(null,handle,planned);
        if(!(prompt instanceof String))return null;
        String text=(String)prompt;
        if(text.length()>MAX_PREFIX_CHARS)return null; // teto de trabalho por pausa
        return text;
    }

    /** Observa o campo de texto para aquecer o prompt conforme o usuário digita. */
    private static void attachWatcher(final Activity activity,final int attempt){
        try{
            final Object value=field(activity,"input");
            if(value instanceof android.widget.EditText){
                watch((android.widget.EditText)value,activity);
                return;
            }
            if(attempt>=INPUT_POLLS){Log.i(TAG,"GGUF_WARMUP_SKIPPED reason=sem_campo");return;}
            new Handler(Looper.getMainLooper()).postDelayed(new Runnable(){
                public void run(){attachWatcher(activity,attempt+1);}
            },POLL_MS);
        }catch(Throwable error){
            Log.i(TAG,"GGUF_WARMUP_SKIPPED reason=watcher");
        }
    }

    private static void watch(android.widget.EditText input,final Activity activity){
        final Handler handler=new Handler(Looper.getMainLooper());
        final Runnable[] pending={null};
        final String[] latest={null};
        input.addTextChangedListener(new TextWatcher(){
            public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){}
            public void afterTextChanged(Editable editable){
                latest[0]=editable==null?null:editable.toString();
                if(pending[0]!=null)handler.removeCallbacks(pending[0]);
                pending[0]=new Runnable(){public void run(){
                    final String text=latest[0];
                    start("gguf-warmup-text",new Runnable(){public void run(){warmTyped(activity,text);}});
                }};
                handler.postDelayed(pending[0],DEBOUNCE_MS);
            }
        });
        Log.i(TAG,"GGUF_WARMUP_WATCHER attached=1");
    }

    private static void start(String name,Runnable body){
        try{
            Thread worker=new Thread(body,name);
            worker.setDaemon(true);
            worker.start();
        }catch(Throwable error){
            Log.i(TAG,"GGUF_WARMUP_SKIPPED reason=thread");
        }
    }

    private static long engineHandle(){
        try{
            Class<?> manager=Class.forName("com.ggufchat.app.EngineManager");
            Method current=manager.getMethod("currentHandle");
            Object handle=current.invoke(null);
            return handle instanceof Long?((Long)handle).longValue():0L;
        }catch(Throwable error){
            return 0L;
        }
    }

    private static Object field(Object target,String name){
        try{
            Field field=target.getClass().getDeclaredField(name);
            field.setAccessible(true);
            return field.get(target);
        }catch(Throwable error){
            return null;
        }
    }
}
