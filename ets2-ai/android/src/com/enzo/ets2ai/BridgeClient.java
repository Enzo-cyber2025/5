package com.enzo.ets2ai;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * TCP bridge client: the PC bridge sends truck state, we run the policy and
 * answer with actuator commands (protocol v1, CSV lines over TCP):
 *
 *   PC -> phone:  S,<speed_mps>,<offset_m>,<hdg_err>,<c1>,<c2>,<c3>,<c4>,<c5>,<limit>,<fuel>,<fatigue>,<job_km>,<t_send_ms>
 *   phone -> PC:  C,<steer>,<throttle>,<brake>,<t_send_ms echo>
 *
 * RTT is computed from the echoed timestamp.
 */
public final class BridgeClient implements Runnable {

    public interface Listener {
        void onStatus(String status);
    }

    private final String host;
    private final int port;
    private final NeuralNet net;
    private final Listener listener;
    private volatile boolean running = true;
    private Socket socket;

    public volatile float lastRttMs = -1f;
    public volatile long answered = 0;

    public BridgeClient(String host, int port, NeuralNet net, Listener listener) {
        this.host = host;
        this.port = port;
        this.net = net;
        this.listener = listener;
    }

    public void stop() {
        running = false;
        try {
            if (socket != null) socket.close();
        } catch (Exception ignored) { }
    }

    @Override
    public void run() {
        post("conectando a " + host + ":" + port + " ...");
        while (running) {
            try {
                socket = new Socket();
                socket.connect(new InetSocketAddress(host, port), 4000);
                socket.setTcpNoDelay(true);
                post("CONECTADO " + host + ":" + port);
                BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), "UTF-8"));
                OutputStream out = socket.getOutputStream();
                String line;
                while (running && (line = in.readLine()) != null) {
                    String resp = handle(line);
                    if (resp != null) {
                        out.write((resp + "\n").getBytes("UTF-8"));
                        out.flush();
                    }
                }
                post("desconectado (bridge caiu)");
            } catch (Exception e) {
                post("erro: " + e.getClass().getSimpleName() + " — tentando de novo em 3 s");
            }
            try {
                if (running) Thread.sleep(3000);
            } catch (InterruptedException ignored) {
                return;
            }
        }
    }

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
            long tSend = Long.parseLong(p[13]);

            float[] f = NeuralNet.features(speed, offset, hdgErr, curv, limit, fuel, fatigue, jobKm);
            float[] raw = net.forward(f);
            float[] cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
            answered++;
            lastRttMs = System.currentTimeMillis() - tSend;
            return "C," + cmd[0] + "," + cmd[1] + "," + cmd[2] + "," + tSend;
        } catch (Exception e) {
            return null;
        }
    }

    private void post(final String s) {
        final Listener l = listener;
        if (l != null) l.onStatus(s);
    }
}
