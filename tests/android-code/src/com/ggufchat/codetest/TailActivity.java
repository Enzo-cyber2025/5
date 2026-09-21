package com.ggufchat.codetest;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.content.Context;
import android.util.Log;
import android.widget.*;
import java.lang.reflect.Method;

/** Explicit UI fixture, not model output. Exercises the installed APK's helper. */
public final class TailActivity extends Activity {
    ScrollView scroll;TextView body,status;Method request;int stage;
    protected void onCreate(Bundle saved){super.onCreate(saved);
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);
        status=new TextView(this);status.setText("Teste de rolagem, não inferência");root.addView(status);
        scroll=new ScrollView(this);body=new TextView(this);body.setTextSize(18);scroll.addView(body);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);
        try{
            Context app=createPackageContext("com.ggufchat.app",CONTEXT_INCLUDE_CODE|CONTEXT_IGNORE_SECURITY);
            request=app.getClassLoader().loadClass("com.ggufchat.app.ScrollTail").getMethod("request",ScrollView.class);
            request.invoke(null,new Object[]{null});
            scroll.post(()->grow());
        }catch(Exception e){throw new RuntimeException(e);}
    }
    void grow(){try{
        for(int i=0;i<100;i++){
            body.append("Linha "+stage+":"+i+" com ação e espaço.\n");
            request.invoke(null,scroll);
        }
        // Tests geometry after real Android layout/render, not a synthetic timing benchmark.
        new Handler().postDelayed(()->check(),250);
    }catch(Exception e){throw new RuntimeException(e);}}
    void check(){
        int range=Math.max(0,body.getHeight()-(scroll.getHeight()-scroll.getPaddingTop()-scroll.getPaddingBottom()));
        if(range<=0||scroll.getScrollY()!=range)throw new AssertionError("Tail mismatch "+scroll.getScrollY()+" / "+range);
        if(!scroll.isSmoothScrollingEnabled())throw new AssertionError("User scroll setting changed");
        if(stage++==0){grow();return;}
        status.setText("Rolagem direta OK");
        Log.i("GGUFTailTest","DIRECT_TAIL_AFTER_LAYOUT_PASS growth_rounds=2 lines=200 user_scroll_setting_preserved=1");
    }
}
