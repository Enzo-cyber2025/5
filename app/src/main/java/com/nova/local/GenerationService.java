package com.nova.local;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.net.Uri;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.os.PowerManager;

import java.io.InputStream;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/**
 * Foreground generation worker. Keeping inference here, rather than in the Activity,
 * makes a long GGUF decode survive the display going dark. The partial wake lock only
 * protects the current decode and is released as soon as the result is posted.
 */
public final class GenerationService extends Service {
    public static final String ACTION_START = "com.nova.local.action.GENERATE";
    public static final String ACTION_CANCEL = "com.nova.local.action.CANCEL";
    public static final String ACTION_PROGRESS = "com.nova.local.action.PROGRESS";
    public static final String ACTION_RESULT = "com.nova.local.action.RESULT";
    public static final String ACTION_ERROR = "com.nova.local.action.ERROR";

    private static final String CHANNEL_ID = "nova_generation";
    private static final int NOTIFICATION_ID = 42;
    private static final String EXTRA_ID = "request_id";
    private static final String EXTRA_MODEL = "model_uri";
    private static final String EXTRA_PROJECTOR = "projector_uri";
    private static final String EXTRA_PROMPT = "prompt";
    private static final String EXTRA_QUERY = "query";
    private static final String EXTRA_RESEARCH = "research";
    private static final String EXTRA_IMAGE = "image_uri";
    private static final String EXTRA_MAX = "max_tokens";
    private static final String EXTRA_TEMP = "temperature";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private Future<?> running;
    private volatile long activeHandle;
    private PowerManager.WakeLock wakeLock;

