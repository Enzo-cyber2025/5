package com.enzo.ets2ai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.drawable.Icon;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.PowerManager;
import android.provider.Settings;

import java.util.Locale;

/**
 * Servico em 1o plano: mantem a IA rodando NA MESMA VELOCIDADE com a tela
 * bloqueada. Segura um wake lock parcial (CPU acordada) e um Wi-Fi lock de
 * alto desempenho enquanto o bridge/teclado BT estao ativos — sem isso o
 * Android entra em Doze, afina a CPU e a taxa de comandos por segundo cai.
 *
 * A notificacao mostra cmd/s + RTT ao vivo (a prova de que a velocidade se
 * mantem com a tela ligada OU bloqueada) e traz o botao Encerrar.
 */
public final class KeepAlive extends Service {

    public static final String ACTION_START = "com.enzo.ets2ai.KEEPALIVE_START";
    public static final String ACTION_STOP = "com.enzo.ets2ai.KEEPALIVE_STOP";
    private static final String CHANNEL = "ets2ai-drive";

    /** Bridge observado pela notificacao (fracamente: so enquanto vivo). */
    private static volatile BridgeClient watched;

    private PowerManager.WakeLock cpu;
    private WifiManager.WifiLock wifi;
    private final Handler handler = new Handler();
    private String label = "IA ativa";

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL,
                    "IA dirigindo (tela bloqueada)", NotificationManager.IMPORTANCE_LOW);
            nm.createNotificationChannel(ch);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null && intent.getAction() != null
                ? intent.getAction() : ACTION_START;
        if (ACTION_STOP.equals(action)) {
            handler.removeCallbacks(ticker);
            releaseLocks();
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }
        String extra = intent != null ? intent.getStringExtra("label") : null;
        if (extra != null) label = extra;
        acquireLocks();
        startForeground(1, notification(text()));
        requestBatteryExemptionOnce();
        handler.removeCallbacks(ticker);
        ticker.run();
        return START_STICKY;
    }

    @Override public void onDestroy() {
        handler.removeCallbacks(ticker);
        releaseLocks();
        super.onDestroy();
    }

    /** Ciclo de 2 s: notificacao viva com a velocidade real da IA. */
    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(1, notification(text()));
            handler.postDelayed(this, 2000);
        }
    };

    private String text() {
        BridgeClient b = watched;
        if (b == null) return label;
        return label + String.format(Locale.US, " | %.0f cmd/s | RTT %.0f ms",
                b.hz, b.lastRttMs < 0f ? 0f : b.lastRttMs);
    }

    private void acquireLocks() {
        if (cpu == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            cpu = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ets2ai:drive");
            cpu.setReferenceCounted(false);
            cpu.acquire();   // solta quando o usuario encerra (botao da notificacao)
        }
        if (wifi == null) {
            try {
                WifiManager wm = (WifiManager) getApplicationContext()
                        .getSystemService(WIFI_SERVICE);
                wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "ets2ai:wifi");
                wifi.setReferenceCounted(false);
                wifi.acquire();
            } catch (Exception ignored) { }
        }
    }

    private void releaseLocks() {
        try { if (cpu != null && cpu.isHeld()) cpu.release(); } catch (Exception ignored) { }
        try { if (wifi != null && wifi.isHeld()) wifi.release(); } catch (Exception ignored) { }
        cpu = null;
        wifi = null;
    }

    /** Pede 1x a isencao de otimizacao de bateria (agressivo em Samsungs). */
    private void requestBatteryExemptionOnce() {
        SharedPreferences sp = getSharedPreferences("ets2ai", MODE_PRIVATE);
        if (sp.getBoolean("battery_asked", false)) return;
        sp.edit().putBoolean("battery_asked", true).apply();
        try {
            Intent it = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:com.enzo.ets2ai"));
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(it);
        } catch (Exception ignored) { }
    }

    private Notification notification(String text) {
        PendingIntent stop = PendingIntent.getService(this, 2,
                new Intent(this, KeepAlive.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setContentTitle("ETS2-AI dirigindo")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.sym_def_app_icon)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(
                        Icon.createWithResource(this,
                                android.R.drawable.ic_menu_close_clear_cancel),
                        "Encerrar", stop).build())
                .build();
    }

    // ------------------------------------------------------------- estatica

    /** Liga o modo tela-bloqueada (chamar quando bridge/teclado BT ativam). */
    public static void begin(Context ctx, String label, BridgeClient watch) {
        watched = watch;
        try {
            Intent it = new Intent(ctx, KeepAlive.class);
            it.setAction(ACTION_START);
            it.putExtra("label", label);
            ctx.startForegroundService(it);
        } catch (Exception e) {
            // contexto invalido ou Android < 8: a IA segue funcionando,
            // so sem a garantia de velocidade com a tela bloqueada.
        }
    }

    /** Desliga quando nenhuma fonte (bridge/teclado BT) esta ativa. */
    public static void end(Context ctx) {
        watched = null;
        try {
            ctx.startService(new Intent(ctx, KeepAlive.class).setAction(ACTION_STOP));
        } catch (Exception ignored) { }
    }
}
