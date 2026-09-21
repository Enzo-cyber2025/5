package com.ggufchat.app;
import android.app.Activity;
import android.os.SystemClock;
import android.util.Log;
import java.util.WeakHashMap;
/** Main-thread Send-handler -> first actual received text, not synthetic token speed. */
public final class ResponseTiming {
    private static final WeakHashMap<Activity,Long> starts=new WeakHashMap<Activity,Long>();
    public static void sent(Activity a){starts.put(a,SystemClock.elapsedRealtimeNanos());}
    public static void first(Activity a){
        Long start=starts.remove(a);
        if(start!=null)Log.i("GGUFUiTiming","GGUF_UI_FIRST_TEXT send_to_first_ui_ns="+(SystemClock.elapsedRealtimeNanos()-start));
    }
}
