package com.enzo.ets2ai;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * Ponte PC -> APK por ARQUIVOS (cabo USB em modo "Transferir arquivos"/MTP).
 *
 * O PC escreve estado.txt (estado do caminhao, protocolo S + seq) na
 * memoria do celular; nos rodamos a IA AQUI (mesma rede do BridgeClient)
 * e escrevemos comando.txt de volta. SEM porta TCP, SEM Depuracao USB,
 * SEM internet — o unico canal e o proprio cabo.
 *
 *   estado.txt  (PC  -> APK): S,&lt;seq&gt;,speed,offset,hdg,c1..c5,limit,fuel,fatigue,job_km,radar
 *   comando.txt (APK -> PC) : C,&lt;seq&gt;,steer,throttle,brake
 */
public final class FileBridge implements Runnable {

    public interface Listener {
        void onStatus(String status);
    }

    private final NeuralNet net;
    private final Listener listener;
    private final Context ctx;
    private volatile boolean running = true;

    public volatile long answered = 0;
    public volatile float hz = 0f;
    private long hzMark = 0L;
    private int hzCount = 0;
    private long lastSeq = -1;
    private long lastMark = 0L;
    private File lastDir = null;

    public FileBridge(Context ctx, NeuralNet net, Listener listener) {
        this.ctx = ctx;
        this.net = net;
        this.listener = listener;
    }

    public void stop() {
        running = false;
    }

    /** Pastas vigiadas: a especifica do app (sem permissao) e a raiz
     *  /sdcard/ETS2AI (se o aparelho permitir). O PC escreve em qualquer
     *  uma das duas; usamos a que tiver atividade. */
    private List<File> dirs() {
        List<File> out = new ArrayList<File>();
        try {
            File d = ctx.getExternalFilesDir("bridge");
            if (d != null) {
                d.mkdirs();
                out.add(d);
            }
        } catch (Exception ignored) { }
        try {
            File root = new File("/sdcard/ETS2AI");
            if (!root.exists()) root.mkdirs();
            if (root.canWrite()) out.add(root);
        } catch (Exception ignored) { }
        return out;
    }

    @Override
    public void run() {
        post("arquivo: aguardando o PC (cabo USB)...");
        while (running) {
            boolean did = false;
            for (File d : dirs()) {
                File st = new File(d, "estado.txt");
                if (!st.exists()) continue;
                long m = st.lastModified();
                if (m == lastMark && d == lastDir) continue;
                String line = readText(st);
                if (line == null) continue;
                lastMark = m;
                lastDir = d;
                String resp = handle(line, d);
                if (resp != null) {
                    writeText(new File(d, "comando.txt"), resp);
                    did = true;
                }
            }
            if (!did) {
                try { Thread.sleep(120); } catch (InterruptedException e) {
                    return;
                }
            }
        }
        post("arquivo: ponte encerrada");
    }

    private String handle(String line, File dir) {
        if (!line.startsWith("S,")) return null;
        try {
            String[] p = line.split(",");
            long seq = Long.parseLong(p[1]);
            if (seq == lastSeq) return null;          // ja respondido
            lastSeq = seq;
            float speed = Float.parseFloat(p[2]);
            float offset = Float.parseFloat(p[3]);
            float hdgErr = Float.parseFloat(p[4]);
            float[] curv = { Float.parseFloat(p[5]), Float.parseFloat(p[6]),
                             Float.parseFloat(p[7]), Float.parseFloat(p[8]),
                             Float.parseFloat(p[9]) };
            float limit = Float.parseFloat(p[10]);
            float fuel = Float.parseFloat(p[11]);
            float fatigue = Float.parseFloat(p[12]);
            float jobKm = Float.parseFloat(p[13]);

            float[] f = NeuralNet.features(speed, offset, hdgErr, curv, limit,
                    fuel, fatigue, jobKm, 150f);
            float[] raw = net.forward(f);
            float[] cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
            answered++;
            long nowMs = System.currentTimeMillis();
            if (hzMark == 0L) hzMark = nowMs;
            hzCount++;
            long dtHz = nowMs - hzMark;
            if (dtHz >= 1000L) {
                hz = hzCount * 1000f / dtHz;
                hzCount = 0;
                hzMark = nowMs;
            }
            return "C," + seq + "," + cmd[0] + "," + cmd[1] + "," + cmd[2];
        } catch (Exception e) {
            return null;
        }
    }

    private String readText(File f) {
        try {
            InputStream in = new FileInputStream(f);
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[512];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();
            return new String(bo.toByteArray(), StandardCharsets.UTF_8).trim();
        } catch (Exception e) {
            return null;
        }
    }

    private void writeText(File f, String text) {
        try {
            FileOutputStream out = new FileOutputStream(f);
            out.write((text + "\n").getBytes(StandardCharsets.UTF_8));
            out.close();
        } catch (Exception ignored) { }
    }

    private void post(final String s) {
        final Listener l = listener;
        if (l != null) l.onStatus(s);
    }
}
