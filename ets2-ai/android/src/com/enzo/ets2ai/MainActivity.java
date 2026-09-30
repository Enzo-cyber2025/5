package com.enzo.ets2ai;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.Locale;

/**
 * ETS2-AI demo: the trained policy (pure-Java inference) drives a truck
 * through random roads with career rules (fuel, sleep, jobs, money).
 *
 * Buttons: IA on/off (manual touch driving when off), ROTA (new route),
 * VEL (sim speed x1/x2/x4), BRIDGE (connect to the Windows bridge),
 * NPU (hardware diagnostics for this phone).
 */
public final class MainActivity extends Activity {

    private GameView game;
    private TextView status;
    private NeuralNet net;
    private BridgeClient bridge;
    private String bridgeStatus = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        try {
            net = NeuralNet.fromAssets(getAssets(), "model-weights.txt");
        } catch (Exception e) {
            net = null;
        }
        game = new GameView(this, net);

        FrameLayout root = new FrameLayout(this);
        root.addView(game, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setShadowLayer(4, 0, 0, Color.BLACK);
        status.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        status.setTextSize(13);
        status.setPadding(12, 8, 12, 8);
        root.addView(status, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.START));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER);
        bar.setBackgroundColor(0x66000000);
        bar.addView(button("IA", new Runnable() {
            public void run() { game.world.aiEnabled = !game.world.aiEnabled; }
        }));
        bar.addView(button("ROTA", new Runnable() {
            public void run() { game.world.newRoute(); }
        }));
        bar.addView(button("VEL", new Runnable() {
            public void run() { game.cycleSpeed(); }
        }));
        bar.addView(button("BRIDGE", new Runnable() {
            public void run() { showBridgeDialog(); }
        }));
        bar.addView(button("NPU", new Runnable() {
            public void run() { showNpuDialog(); }
        }));
        root.addView(bar, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM));

        setContentView(root);
    }

    private Button button(String label, final Runnable r) {
        Button b = new Button(this);
        b.setText(label);
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { r.run(); }
        });
        return b;
    }

    private void showBridgeDialog() {
        if (bridge != null) {
            bridge.stop();
            bridge = null;
            bridgeStatus = "bridge desconectado";
            return;
        }
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        final EditText host = new EditText(this);
        host.setHint("IP do PC (ex.: 192.168.1.10)");
        host.setInputType(InputType.TYPE_CLASS_TEXT);
        final EditText port = new EditText(this);
        port.setHint("porta (padrao 7777)");
        port.setInputType(InputType.TYPE_CLASS_NUMBER);
        port.setText("7777");
        box.addView(host);
        box.addView(port);
        new AlertDialog.Builder(this)
                .setTitle("Conectar ao bridge do PC")
                .setMessage("No PC rode: ETS2-AI-bridge.exe (ou ets2_bridge.py). "
                        + "O app recebe o estado e devolve os comandos da IA.")
                .setView(box)
                .setPositiveButton("Conectar", new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int w) {
                        String h = host.getText().toString().trim();
                        int p = 7777;
                        try { p = Integer.parseInt(port.getText().toString().trim()); } catch (Exception ignored) { }
                        if (h.length() == 0) return;
                        if (net == null) return;
                        bridge = new BridgeClient(h, p, net, new BridgeClient.Listener() {
                            public void onStatus(final String s) {
                                runOnUiThread(new Runnable() {
                                    public void run() { bridgeStatus = s; }
                                });
                            }
                        });
                        new Thread(bridge).start();
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showNpuDialog() {
        ScrollView sc = new ScrollView(this);
        TextView tv = new TextView(this);
        tv.setText(NpuProbe.report(this));
        tv.setPadding(24, 16, 24, 16);
        tv.setTypeface(Typeface.MONOSPACE);
        tv.setTextSize(12);
        sc.addView(tv);
        new AlertDialog.Builder(this)
                .setTitle("Diagnostico NPU / hardware")
                .setView(sc)
                .setPositiveButton("Fechar", null)
                .show();
    }

    void setStatus(final String s) {
        runOnUiThread(new Runnable() {
            public void run() { status.setText(s); }
        });
    }

    // ------------------------------------------------------------------

    final class GameView extends SurfaceView implements SurfaceHolder.Callback, Runnable {
        private Thread thread;
        private volatile boolean alive;
        final SimWorld world = new SimWorld();
        private final NeuralNet net;
        private final Paint roadPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint edgePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint centerPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint trailerPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint cabPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint hudPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint barBg = new Paint();
        private final Paint barFg = new Paint();
        private final float scale = 6f;    // px per metre
        private int speedMult = 1;
        private float manualSteer, manualThrottle, manualBrake;
        private long lastNs;

        GameView(Context ctx, NeuralNet net) {
            super(ctx);
            this.net = net;
            getHolder().addCallback(this);
            roadPaint.setColor(0xFF3A3A44);
            roadPaint.setStyle(Paint.Style.STROKE);
            roadPaint.setStrokeWidth(9f * scale);
            roadPaint.setStrokeCap(Paint.Cap.ROUND);
            edgePaint.setColor(0xFFE8E8E8);
            edgePaint.setStyle(Paint.Style.STROKE);
            edgePaint.setStrokeWidth(0.35f * scale);
            centerPaint.setColor(0xFFF2C14E);
            centerPaint.setStyle(Paint.Style.STROKE);
            centerPaint.setStrokeWidth(0.25f * scale);
            centerPaint.setPathEffect(new DashPathEffect(new float[] { 4f * scale, 4f * scale }, 0));
            trailerPaint.setColor(0xFFD0D6DE);
            cabPaint.setColor(0xFF2F7BFF);
            hudPaint.setColor(Color.WHITE);
            hudPaint.setTypeface(Typeface.MONOSPACE);
            hudPaint.setTextSize(14);
            barBg.setColor(0x66000000);
        }

        void cycleSpeed() {
            speedMult = speedMult == 1 ? 2 : speedMult == 2 ? 4 : 1;
        }

        @Override public void surfaceCreated(SurfaceHolder h) {
            alive = true;
            thread = new Thread(this);
            thread.start();
        }

        @Override public void surfaceDestroyed(SurfaceHolder h) {
            alive = false;
            if (thread != null) {
                try { thread.join(500); } catch (InterruptedException ignored) { }
            }
        }

        @Override public void surfaceChanged(SurfaceHolder h, int f, int w, int ht) { }

        @Override
        public boolean onTouchEvent(MotionEvent ev) {
            if (world.aiEnabled) return false;
            manualSteer = manualThrottle = manualBrake = 0f;
            for (int i = 0; i < ev.getPointerCount(); i++) {
                float x = ev.getX(i);
                if (ev.getActionMasked() == MotionEvent.ACTION_POINTER_UP
                        && ev.getActionIndex() == i) continue;
                float w = getWidth();
                if (x < w / 3f) manualSteer = -1f;              // esquerda
                else if (x < 2f * w / 3f) manualBrake = 1f;     // meio = freio
                else manualSteer = 1f;                          // direita
                manualThrottle = manualBrake > 0f ? 0f : 0.65f; // cruise
            }
            return true;
        }

        @Override
        public void run() {
            lastNs = System.nanoTime();
            while (alive) {
                long now = System.nanoTime();
                float dtReal = (now - lastNs) / 1e9f;
                lastNs = now;
                if (dtReal > 0.25f) dtReal = 0.25f;
                for (int k = 0; k < speedMult; k++) {
                    stepWorld(dtReal);
                }
                render();
                try { Thread.sleep(16); } catch (InterruptedException ignored) { }
            }
        }

        private void stepWorld(float dtReal) {
            // fixed 10 Hz physics, accumulated real time
            acc += dtReal;
            while (acc >= SimWorld.DT) {
                acc -= SimWorld.DT;
                float[] cmd;
                if (world.aiEnabled && net != null) {
                    float[] f = NeuralNet.features(
                            world.truck.speed, world.truck.offset, world.headingError(),
                            world.curvAhead(), SimWorld.SPEED_LIMIT,
                            world.truck.fuel, world.truck.fatigue, world.jobLeftKm());
                    float[] raw = net.forward(f);
                    cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
                } else {
                    cmd = NeuralNet.clampAction(manualSteer, manualThrottle, manualBrake);
                }
                world.step(cmd);
            }
        }

        private float acc;

        private void render() {
            SurfaceHolder h = getHolder();
            Canvas c = h.lockCanvas();
            if (c == null) return;
            try {
                int cw = c.getWidth(), ch = c.getHeight();
                c.drawColor(0xFF1C4E28);                       // grama
                SimWorld.Road road = world.road;
                SimWorld.Truck t = world.truck;

                c.save();
                c.translate(cw / 2f, ch * 0.62f);
                float deg = (float) Math.toDegrees(-Math.PI / 2 - t.heading);
                c.rotate(deg);
                c.translate(-t.x, -t.y);

                // road ribbon around the truck
                int i0 = Math.max(0, t.hint - 60);
                int i1 = Math.min(road.sx.length - 1, t.hint + 140);
                drawPoly(c, roadPaint, road, i0, i1, 0f);
                drawPoly(c, edgePaint, road, i0, i1, -4.5f);
                drawPoly(c, edgePaint, road, i0, i1, 4.5f);
                drawPoly(c, centerPaint, road, i0, i1, 0f);

                // truck: trailer + cab (local coords, heading up)
                c.save();
                c.translate(t.x, t.y);
                c.rotate((float) Math.toDegrees(t.heading));
                c.drawRect(-1.3f * scale, -2f * scale, 1.3f * scale, 11f * scale, trailerPaint);
                c.drawRect(-1.3f * scale, -4.5f * scale, 1.3f * scale, -1.9f * scale, cabPaint);
                c.restore();
                c.restore();

                drawHud(c, cw, ch);
            } finally {
                h.unlockCanvasAndPost(c);
            }
        }

        private void drawPoly(Canvas c, Paint p, SimWorld.Road road, int i0, int i1, float lateral) {
            // build path along the samples, offset laterally if needed
            android.graphics.Path path = new android.graphics.Path();
            boolean first = true;
            for (int i = i0; i <= i1; i += 2) {
                int a = Math.max(0, i - 1), b = Math.min(road.sx.length - 1, i + 1);
                float tx = road.sx[b] - road.sx[a], ty = road.sy[b] - road.sy[a];
                float tn = (float) Math.hypot(tx, ty);
                if (tn < 0.0001f) { tx = 1; ty = 0; tn = 1; }
                float nx = -ty / tn * lateral, ny = tx / tn * lateral;
                float x = road.sx[i] + nx, y = road.sy[i] + ny;
                if (first) { path.moveTo(x, y); first = false; }
                else path.lineTo(x, y);
            }
            c.drawPath(path, p);
        }

        private void drawHud(Canvas c, int cw, int ch) {
            SimWorld.Truck t = world.truck;
            String src = world.aiEnabled ? "IA" : "MANUAL";
            if (bridge != null) {
                src += String.format(Locale.US, " | BRIDGE RTT %.0f ms (%d cmds)",
                        bridge.lastRttMs, bridge.answered);
            }
            String line = String.format(Locale.US,
                    "FONTE: %s | %d km/h | faixa %.0f%% | EUR %.0f | entrega %.1f km | rota %.1f km%s",
                    src, Math.round(t.speed * 3.6f), world.inLanePct * 100f, t.money,
                    world.jobLeftKm(), roadKm(), world.crashed ? " | BATER!" : "");
            setStatus(line);

            // fuel / fatigue bars (right edge)
            float bw = 26f, bh = ch * 0.35f, bx = cw - bw - 14f, by = 40f;
            c.drawRect(bx, by, bx + bw, by + bh, barBg);
            barFg.setColor(t.fuel < SimWorld.REFUEL_BELOW + 0.08f ? 0xFFFF5252 : 0xFF7ED957);
            c.drawRect(bx, by + bh * (1f - t.fuel), bx + bw, by + bh, barFg);
            c.drawRect(bx + bw + 6f, by, bx + bw + 6f + 20f, by + bh, barBg);
            barFg.setColor(t.fatigue > 0.7f ? 0xFFFF5252 : 0xFFFFC24B);
            c.drawRect(bx + bw + 6f, by + bh * (1f - t.fatigue), bx + bw + 6f + 20f, by + bh, barFg);
            c.save();
            c.rotate(-90f, bx - 6f, by + bh);
            c.drawText("COMB", bx - 6f, by + bh, hudPaint);
            c.restore();

            // event / crash overlay
            if (world.eventTimer > 0f || world.crashed || world.eventText.length() > 0) {
                if (world.eventTimer > 0f || world.crashed) {
                    hudPaint.setTextAlign(Paint.Align.CENTER);
                    c.drawText(world.crashed ? "BATER! Toque ROTA para recomecar"
                            : world.eventText, cw / 2f, ch * 0.25f, hudPaint);
                    hudPaint.setTextAlign(Paint.Align.LEFT);
                }
            }
            if (bridgeStatus.length() > 0) {
                c.drawText(bridgeStatus, 12f, ch - 120f, hudPaint);
            }
        }

        private float roadKm() {
            return world.road.length / 1000f;
        }
    }
}
