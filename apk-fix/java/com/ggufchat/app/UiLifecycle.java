package com.ggufchat.app;
import android.app.*;
import android.os.Bundle;
import android.view.*;
import android.widget.Button;

/** Apply after layout construction as well as in Ui.btn, so old navigation and
 * restored activities cannot render emoji controls or oversized defaults. */
public final class UiLifecycle implements Application.ActivityLifecycleCallbacks {
    public static void install(Application app){app.registerActivityLifecycleCallbacks(new UiLifecycle());}
    private void visit(View v){if(v instanceof Button)CompactUi.style((Button)v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)visit(g.getChildAt(i));}}
    public void onActivityResumed(Activity a){visit(a.getWindow().getDecorView());}
    public void onActivityCreated(Activity a,Bundle s){} public void onActivityStarted(Activity a){}
    public void onActivityPaused(Activity a){} public void onActivityStopped(Activity a){}
    public void onActivitySaveInstanceState(Activity a,Bundle s){} public void onActivityDestroyed(Activity a){}
}
