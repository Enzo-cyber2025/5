package com.ggufchat.app;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import android.util.Log;
import java.lang.reflect.Field;
import java.util.concurrent.ConcurrentHashMap;

/** Completion alerts are independent of the quiet foreground-service notice.
 * Never include prompts, generated text or chat titles on the lock screen.
 * Token generation, callbacks, storage and native caches are not throttled.
 */
public final class ReplyNotifications {
    public static final String CHANNEL="reply-ready-v1";
    private static final int READY_ID=2101;
    private static final String TAG="GGUFReplyNotice";
    private static final ConcurrentHashMap<Service,State> STATES=new ConcurrentHashMap<>();
    private static final Handler MAIN=new Handler(Looper.getMainLooper());

    private static final class State extends BroadcastReceiver {
        final Context app;
        volatile boolean interactive;
        boolean registered, persisted;
        String chatId;
        long lastUpdate, updates, skippedOff;
        State(Service service) {
            app=service.getApplicationContext();
            PowerManager pm=app.getSystemService(PowerManager.class);
            interactive=pm==null || pm.isInteractive();
        }
        @Override public void onReceive(Context context,Intent intent) {
            if(Intent.ACTION_SCREEN_OFF.equals(intent.getAction()))interactive=false;
            else if(Intent.ACTION_SCREEN_ON.equals(intent.getAction()))interactive=true;
        }
    }
    public static void install(Service service) {
        State state=new State(service);
        if(STATES.putIfAbsent(service,state)!=null)return;
        try {
            IntentFilter filter=new IntentFilter(Intent.ACTION_SCREEN_ON);
            filter.addAction(Intent.ACTION_SCREEN_OFF);
            if(Build.VERSION.SDK_INT>=33)state.app.registerReceiver(state,filter,Context.RECEIVER_NOT_EXPORTED);
            else state.app.registerReceiver(state,filter);
            state.registered=true;
        } catch(RuntimeException e) { Log.w(TAG,"Screen-state observer unavailable",e); }
        try {
            NotificationManager nm=service.getSystemService(NotificationManager.class);
            NotificationChannel channel=new NotificationChannel(CHANNEL,"Respostas prontas",NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Avisa quando a resposta foi salva com a tela apagada ou bloqueada. Respeita as configurações do Android.");
            channel.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
            nm.createNotificationChannel(channel);
            nm.cancel(1002); // Remove only the obsolete, untagged completion notice.
        } catch(RuntimeException e) { Log.w(TAG,"Completion channel unavailable",e); }
    }
    private static String tag(String chatId){return "reply-ready:"+chatId;}
    public static void begin(Service service,String chatId) {
        State s=STATES.get(service);if(s==null){install(service);s=STATES.get(service);}
        s.chatId=chatId;s.persisted=false;s.lastUpdate=0;s.updates=0;s.skippedOff=0;
        // A previous reply in THIS chat must not masquerade as this request's
        // completion if the new request is cancelled. Other chats are untouched.
        try { service.getSystemService(NotificationManager.class).cancel(tag(chatId),READY_ID); }
        catch(RuntimeException e){Log.w(TAG,"Old reply notice could not be removed",e);}
    }
    public static void persisted(Service service) {
        State s=STATES.get(service);if(s!=null)s.persisted=true;
    }
    public static boolean progressNow(Service service) {
        State s=STATES.get(service);if(s==null)return false;
        // Screen broadcasts update a volatile flag, avoiding a PowerManager IPC
        // per token callback. If registration failed, keep the safe old cadence.
        if(s.registered&&!s.interactive){s.skippedOff++;return false;}
        long now=SystemClock.elapsedRealtime();
        if(s.updates>0 && now-s.lastUpdate<1000)return false;
        s.lastUpdate=now;s.updates++;return true;
    }
    public static void finished(Service service,boolean success) {
        State s=STATES.get(service);if(s==null)return;
        Log.i(TAG,"GGUF_NOTICE_STATS progress_updates="+s.updates+" skipped_screen_off="+s.skippedOff);
        if(!success || !s.persisted || s.chatId==null) {
            Log.i(TAG,"GGUF_REPLY_NOTICE suppressed=not_saved_success");return;
        }
        try {
            // Authoritative completion-time check, not a possibly delayed screen
            // broadcast. A locked ambient display is covered as well.
            PowerManager pm=service.getSystemService(PowerManager.class);
            KeyguardManager keyguard=service.getSystemService(KeyguardManager.class);
            boolean off=pm!=null&&!pm.isInteractive();
            boolean locked=keyguard!=null&&keyguard.isKeyguardLocked();
            if(!off&&!locked){Log.i(TAG,"GGUF_REPLY_NOTICE suppressed=screen_active");return;}
            NotificationManager nm=service.getSystemService(NotificationManager.class);
            if(!nm.areNotificationsEnabled() || (Build.VERSION.SDK_INT>=33 && service.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)) {
                Log.i(TAG,"GGUF_REPLY_NOTICE blocked=permission");return;
            }
            NotificationChannel channel=nm.getNotificationChannel(CHANNEL);
            if(channel==null||channel.getImportance()==NotificationManager.IMPORTANCE_NONE){Log.i(TAG,"GGUF_REPLY_NOTICE blocked=channel");return;}
            Intent intent=new Intent().setClassName(service,service.getPackageName()+".ChatActivity")
                .setData(new Uri.Builder().scheme("ggufchat").authority("reply").appendPath(s.chatId).build())
                .putExtra("chatId",s.chatId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP);
            PendingIntent open=PendingIntent.getActivity(service,0,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            Notification publicNotice=new Notification.Builder(service,CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_chat).setContentTitle("GGUF Chat")
                .setContentText("Resposta pronta").build();
            Notification notice=new Notification.Builder(service,CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_chat).setContentTitle("Resposta pronta")
                .setContentText("A resposta foi salva. Toque para abrir a conversa.")
                .setContentIntent(open).setAutoCancel(true).setOngoing(false)
                .setCategory(Notification.CATEGORY_MESSAGE).setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(publicNotice).build();
            nm.notify(tag(s.chatId),READY_ID,notice);
            Log.i(TAG,"GGUF_REPLY_NOTICE posted=1 saved=1 screen_off="+(off?1:0)+" locked="+(locked?1:0));
        } catch(RuntimeException e) {
            // A blocked notifier must never turn a saved reply into a failure.
            Log.w(TAG,"GGUF_REPLY_NOTICE unavailable",e);
        }
    }
    public static void workerFinished(Service service) {
        Thread owner=Thread.currentThread();
        MAIN.post(()->{
            try {
                // On the main thread, onStartCommand cannot replace worker
                // between this check and stopSelf. Never stop a newer request.
                Field field=service.getClass().getDeclaredField("worker");field.setAccessible(true);
                if(field.get(service)==owner){
                    WorkWakeLocks.release(service);
                    service.stopForeground(true);
                    service.stopSelf();
                }
            } catch(ReflectiveOperationException e){Log.w(TAG,"Service completion check unavailable",e);}
        });
    }
    public static void destroy(Service service) {
        State s=STATES.remove(service);
        if(s!=null&&s.registered)try{s.app.unregisterReceiver(s);}catch(RuntimeException ignored){}
        Log.i(TAG,"GGUF_REPLY_SERVICE_DESTROYED");
    }
}
