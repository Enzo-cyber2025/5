package com.ggufchat.app;
import android.content.Context;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class GenerationStatsUi {
    public static void caption(Context c,LinearLayout column,Object message){
        if(message==null)return;
        try {
            if(!"assistant".equals(message.getClass().getField("role").get(message)))return;
            String value=(String)message.getClass().getField("generationMetrics").get(message);
            TextView view=new TextView(c);view.setText(GenerationStats.label(value));view.setTextSize(11);
            view.setTextColor(0xff9cafa6);view.setContentDescription("Velocidade da resposta");
            int pad=Math.round(4*c.getResources().getDisplayMetrics().density);
            view.setPadding(pad,pad,pad,pad);column.addView(view);
        }catch(Exception e){throw new IllegalStateException("Não foi possível exibir a medição",e);}
    }
}
