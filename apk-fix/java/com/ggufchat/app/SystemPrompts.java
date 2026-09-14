package com.ggufchat.app;

import android.app.*;
import android.content.*;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;

/** Explicit system-role instructions: global default, chat override and presets.
 * Saved chat overrides travel in Chat JSON; they are not ordinary user messages.
 */
public final class SystemPrompts {
    public static final String DEFAULT="Você é um assistente útil, direto e preciso. Responda em português a menos que o usuário peça outro idioma.";
    private static final String[] TITLES={"Personalizado","Assistente em português","Programação","Analisar documentos"};
    private static final String[] PRESETS={"",DEFAULT,"Você é um assistente de programação. Explique as alterações e forneça código verificável. Não diga que executou testes que não executou.","Analise apenas o conteúdo fornecido. Diferencie fatos, inferências e conteúdo ilegível. Não invente páginas, anexos ou citações. Responda em português."};
    private static Object get(Object o,String n) throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    private static SharedPreferences prefs(Context c){return c.getSharedPreferences("gguf-system-prompts",Context.MODE_PRIVATE);}
    public static void readInfo(Object chat,JSONObject j) throws Exception {
        chat.getClass().getField("systemPrompt").set(chat,j.has("systemPrompt")&&!j.isNull("systemPrompt")?j.getString("systemPrompt"):null);
    }
    public static void writeInfo(Object chat,JSONObject j) throws Exception {
        Object s=get(chat,"systemPrompt");j.put("systemPrompt",s==null?JSONObject.NULL:s);
    }
    public static String resolve(Context c,Object chat) throws Exception {
        String s=(String)get(chat,"systemPrompt");return s!=null?s:prefs(c).getString("global",DEFAULT);
    }
    public static void apply(Context c,Object chat,List<String[]> rows) throws Exception {
        if(rows.isEmpty()||!"system".equals(rows.get(0)[0])||!rows.get(0)[1].startsWith(DEFAULT))throw new IllegalStateException("Formato de prompt de sistema inesperado");
        String custom=resolve(c,chat);
        if(custom.length()>32768)throw new IllegalArgumentException("Prompt de sistema excede 32.768 caracteres; reduza-o explicitamente");
        // Keep original thinking/search additions, but replace the default exactly once.
        rows.get(0)[1]=custom+rows.get(0)[1].substring(DEFAULT.length());
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(custom.getBytes(StandardCharsets.UTF_8));StringBuilder hex=new StringBuilder();for(byte b:digest)hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        android.util.Log.i("GGUFSystem","GGUF_SYSTEM_PROMPT_APPLIED scope="+(get(chat,"systemPrompt")==null?"global":"chat")+" chars="+custom.length()+" sha256="+hex);
    }
    public static Button chatButton(Activity a){
        Button b=new Button(a);b.setText("Sistema");b.setContentDescription("Prompt de sistema da conversa");
        b.setOnClickListener(v->{try{
            if(Boolean.TRUE.equals(get(a,"generating"))||Boolean.TRUE.equals(get(a,"loading"))){Toast.makeText(a,"Aguarde a geração/carregamento antes de editar o prompt.",Toast.LENGTH_LONG).show();return;}
            editor(a,get(a,"chat"));
        }catch(Exception e){error(a,e);}});return b;
    }
    public static void installGlobal(Activity a,LinearLayout root){
        Button b=new Button(a);b.setText("Prompt de sistema global");b.setContentDescription("Prompt de sistema global");CompactUi.style(b);
        b.setOnClickListener(v->editor(a,null));root.addView(b,0);
    }
    private static void error(Context c,Exception e){Toast.makeText(c,"Não foi possível salvar/ler o prompt: "+e.getMessage(),Toast.LENGTH_LONG).show();}
    private static void editor(Activity a,Object chat){
        try {
            LinearLayout layout=new LinearLayout(a);layout.setOrientation(LinearLayout.VERTICAL);layout.setPadding(24,12,24,12);
            TextView description=new TextView(a);description.setText(chat==null?"Padrão usado pelas conversas sem configuração própria. Presets não são aplicados até salvar.":"Instrução enviada no papel system. Substitui o padrão global nesta conversa; não apaga o histórico.");layout.addView(description);
            Spinner preset=new Spinner(a);preset.setAdapter(new ArrayAdapter<String>(a,android.R.layout.simple_spinner_dropdown_item,TITLES));layout.addView(preset);
            EditText input=new EditText(a);input.setContentDescription("Texto do prompt de sistema");input.setGravity(Gravity.TOP);input.setMinLines(4);input.setMaxLines(9);input.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
            input.setText(chat==null?prefs(a).getString("global",DEFAULT):resolve(a,chat));layout.addView(input);
            preset.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
                public void onItemSelected(android.widget.AdapterView<?> parent,View view,int pos,long id){if(pos>0)input.setText(PRESETS[pos]);}
                public void onNothingSelected(android.widget.AdapterView<?> parent){}
            });
            AlertDialog dialog=new AlertDialog.Builder(a).setTitle(chat==null?"Prompt de sistema global":"Prompt de sistema da conversa").setView(layout)
                .setPositiveButton("Salvar",null).setNegativeButton("Cancelar",null).setNeutralButton(chat==null?"Restaurar padrão":"Usar padrão global",null).create();
            dialog.setOnShowListener(v->{
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(button->{try{
                    String text=input.getText().toString();if(text.length()>32768)throw new IllegalArgumentException("Máximo de 32.768 caracteres, sem corte automático");
                    persist(a,chat,text);dialog.dismiss();
                }catch(Exception e){error(a,e);}});
                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(button->{try{persist(a,chat,chat==null?DEFAULT:null);dialog.dismiss();}catch(Exception e){error(a,e);}});
            });dialog.show();
        }catch(Exception e){error(a,e);}
    }
    private static void persist(Context c,Object chat,String text) throws Exception {
        if(chat==null){if(!prefs(c).edit().putString("global",text).commit())throw new java.io.IOException("Falha de armazenamento");}
        else {
            Field f=chat.getClass().getField("systemPrompt");Object previous=f.get(chat);f.set(chat,text);
            try{Class.forName("com.ggufchat.app.ChatStore").getMethod("upsert",Context.class,chat.getClass()).invoke(null,c,chat);
                List<?> saved=(List<?>)Class.forName("com.ggufchat.app.ChatStore").getMethod("load",Context.class).invoke(null,c);
                boolean found=false;for(Object row:saved)if(get(row,"id").equals(get(chat,"id"))&&java.util.Objects.equals(get(row,"systemPrompt"),text))found=true;
                if(!found)throw new java.io.IOException("Prompt não foi persistido");
            }catch(Exception e){f.set(chat,previous);throw e;}
        }
        Toast.makeText(c,"Prompt de sistema salvo",Toast.LENGTH_SHORT).show();
    }
}
