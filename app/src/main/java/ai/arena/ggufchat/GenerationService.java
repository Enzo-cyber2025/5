package ai.arena.ggufchat;

import android.app.*;
import android.content.*;
import android.os.*;

public class GenerationService extends Service {
    public static final String ACTION_GENERATE = "ai.arena.ggufchat.GENERATE";
    public static final String EXTRA_PROMPT = "prompt";
    public static final String EXTRA_MODEL_A = "modelA";
    public static final String EXTRA_MODEL_B = "modelB";
    public static final String EXTRA_THINKING = "thinking";
    public static final String EXTRA_SEARCH = "search";
    public static final String ACTION_DONE = "ai.arena.ggufchat.DONE";
    public static final String EXTRA_RESULT = "result";
    private static final int NOTIFICATION_ID = 93;
    private static final String CHANNEL_ID = "generation";
    private PowerManager.WakeLock wakeLock;

    @Override public void onCreate() { super.onCreate(); ensureChannel(); }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || !ACTION_GENERATE.equals(intent.getAction())) return START_NOT_STICKY;
        String prompt = intent.getStringExtra(EXTRA_PROMPT);
        String modelA = intent.getStringExtra(EXTRA_MODEL_A);
        String modelB = intent.getStringExtra(EXTRA_MODEL_B);
        boolean thinking = intent.getBooleanExtra(EXTRA_THINKING, true);
        boolean search = intent.getBooleanExtra(EXTRA_SEARCH, false);
        startForeground(NOTIFICATION_ID, notification("Gerando resposta em segundo plano…", "Pode bloquear a tela; o wake lock mantém a tarefa ativa."));
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "GGUFChat:Generation");
        wakeLock.acquire(10 * 60 * 1000L);
        new Thread(() -> {
            String result;
            try {
                // Simula pipeline incremental; troca para inferência real JNI/llama quando bibliotecas forem anexadas.
                Thread.sleep(500);
                result = NativeBridge.draftAnswer(prompt == null ? "" : prompt, modelA == null ? "" : modelA, modelB == null ? "" : modelB, thinking, search);
            } catch (Throwable t) {
                result = "Falha ao gerar: " + t.getMessage();
            }
            Intent done = new Intent(ACTION_DONE).setPackage(getPackageName()).putExtra(EXTRA_RESULT, result);
            sendBroadcast(done);
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf(startId);
        }, "gguf-background-generation").start();
        return START_REDELIVER_INTENT;
    }

    @Override public void onDestroy() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(CHANNEL_ID, "Geração em segundo plano", NotificationManager.IMPORTANCE_LOW);
            c.setDescription("Mantém a geração de respostas rodando com a tela bloqueada.");
            ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(c);
        }
    }

    private Notification notification(String title, String text) {
        PendingIntent pi = PendingIntent.getActivity(this, 7, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL_ID) : new Notification.Builder(this);
        return b.setContentTitle(title).setContentText(text).setSmallIcon(android.R.drawable.stat_sys_download_done).setContentIntent(pi).setOngoing(true).build();
    }
}
