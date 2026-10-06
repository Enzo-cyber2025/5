package com.enzo.ets2ai;

import android.content.Context;
import android.os.Environment;

import java.io.File;
import java.io.FileWriter;
import java.util.Arrays;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * IA no CELULAR via cabo USB SIMPLES (sem Depuracao, sem portas TCP):
 * o PC escreve Download/ets2ai-s{seq}.txt (estado) pelo MTP; este worker
 * le, roda a rede (mesma do bridge TCP), responde Download/ets2ai-c{seq}.txt
 * e apaga os arquivos consumidos. Roda dentro do KeepAlive (tela pode
 * bloquear). Precisa de acesso a arquivos (pedido 1x na UI).
 */
public final class MtpWorker implements Runnable {

    private static final Pattern RE_STATE =
            Pattern.compile("^ets2ai-s(\\d+)\\.txt$");
    private volatile boolean running = true;
    private final NeuralNet net;
    public volatile long answered = 0;
    public volatile float hz = 0f;

    private long hzMark = 0L;
    private int hzCount = 0;

    public MtpWorker(NeuralNet net) {
        this.net = net;
    }

    public void stop() { running = false; }

    public static boolean hasPermission(Context ctx) {
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            return android.os.Environment.isExternalStorageManager();
        }
        return ctx.checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    /** Abre a tela de 'acesso a todos os arquivos' (pedido UNICA vez). */
    public static void requestPermission(Context ctx) {
        try {
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                ctx.startActivity(new android.content.Intent(
                        android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        android.net.Uri.parse("package:" + ctx.getPackageName())));
            }
        } catch (Exception e) {
            try {
                ctx.startActivity(new android.content.Intent(
                        android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            } catch (Exception ignored) { }
        }
    }

    private static File dir() {
        return Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOWNLOADS);
    }

    @Override
    public void run() {
        if (net == null || !running) return;
        long lastSeq = 0L;
        while (running) {
            try {
                File d = dir();
                File[] files = d == null ? null : d.listFiles();
                if (files != null && files.length > 0) {
                    Arrays.sort(files);
                    for (File f : files) {
                        Matcher m = RE_STATE.matcher(f.getName());
                        if (!m.matches()) continue;
                        long seq = Long.parseLong(m.group(1));
                        if (seq <= lastSeq) {        // velho: limpa
                            //noinspection ResultOfMethodCallIgnored
                            f.delete();
                            continue;
                        }
                        String line = readOneLine(f);
                        //noinspection ResultOfMethodCallIgnored
                        f.delete();                  // consumido
                        lastSeq = seq;
                        if (line == null) continue;
                        String cmd = handle(line);
                        if (cmd != null) {
                            File out = new File(d, "ets2ai-c" + seq + ".txt");
                            FileWriter w = new FileWriter(out, false);
                            w.write(cmd);
                            w.close();
                            answered++;
                        }
                    }
                    // limpa respostas velhas que o PC nao leu (>30 s)
                    long now = System.currentTimeMillis();
                    for (File f : d.listFiles()) {
                        if (f.getName().startsWith("ets2ai-c")
                                && now - f.lastModified() > 30000L) {
                            //noinspection ResultOfMethodCallIgnored
                            f.delete();
                        }
                    }
                }
                long nowMs = System.currentTimeMillis();
                if (hzMark == 0L) hzMark = nowMs;
                hzCount++;
                long dt = nowMs - hzMark;
                if (dt >= 1000L) { hz = hzCount * 1000f / dt; hzCount = 0; hzMark = nowMs; }
                Thread.sleep(60L);
            } catch (InterruptedException e) {
                return;
            } catch (Exception ignored) {
                try { Thread.sleep(200L); } catch (InterruptedException e) { return; }
            }
        }
    }

    private static String readOneLine(File f) {
        try {
            byte[] buf = new byte[(int) Math.min(4096L, f.length() + 1)];
            java.io.FileInputStream in = new java.io.FileInputStream(f);
            int n = in.read(buf);
            in.close();
            if (n <= 0) return null;
            return new String(buf, 0, n, "UTF-8").trim();
        } catch (Exception e) {
            return null;
        }
    }

    /** Mesmo protocolo S -> C do BridgeClient (rede identica). */
    private String handle(String line) {
        if (!line.startsWith("S,")) return null;
        try {
            String[] p = line.split(",");
            float speed = Float.parseFloat(p[1]);
            float offset = Float.parseFloat(p[2]);
            float hdgErr = Float.parseFloat(p[3]);
            float[] curv = { Float.parseFloat(p[4]), Float.parseFloat(p[5]),
                             Float.parseFloat(p[6]), Float.parseFloat(p[7]),
                             Float.parseFloat(p[8]) };
            float limit = Float.parseFloat(p[9]);
            float fuel = Float.parseFloat(p[10]);
            float fatigue = Float.parseFloat(p[11]);
            float jobKm = Float.parseFloat(p[12]);
            float radarDist = p.length > 13 ? Float.parseFloat(p[13]) : 150f;

            float[] f = NeuralNet.features(speed, offset, hdgErr, curv, limit,
                    fuel, fatigue, jobKm, radarDist);
            float[] raw = net.forward(f);
            float[] cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
            return "C," + cmd[0] + "," + cmd[1] + "," + cmd[2];
        } catch (Exception e) {
            return null;
        }
    }
}
