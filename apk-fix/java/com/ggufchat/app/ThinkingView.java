package com.ggufchat.app;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.IdentityHashMap;
import java.util.Map;

/** Reasoning shown apart from the answer: collapsible "Raciocínio" panel.
 * The raw model text keeps its <thinking> block, so history, persistence and the
 * original answer are untouched; only the presentation is separated.
 */
public final class ThinkingView {
    private static final Map<LinearLayout,Holder> PANELS=new IdentityHashMap<>();
    private static final String OPEN="<thinking>";
    private static final String CLOSE="</thinking>";

    private static final class Holder {
        final LinearLayout panel;final TextView header,body;final Button toggle;
        boolean expanded,hasText;
        Holder(LinearLayout p,TextView h,TextView b,Button t){panel=p;header=h;body=b;toggle=t;}
    }

    private ThinkingView(){}

    private static int dp(Context c,int n){return Math.round(c.getResources().getDisplayMetrics().density*n);}

    /** [0] = raciocínio, [1] = resposta. Streaming com bloco ainda aberto devolve a
     * resposta vazia em vez de vazar o raciocínio para o balão da resposta. */
    public static String[] split(String raw){
        String text=raw==null?"":raw;
        int start=indexOfTag(text,OPEN);
        if(start<0)return new String[]{"",text};
        int body=start+OPEN.length();
        int end=indexOfTag(text,body,CLOSE);
        if(end<0)return new String[]{text.substring(body).trim(),""};
        String thinking=text.substring(body,end).trim();
        String answer=(text.substring(0,start)+text.substring(end+CLOSE.length())).trim();
        return new String[]{thinking,answer};
    }

    private static int indexOfTag(String text,String tag){return indexOfTag(text,0,tag);}
    private static int indexOfTag(String text,int from,String tag){
        return text.toLowerCase(java.util.Locale.ROOT).indexOf(tag,from);
    }

    public static boolean hasReasoning(String raw){return split(raw)[0].length()>0;}

    /** Histórico: painel recolhido no topo da coluna da mensagem. */
    public static void attach(LinearLayout column,String thinking){
        Holder holder=panel(column);
        update(column,holder,thinking);
    }

    /** Streaming: mantém o raciocínio fora do balão da resposta, em tempo real.
     * O texto da resposta continua sendo entregue ao renderizador incremental. */
    public static void reasoning(LinearLayout column,String thinking){
        if(column==null||thinking==null||thinking.length()==0)return;
        update(column,panel(column),thinking);
    }

    private static void update(LinearLayout column,Holder holder,String thinking){
        holder.hasText=thinking.length()>0;
        if(!holder.hasText){
            holder.panel.setVisibility(View.GONE);
            return;
        }
        holder.panel.setVisibility(View.VISIBLE);
        holder.header.setText("Raciocínio · "+thinking.length()+" caracteres");
        MarkdownText.clear(holder.body);
        MarkdownText.set(holder.body,thinking);
        holder.body.setVisibility(holder.expanded?View.VISIBLE:View.GONE);
        holder.toggle.setText(holder.expanded?"Ocultar":"Mostrar raciocínio");
        holder.panel.setContentDescription("Raciocínio");
    }

    private static Holder panel(LinearLayout column){
        Holder holder=PANELS.get(column);
        if(holder!=null)return holder;
        Context c=column.getContext();
        LinearLayout panel=new LinearLayout(c);
        panel.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable box=new GradientDrawable();
        box.setColor(0xff152430);box.setCornerRadius(dp(c,12));panel.setBackground(box);
        panel.setPadding(dp(c,12),dp(c,8),dp(c,12),dp(c,10));
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);
        params.setMargins(0,0,0,dp(c,6));
        panel.setLayoutParams(params);
        LinearLayout bar=new LinearLayout(c);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        final TextView header=new TextView(c);
        header.setTextSize(12);header.setTextColor(0xff9fb4c4);header.setSingleLine(true);
        header.setEllipsize(TextUtils.TruncateAt.END);
        bar.addView(header,new LinearLayout.LayoutParams(0,-2,1));
        final Button toggle=new Button(c);
        toggle.setAllCaps(false);toggle.setTextSize(11.5f);toggle.setMinWidth(0);toggle.setMinimumWidth(0);
        toggle.setMinHeight(0);toggle.setMinimumHeight(0);toggle.setPadding(dp(c,8),0,dp(c,8),0);
        toggle.setText("Mostrar raciocínio");
        toggle.setContentDescription("Alternar raciocínio");
        bar.addView(toggle,new LinearLayout.LayoutParams(-2,dp(c,32)));
        panel.addView(bar,new LinearLayout.LayoutParams(-1,-2));
        final TextView body=new TextView(c);
        body.setTextSize(12.5f);body.setTextColor(0xffc2d2de);body.setTextIsSelectable(true);
        body.setPadding(0,dp(c,6),0,0);
        body.setContentDescription("Raciocínio detalhado");
        body.setVisibility(View.GONE);
        panel.addView(body,new LinearLayout.LayoutParams(-1,-2));
        holder=new Holder(panel,header,body,toggle);
        final Holder created=holder;
        View.OnClickListener listener=new View.OnClickListener(){
            @Override public void onClick(View v){
                created.expanded=!created.expanded;
                created.body.setVisibility(created.expanded?View.VISIBLE:View.GONE);
                created.toggle.setText(created.expanded?"Ocultar":"Mostrar raciocínio");
                Log.i("GGUFThinking","GGUF_THINKING_TOGGLED expanded="+(created.expanded?1:0));
            }
        };
        toggle.setOnClickListener(listener);
        bar.setOnClickListener(listener);
        column.addView(panel,0);
        PANELS.put(column,holder);
        Log.i("GGUFThinking","GGUF_THINKING_PANEL attached=1");
        return holder;
    }

    /** Histórico já renderizado: o balão "Raciocínio:" vira painel recolhível e o
     * texto restante recebe formatação inline (negrito, itálico, código). */
    public static void upgrade(android.content.Context context,LinearLayout column){
        if(column==null)return;
        int answerIndex=-1;
        for(int i=column.getChildCount()-1;i>=0;i--){
            if(!(column.getChildAt(i) instanceof TextView))continue;
            TextView view=(TextView)column.getChildAt(i);
            String text=view.getText().toString();
            if(text.startsWith("Raciocínio:")){
                String thinking=text.substring("Raciocínio:".length()).trim();
                column.removeViewAt(i);
                if(thinking.length()>0)attach(column,thinking);
                else Log.i("GGUFThinking","GGUF_THINKING_EMPTY_BLOCK removed=1");
                answerIndex=-1;
            }
        }
        for(int i=0;i<column.getChildCount();i++){
            if(!(column.getChildAt(i) instanceof TextView))continue;
            TextView view=(TextView)column.getChildAt(i);
            String text=view.getText().toString();
            if(text.contains("*")||text.contains("`")||text.contains("~"))MarkdownText.set(view,text);
            if(answerIndex<0&&text.trim().length()>0){answerIndex=i;view.setContentDescription("Resposta");}
        }
        Log.i("GGUFThinking","GGUF_THINKING_UPGRADE column_children="+column.getChildCount());
    }

    /** Fim da geração: mantém o painel montado (o histórico já o reconstrói). */
    public static void reset(LinearLayout column){PANELS.remove(column);}
}
