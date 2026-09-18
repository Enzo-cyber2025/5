package com.ggufchat.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.util.IdentityHashMap;

/** Opt-in experiment: private, same-process generation events, FIFO on main.
 * No text batching, timer, model changes or delayed first token. The service
 * remains the authoritative writer; paused Activities receive no stale events.
 * System broadcasts/notifications and all other app broadcasts are untouched.
 */
public final class LocalGenerationStream {
    private static final boolean ENABLED="1".equals(System.getenv("GGUF_LOCAL_STREAM"));
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final IdentityHashMap<BroadcastReceiver,Registration> RECEIVERS=new IdentityHashMap<>();
    private static final class Registration {
        final Context context;final BroadcastReceiver receiver;
        volatile boolean active=true;
        Registration(Context c,BroadcastReceiver r){context=c;receiver=r;}
    }
    static {Log.i("GGUFNative","GGUF_LOCAL_STREAM enabled="+(ENABLED?1:0));}
    private static boolean known(String action){
        return "com.ggufchat.app.action.TOKEN".equals(action)
            || "com.ggufchat.app.action.DONE".equals(action)
            || "com.ggufchat.app.action.ERROR".equals(action);
    }
    private static Intent attach(Context c,BroadcastReceiver receiver,IntentFilter filter){
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("UI registration must run on main");
        if(filter.countActions()!=3 || filter.countDataSchemes()!=0 || filter.countDataTypes()!=0 || filter.countCategories()!=0)
            throw new IllegalArgumentException("Unexpected generation filter");
        for(int i=0;i<filter.countActions();i++)if(!known(filter.getAction(i)))throw new IllegalArgumentException("Unknown generation action");
        synchronized(RECEIVERS){
            Registration old=RECEIVERS.get(receiver);
            if(old!=null){if(old.context!=c)throw new IllegalArgumentException("Receiver context changed");return null;}
            RECEIVERS.put(receiver,new Registration(c,receiver));
        }
        return null; // These private generation events are never sticky.
    }
    public static Intent register(Context c,BroadcastReceiver r,IntentFilter f,int flags){
        return ENABLED?attach(c,r,f):c.registerReceiver(r,f,flags);
    }
    public static Intent register(Context c,BroadcastReceiver r,IntentFilter f){
        return ENABLED?attach(c,r,f):c.registerReceiver(r,f);
    }
    public static void unregister(Context c,BroadcastReceiver r){
        if(!ENABLED){c.unregisterReceiver(r);return;}
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("UI removal must run on main");
        synchronized(RECEIVERS){
            Registration old=RECEIVERS.get(r);
            if(old==null || old.context!=c)throw new IllegalArgumentException("Receiver not registered here");
            old.active=false;RECEIVERS.remove(r);
        }
    }
    public static void send(Context c,Intent original){
        if(!ENABLED){c.sendBroadcast(original);return;}
        if(!known(original.getAction()) || !c.getPackageName().equals(original.getPackage()))
            throw new IllegalArgumentException("Only private generation events may use this route");
        // All patched producers create a fresh Intent containing only immutable
        // strings/booleans. Copy extras before returning to the producer.
        final Intent event=new Intent(original);
        synchronized(RECEIVERS){
            if(RECEIVERS.isEmpty())return; // Authoritative saving/notification still runs in service.
            final Registration[] snapshot=RECEIVERS.values().toArray(new Registration[0]);
            if(!MAIN.post(new Runnable(){public void run(){
                for(Registration r:snapshot)if(r.active)r.receiver.onReceive(r.context,new Intent(event));
            }}))throw new IllegalStateException("Main event queue stopped");
        }
    }
}
