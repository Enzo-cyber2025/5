package com.ggufchat.app;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import android.util.Log;
import java.util.ArrayDeque;

/** User-started, on-device work. No alarms, boot receiver or silent restart.
 * Service owns the worker until all submitted imports terminate. */
public final class ComputeService extends Service {
    private static final ArrayDeque<Runnable> QUEUE=new ArrayDeque<>();
    private static final String CANCEL="com.ggufchat.app.CANCEL_IMPORT";
    private static final int ID=2002;
    private Thread worker;
    private final Handler main=new Handler(Looper.getMainLooper());
    public static void submit(Context c,Runnable task) {
        synchronized(QUEUE){
            QUEUE.add(task);
            try { c.getApplicationContext().startForegroundService(new Intent(c,ComputeService.class)); }
            catch(RuntimeException e){QUEUE.remove(task);throw e;}
        }
    }
    public static void startThread(Context c,Thread task){submit(c,task);}
    public static void promote(Service service,int id,Notification notification) {
        if(Build.VERSION.SDK_INT>=34)service.startForeground(id,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else service.startForeground(id,notification);
    }
    private Notification notification(String text) {
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("local-compute","Processamento local de IA",NotificationManager.IMPORTANCE_LOW));
        Intent launch=getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent open=PendingIntent.getActivity(this,ID,launch,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        PendingIntent cancel=PendingIntent.getService(this,ID,new Intent(this,ComputeService.class).setAction(CANCEL),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,"local-compute").setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("GGUF Chat · processamento local").setContentText(text).setContentIntent(open)
            .setOngoing(true).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(new Notification.Action.Builder(null,"Cancelar",cancel).build()).build();
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        promote(this,ID,notification("Importando e validando GGUF. Pode bloquear a tela."));
        if(intent!=null&&CANCEL.equals(intent.getAction())) {
            // Do not drop queued transactions: each must run its cleanup/failure path.
            if(worker!=null)worker.interrupt();else drain();
            getSystemService(NotificationManager.class).notify(ID,notification("Cancelando com segurança; aguarde a etapa nativa terminar."));
        } else drain();
        return START_NOT_STICKY;
    }
    private void drain() {
        if(worker!=null)return;
        WorkWakeLocks.acquire(this);
        worker=new Thread(()->{
            try {
                while(true){Runnable task;synchronized(QUEUE){task=QUEUE.poll();}if(task==null)break;
                    try{task.run();}catch(Throwable e){Log.e("GGUFCompute","Import worker failed",e);}
                }
            } finally {main.post(()->{
                worker=null;
                synchronized(QUEUE){if(!QUEUE.isEmpty()){drain();return;}}
                WorkWakeLocks.release(this);stopForeground(true);stopSelf();
                Log.i("GGUFCompute","GGUF_COMPUTE_FINISHED wakelock_released=1");
            });}
        },"gguf-import-service");
        worker.start();Log.i("GGUFCompute","GGUF_COMPUTE_STARTED foreground=1");
    }
    @Override public void onDestroy(){if(worker!=null)worker.interrupt();WorkWakeLocks.release(this);super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