    public static void start(Context context, String requestId, String modelUri, String projectorUri,
                             String prompt, String query, boolean research, String imageUri) {
        Intent intent = new Intent(context, GenerationService.class)
                .setAction(ACTION_START)
                .putExtra(EXTRA_ID, requestId)
                .putExtra(EXTRA_MODEL, modelUri)
                .putExtra(EXTRA_PROJECTOR, projectorUri)
                .putExtra(EXTRA_PROMPT, prompt)
                .putExtra(EXTRA_QUERY, query)
                .putExtra(EXTRA_RESEARCH, research)
                .putExtra(EXTRA_IMAGE, imageUri)
                .putExtra(EXTRA_MAX, 320)
                .putExtra(EXTRA_TEMP, 0.65f);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent);
        else context.startService(intent);
    }

    public static void cancel(Context context) {
        context.startService(new Intent(context, GenerationService.class).setAction(ACTION_CANCEL));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        PowerManager powerManager = (PowerManager) getSystemService(POWER_SERVICE);
        if (powerManager != null) {
            wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                    "NovaLocal:Generation");
            wakeLock.setReferenceCounted(false);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_NOT_STICKY;
        String action = intent.getAction();
        if (ACTION_CANCEL.equals(action)) {
            NativeRuntime.cancel(activeHandle);
            if (running != null) running.cancel(true);
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!ACTION_START.equals(action)) return START_NOT_STICKY;

        startForeground(NOTIFICATION_ID, notification("Preparando o modelo…", true));
        if (running != null) running.cancel(true);
        final Intent request = intent;
        running = executor.submit(() -> runRequest(request, startId));
        return START_NOT_STICKY;
    }

    private void runRequest(Intent request, int startId) {
        String requestId = request.getStringExtra(EXTRA_ID);
        String modelUri = request.getStringExtra(EXTRA_MODEL);
        String projectorUri = request.getStringExtra(EXTRA_PROJECTOR);
        String prompt = request.getStringExtra(EXTRA_PROMPT);
        String query = request.getStringExtra(EXTRA_QUERY);
        boolean research = request.getBooleanExtra(EXTRA_RESEARCH, false);
        String imageUri = request.getStringExtra(EXTRA_IMAGE);
        int maxTokens = request.getIntExtra(EXTRA_MAX, 320);
        float temperature = request.getFloatExtra(EXTRA_TEMP, 0.65f);

        if (wakeLock != null && !wakeLock.isHeld()) {
            try { wakeLock.acquire(30 * 60 * 1000L); } catch (Throwable ignored) { }
        }

        ParcelFileDescriptor modelFd = null;
        ParcelFileDescriptor projectorFd = null;
        long handle = 0L;
        try {
            if (modelUri == null || modelUri.trim().isEmpty()) {
                fail(requestId, "Importe um GGUF antes de gerar.");
                return;
            }

            if (research) {
                progress(requestId, "Pesquisando fontes abertas…");
                String researchResult = ResearchTool.search(query);
                if (researchResult != null && !researchResult.isEmpty()) {
                    prompt = prompt + "\n\n[TOOL: RESEARCH]\n" + researchResult
                            + "\n[/TOOL]\nUse as fontes acima, mas sinalize incerteza quando necessário.";
                } else {
                    prompt = prompt + "\n\n[TOOL: RESEARCH]\nA pesquisa ao vivo não retornou resultados. Não invente fontes.\n[/TOOL]";
                }
            }

            progress(requestId, "Mapeando o GGUF diretamente da memória…");
            modelFd = getContentResolver().openFileDescriptor(Uri.parse(modelUri), "r");
            if (modelFd == null) {
                fail(requestId, "Não consegui abrir o arquivo pelo provedor de documentos.");
                return;
            }
            long modelSize = modelFd.getStatSize();
            if (projectorUri != null && !projectorUri.isEmpty()) {
                projectorFd = getContentResolver().openFileDescriptor(Uri.parse(projectorUri), "r");
            }
            progress(requestId, projectorFd == null
                    ? "Inicializando o runtime local…"
                    : "Inicializando o pipeline multimodal…");
            handle = NativeRuntime.load(modelFd, modelSize, projectorFd, true);
            activeHandle = handle;
            if (handle == 0L) {
                fail(requestId, "O GGUF não pôde ser carregado. Verifique a arquitetura e a memória livre do aparelho.");
                return;
            }

            BitmapPayload image = imageUri == null ? null : readImage(Uri.parse(imageUri));
            progress(requestId, image == null ? "Gerando no backend local…" : "Codificando a imagem + gerando…");
            String answer;
            if (image != null && projectorFd != null) {
                answer = NativeRuntime.generateWithImage(handle, ensureMediaMarker(prompt), maxTokens,
                        temperature, image.rgb, image.width, image.height);
            } else {
                answer = NativeRuntime.generate(handle, prompt, maxTokens, temperature);
            }
            if (answer == null || answer.trim().isEmpty()) {
                fail(requestId, "A geração foi interrompida ou não retornou tokens.");
                return;
            }
            result(requestId, clean(answer));
            notifyDone("Resposta pronta · Nova Local");
        } catch (Throwable error) {
            fail(requestId, "Falha durante a geração local. O modelo permanece no armazenamento original.");
        } finally {
            if (handle != 0L) NativeRuntime.release(handle);
            activeHandle = 0L;
            if (modelFd != null) try { modelFd.close(); } catch (Throwable ignored) { }
            if (projectorFd != null) try { projectorFd.close(); } catch (Throwable ignored) { }
            if (wakeLock != null && wakeLock.isHeld()) {
                try { wakeLock.release(); } catch (Throwable ignored) { }
            }
            stopForeground(true);
            stopSelf(startId);
        }
    }

    private BitmapPayload readImage(Uri uri) {
        InputStream stream = null;
        try {
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            stream = getContentResolver().openInputStream(uri);
            if (stream == null) return null;
            BitmapFactory.decodeStream(stream, null, bounds);
            stream.close();
            int sample = 1;
            while (Math.max(bounds.outWidth, bounds.outHeight) / sample > 1024) sample *= 2;
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inSampleSize = Math.max(1, sample);
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            stream = getContentResolver().openInputStream(uri);
            Bitmap bitmap = BitmapFactory.decodeStream(stream, null, options);
            if (stream != null) stream.close();
            if (bitmap == null) return null;
            if (bitmap.getWidth() > 1024 || bitmap.getHeight() > 1024) {
                float scale = Math.min(1024f / bitmap.getWidth(), 1024f / bitmap.getHeight());
                Bitmap scaled = Bitmap.createScaledBitmap(bitmap,
                        Math.max(1, Math.round(bitmap.getWidth() * scale)),
                        Math.max(1, Math.round(bitmap.getHeight() * scale)), true);
                if (scaled != bitmap) bitmap.recycle();
                bitmap = scaled;
            }
            int width = bitmap.getWidth();
            int height = bitmap.getHeight();
            int[] pixels = new int[width * height];
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
            byte[] rgb = new byte[width * height * 3];
            for (int i = 0, p = 0; i < pixels.length; i++) {
                int color = pixels[i];
                rgb[p++] = (byte) Color.red(color);
                rgb[p++] = (byte) Color.green(color);
                rgb[p++] = (byte) Color.blue(color);
            }
            bitmap.recycle();
            return new BitmapPayload(rgb, width, height);
        } catch (Throwable ignored) {
            if (stream != null) try { stream.close(); } catch (Throwable ignoredAgain) { }
            return null;
        }
    }

    private static String ensureMediaMarker(String prompt) {
        if (prompt == null) return "<__media__>\nDescreva esta imagem.";
        return prompt.contains("<__media__>") ? prompt : "<__media__>\n" + prompt;
    }

    private static String clean(String answer) {
        return answer.replace("<|assistant|>", "").replace("<|eot_id|>", "")
                .replace("<|end|>", "").trim();
    }

    private void progress(String requestId, String message) {
        send(ACTION_PROGRESS, requestId, message, null);
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(NOTIFICATION_ID, notification(message, true));
    }

    private void result(String requestId, String answer) {
        send(ACTION_RESULT, requestId, null, answer);
    }

    private void fail(String requestId, String message) {
        send(ACTION_ERROR, requestId, message, null);
        notifyDone(message);
    }

    private void send(String action, String requestId, String message, String answer) {
        Intent intent = new Intent(action).setPackage(getPackageName()).putExtra(EXTRA_ID, requestId);
        if (message != null) intent.putExtra("message", message);
        if (answer != null) intent.putExtra("answer", answer);
        sendBroadcast(intent);
    }

    private void notifyDone(String message) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(NOTIFICATION_ID, notification(message, false));
    }

    private Notification notification(String message, boolean ongoing) {
        Intent cancelIntent = new Intent(this, GenerationService.class).setAction(ACTION_CANCEL);
        PendingIntent cancel = PendingIntent.getService(this, 44, cancelIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setSmallIcon(com.nova.local.R.drawable.ic_nova)
                .setContentTitle("Nova Local")
                .setContentText(message)
                .setOngoing(ongoing)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE);
        if (ongoing) builder.addAction(new Notification.Action.Builder(null, "Parar", cancel).build());
        return builder.build();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Geração local",
                    NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Status de inferência GGUF em segundo plano");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override
    public void onDestroy() {
        NativeRuntime.cancel(activeHandle);
        if (running != null) running.cancel(true);
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    private static final class BitmapPayload {
        final byte[] rgb;
        final int width;
        final int height;
        BitmapPayload(byte[] rgb, int width, int height) {
            this.rgb = rgb;
            this.width = width;
            this.height = height;
        }
    }
}
