package com.enzo.ets2ai;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
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
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import android.Manifest;
import android.content.pm.PackageManager;

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
    private InferenceEngine.Net engine;
    private String engineName = "Java CPU";
    private TextView engineChip;
    private BridgeClient bridge;
    private String bridgeStatus = "";
    private BtKeyboard btKeyboard;
    private String btStatus = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(0xFF101018);
        getWindow().setNavigationBarColor(0xFF101018);
        try {
            net = NeuralNet.fromStream(getAssets().open("model-weights.txt"));
        } catch (Exception e) {
            net = null;
        }
        game = new GameView(this, net);
        if (net != null) {
            new Thread(new Runnable() {
                public void run() {
                    final InferenceEngine.Net e = InferenceEngine.create(MainActivity.this, net);
                    runOnUiThread(new Runnable() {
                        public void run() {
                            engine = e;
                            engineName = e.name();
                            engineChip.setText(engineName);
                        }
                    });
                }
            }).start();
        }

        FrameLayout root = new FrameLayout(this);
        root.addView(game, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable panelBg = new GradientDrawable();
        panelBg.setColor(0xCC16161F);
        panelBg.setCornerRadius(18f);
        panel.setBackgroundDrawable(panelBg);
        panel.setPadding(16, 10, 16, 12);

        LinearLayout titleRow = new LinearLayout(this);
        titleRow.setOrientation(LinearLayout.HORIZONTAL);
        TextView title = new TextView(this);
        title.setText("ETS2-AI");
        title.setTextColor(Color.WHITE);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextSize(15);
        titleRow.addView(title);
        titleRow.addView(chip("OFFLINE", 0xFF00A884));
        engineChip = chip(engineName, 0xFF2F7BFF);
        titleRow.addView(engineChip);
        panel.addView(titleRow);

        status = new TextView(this);
        status.setTextColor(0xFFE6E6F0);
        status.setTypeface(Typeface.MONOSPACE);
        status.setTextSize(11);
        status.setPadding(0, 8, 0, 0);
        panel.addView(status);

        FrameLayout.LayoutParams plp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.START);
        plp.setMargins(12, 12, 12, 12);
        root.addView(panel, plp);

        HorizontalScrollView scroll = new HorizontalScrollView(this);
        scroll.setHorizontalScrollBarEnabled(false);
        scroll.setBackgroundColor(0x88101420);
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(10, 8, 10, 10);
        scroll.addView(bar);
        bar.addView(styledButton("IA", 0xFF2F7BFF, new Runnable() {
            public void run() { game.world.aiEnabled = !game.world.aiEnabled; }
        }));
        bar.addView(styledButton("ROTA", 0xFF00A884, new Runnable() {
            public void run() { game.world.newRoute(); }
        }));
        bar.addView(styledButton("VEL", 0xFFF2A93B, new Runnable() {
            public void run() { game.cycleSpeed(); }
        }));
        bar.addView(styledButton("BRIDGE", 0xFF8E5BF2, new Runnable() {
            public void run() { showBridgeDialog(); }
        }));
        bar.addView(styledButton("NPU", 0xFFE85D75, new Runnable() {
            public void run() { showNpuDialog(); }
        }));
        bar.addView(styledButton("BACKEND", 0xFF3AA8C1, new Runnable() {
            public void run() { showBackendDialog(); }
        }));
        bar.addView(styledButton("TECLADO BT", 0xFF5B6B8C, new Runnable() {
            public void run() { showBtDialog(); }
        }));
        root.addView(scroll, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM));

        setContentView(root);
    }

    private TextView chip(String text, int color) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextColor(Color.WHITE);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setTextSize(9);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(10f);
        t.setBackgroundDrawable(bg);
        t.setPadding(14, 4, 14, 4);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(10, 0, 0, 0);
        lp.gravity = Gravity.CENTER_VERTICAL;
        t.setLayoutParams(lp);
        return t;
    }

    private Button styledButton(String label, int color, final Runnable r) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextColor(Color.WHITE);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setTextSize(12);
        b.setAllCaps(false);
        b.setPadding(28, 12, 28, 12);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(22f);
        b.setBackgroundDrawable(bg);
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { r.run(); }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(6, 0, 6, 0);
        b.setLayoutParams(lp);
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
                .setNeutralButton("AUTO (USB/Wi-Fi)", new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int w) {
                        autoConnectBridge();
                    }
                })
                .show();
    }

    /** Procura o PC sozinho: sub-redes do aparelho + faixas tipicas de
     *  ancoragem USB (tethering). Cabo USB + 'Ancoragem USB' ligada = rede. */
    private void autoConnectBridge() {
        if (net == null) return;
        if (bridge != null) { bridge.stop(); bridge = null; }
        bridgeStatus = "AUTO: procurando o PC (USB/Wi-Fi)...";
        new Thread(new Runnable() {
            public void run() {
                List<String> prefixes = new ArrayList<String>();
                try {
                    Enumeration<NetworkInterface> nis = NetworkInterface.getNetworkInterfaces();
                    while (nis.hasMoreElements()) {
                        NetworkInterface ni = nis.nextElement();
                        for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses()) {
                            String ip = ia.getAddress().getHostAddress();
                            if (ip != null && ip.contains("."))
                                prefixes.add(ip.substring(0, ip.lastIndexOf('.')));
                        }
                    }
                } catch (Exception ignored) { }
                String[] tether = { "192.168.42", "192.168.43", "192.168.44",
                                    "192.168.45", "192.168.46" };
                for (String t : tether) if (!prefixes.contains(t)) prefixes.add(t);

                ExecutorService pool = Executors.newFixedThreadPool(24);
                List<Future<String>> futures = new ArrayList<Future<String>>();
                for (final String pre : prefixes) {
                    for (int i = 1; i <= 254; i++) {
                        final String host = pre + "." + i;
                        futures.add(pool.submit(new java.util.concurrent.Callable<String>() {
                            public String call() {
                                try {
                                    Socket sk = new Socket();
                                    sk.connect(new InetSocketAddress(host, 7777), 150);
                                    sk.close();
                                    return host;
                                } catch (Exception e) { return null; }
                            }
                        }));
                    }
                }
                String found = null;
                try {
                    for (Future<String> f : futures) {
                        String h = f.get();
                        if (h != null) { found = h; break; }
                    }
                } catch (Exception ignored) { }
                pool.shutdownNow();
                final String host = found;
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (host == null) {
                            bridgeStatus = "AUTO: PC nao encontrado — confira o bridge "
                                    + "e a 'Ancoragem USB'";
                            return;
                        }
                        bridgeStatus = "AUTO: PC encontrado em " + host + "!";
                        bridge = new BridgeClient(host, 7777, net, new BridgeClient.Listener() {
                            public void onStatus(final String st) {
                                runOnUiThread(new Runnable() {
                                    public void run() { bridgeStatus = st; }
                                });
                            }
                        });
                        new Thread(bridge).start();
                    }
                });
            }
        }).start();
    }

    private void showBtDialog() {
        if (!BtKeyboard.supported()) {
            btStatus = "Android < 9: HID indisponivel";
            return;
        }
        if (btKeyboard != null) {
            btKeyboard.stop();
            btKeyboard = null;
            btStatus = "teclado BT desligado";
            return;
        }
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.BLUETOOTH_CONNECT }, 41);
            btStatus = "permissao Bluetooth pedida; toque TECLADO BT de novo";
            return;
        }
        btKeyboard = new BtKeyboard(new BtKeyboard.Listener() {
            public void onStatus(final String s) {
                runOnUiThread(new Runnable() { public void run() { btStatus = "BT: " + s; } });
            }
        });
        btKeyboard.start(this);
        // lista de aparelhos ja pareados (o PC precisa estar pareado)
        final java.util.Set<android.bluetooth.BluetoothDevice> bonded =
                android.bluetooth.BluetoothAdapter.getDefaultAdapter().getBondedDevices();
        final String[] names = new String[bonded.size()];
        final android.bluetooth.BluetoothDevice[] devs = bonded.toArray(
                new android.bluetooth.BluetoothDevice[0]);
        for (int i = 0; i < devs.length; i++) names[i] = devs[i].getName();
        if (devs.length == 0) {
            btStatus = "BT: nenhum aparelho pareado — pareie o PC nas configuracoes";
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Conectar teclado a qual aparelho?")
                .setItems(names, new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int w) {
                        btKeyboard.connect(devs[w]);
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showBackendDialog() {
        if (net == null) return;
        Backends.benchmark(this, net, new Backends.Report() {
            public void done(final String text) {
                runOnUiThread(new Runnable() {
                    public void run() {
                        ScrollView sc = new ScrollView(MainActivity.this);
                        TextView tv = new TextView(MainActivity.this);
                        tv.setText(text);
                        tv.setPadding(24, 16, 24, 16);
                        tv.setTypeface(Typeface.MONOSPACE);
                        tv.setTextSize(11);
                        sc.addView(tv);
                        new AlertDialog.Builder(MainActivity.this)
                                .setTitle("Backends medidos neste aparelho")
                                .setView(sc)
                                .setPositiveButton("Fechar", null)
                                .show();
                    }
                });
            }
        });
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
        private final InferenceEngine.Net javaNetHolder;
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
        private final Paint skyPaint = new Paint();
        private final Paint grassPaint = new Paint();
        private final Paint hillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint wearPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint dockA = new Paint();
        private final Paint dockB = new Paint();
        private final Paint wheelPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint glassPaint = new Paint();
        private final Paint trailerBorder = new Paint();
        private final Paint panelPaint = new Paint();
        private final Paint bannerBg = new Paint();
        private final Paint bigText = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint barLabel = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF panelRect = new RectF();
        private final RectF barRect = new RectF();
        private int shaderW = -1, shaderH = -1;
        private final float scale = 6f;    // px per metre
        private int speedMult = 1;
        private float manualSteer, manualThrottle, manualBrake;
        private long lastNs;

        GameView(Context ctx, NeuralNet net) {
            super(ctx);
            this.net = net;
            javaNetHolder = new InferenceEngine.JavaNet(net);
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
            hillPaint.setColor(0xFF24463A);
            hillPaint.setStyle(Paint.Style.FILL);
            wearPaint.setColor(0xFF55555F);
            wearPaint.setStyle(Paint.Style.STROKE);
            wearPaint.setStrokeWidth(1f * scale);
            wearPaint.setPathEffect(new DashPathEffect(new float[] { 3f * scale, 12f * scale }, 0));
            dockA.setColor(0xFFF5F5F5);
            dockB.setColor(0xFF1A1A22);
            wheelPaint.setColor(0xFF14141C);
            glassPaint.setColor(0xFFBFE3FF);
            trailerBorder.setColor(0xFF8A93A3);
            panelPaint.setColor(0x99101420);
            bannerBg.setColor(0xCC1E1E28);
            bigText.setColor(Color.WHITE);
            bigText.setTypeface(Typeface.DEFAULT_BOLD);
            barLabel.setColor(0xFFB9B9C9);
            barLabel.setTypeface(Typeface.DEFAULT_BOLD);
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
                            world.truck.fuel, world.truck.fatigue, world.jobLeftKm(),
                            world.radarDist());
                    InferenceEngine.Net eng = engine != null ? engine : javaNetHolder;
                    float[] raw = eng.forward(f);
                    cmd = NeuralNet.clampAction(raw[0], raw[1], raw[2]);
                } else {
                    cmd = NeuralNet.clampAction(manualSteer, manualThrottle, manualBrake);
                }
                cmd = SimWorld.governor(world.road, world.truck, cmd);
                if (btKeyboard != null) {
                    btKeyboard.update(cmd[0], cmd[1], cmd[2]);   // teclas reais via BT
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
                // ceu e grama com gradiente (shaders em cache por tamanho)
                if (shaderW != cw || shaderH != ch) {
                    shaderW = cw;
                    shaderH = ch;
                    skyPaint.setShader(new LinearGradient(0, 0, 0, ch * 0.5f,
                            0xFF101B2D, 0xFF2E5A46, Shader.TileMode.CLAMP));
                    grassPaint.setShader(new LinearGradient(0, ch * 0.45f, 0, ch,
                            0xFF2E5A46, 0xFF1C4E28, Shader.TileMode.CLAMP));
                }
                c.drawRect(0, 0, cw, ch * 0.5f, skyPaint);
                c.drawCircle(cw * 0.15f, ch * 0.45f, ch * 0.10f, hillPaint);
                c.drawCircle(cw * 0.55f, ch * 0.45f, ch * 0.15f, hillPaint);
                c.drawCircle(cw * 0.92f, ch * 0.45f, ch * 0.08f, hillPaint);
                c.drawRect(0, ch * 0.45f, cw, ch, grassPaint);
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
                drawPoly(c, wearPaint, road, i0, i1, 0f);
                drawPoly(c, edgePaint, road, i0, i1, -4.5f);
                drawPoly(c, edgePaint, road, i0, i1, 4.5f);
                drawPoly(c, centerPaint, road, i0, i1, 0f);

                // dock: faixa quadriculada no fim da rota
                float dockS = road.length - 6f;
                if (dockS < t.s + 240f) {
                    int di = Math.min(road.ss.length - 1, Math.max(0, (int) (dockS / 2f)));
                    int d0 = Math.max(0, di - 1), d1 = Math.min(road.sx.length - 1, di + 1);
                    float dtx = road.sx[d1] - road.sx[d0], dty = road.sy[d1] - road.sy[d0];
                    float dtn = (float) Math.hypot(dtx, dty);
                    if (dtn < 0.0001f) { dtx = 1; dty = 0; dtn = 1; }
                    float nx = -dty / dtn, ny = dtx / dtn;
                    float ux = dtx / dtn, uy = dty / dtn;
                    for (int row = 0; row < 2; row++) {
                        for (int k = 0; k < 12; k++) {
                            float off = -4.6f + (k + 0.5f) * (9.2f / 12f);
                            float along = row * 0.9f - 0.9f;
                            float px = road.sx[di] + nx * off + ux * along;
                            float py = road.sy[di] + ny * off + uy * along;
                            Paint dp = ((row + k) % 2 == 0) ? dockA : dockB;
                            c.drawRect(px - 0.45f * scale, py - 0.45f * scale,
                                    px + 0.45f * scale, py + 0.45f * scale, dp);
                        }
                    }
                }

                // speed cameras ahead (radar markers)
                Paint camPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
                camPaint.setColor(0xFFFFD54F);
                for (float rs : road.radars) {
                    if (rs > t.s - 30f && rs < t.s + 220f) {
                        int ri = Math.min(road.ss.length - 1,
                                Math.max(0, (int) (rs / 2f)));
                        float rx = road.sx[ri], ry = road.sy[ri];
                        int r0 = Math.max(0, ri - 1), r1 = Math.min(road.sx.length - 1, ri + 1);
                        float rth = (float) Math.atan2(road.sy[r1] - road.sy[r0],
                                road.sx[r1] - road.sx[r0]);
                        float mx = rx - (float) Math.sin(rth) * 7.5f;
                        float my = ry + (float) Math.cos(rth) * 7.5f;
                        c.drawRect(mx - 3f * scale / 2, my - 3f * scale / 2,
                                mx + 3f * scale / 2, my + 3f * scale / 2, camPaint);
                    }
                }

                // truck: rodas, bau com borda, cabine e para-brisa
                c.save();
                c.translate(t.x, t.y);
                c.rotate((float) Math.toDegrees(t.heading));
                c.drawCircle(-0.95f * scale, -3.3f * scale, 0.45f * scale, wheelPaint);
                c.drawCircle(0.95f * scale, -3.3f * scale, 0.45f * scale, wheelPaint);
                c.drawCircle(-0.95f * scale, 4.6f * scale, 0.5f * scale, wheelPaint);
                c.drawCircle(0.95f * scale, 4.6f * scale, 0.5f * scale, wheelPaint);
                c.drawCircle(-0.95f * scale, 7.2f * scale, 0.5f * scale, wheelPaint);
                c.drawCircle(0.95f * scale, 7.2f * scale, 0.5f * scale, wheelPaint);
                c.drawRect(-1.4f * scale, -2.1f * scale, 1.4f * scale, 11.1f * scale, trailerBorder);
                c.drawRect(-1.3f * scale, -2f * scale, 1.3f * scale, 11f * scale, trailerPaint);
                c.drawRect(-1.3f * scale, -4.5f * scale, 1.3f * scale, -1.9f * scale, cabPaint);
                c.drawRect(-1.05f * scale, -4.1f * scale, 1.05f * scale, -3.1f * scale, glassPaint);
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
            String src = (world.aiEnabled ? "IA/" + engineName : "MANUAL");
            if (bridge != null) {
                src += String.format(Locale.US, " | BRIDGE RTT %.0f ms (%d cmds)",
                        bridge.lastRttMs, bridge.answered);
            }
            String line = String.format(Locale.US,
                    "%s | faixa %.0f%% | EUR %.0f | jobs %d | entrega %.1f km%s",
                    src, world.inLanePct * 100f, t.money, world.jobsDone,
                    world.jobLeftKm(), world.crashed ? " | BATER!" : "");
            setStatus(line);

            // painel de velocidade (topo direita)
            panelRect.set(cw - 150f, 16f, cw - 20f, 100f);
            c.drawRoundRect(panelRect, 16f, 16f, panelPaint);
            bigText.setTextSize(34f);
            bigText.setTextAlign(Paint.Align.CENTER);
            c.drawText(String.valueOf(Math.round(t.speed * 3.6f)), cw - 85f, 64f, bigText);
            hudPaint.setTextAlign(Paint.Align.CENTER);
            hudPaint.setTextSize(11f);
            c.drawText("km/h", cw - 85f, 88f, hudPaint);
            hudPaint.setTextAlign(Paint.Align.LEFT);
            hudPaint.setTextSize(14f);

            // barras de combustivel e sono
            barLabel.setTextSize(9f);
            barLabel.setTextAlign(Paint.Align.CENTER);
            drawBarH(c, cw - 150f, 112f, 60f, "COMB", t.fuel,
                    t.fuel < SimWorld.REFUEL_BELOW + 0.08f ? 0xFFFF5252 : 0xFF7ED957);
            drawBarH(c, cw - 78f, 112f, 60f, "SONO", t.fatigue,
                    t.fatigue > 0.7f ? 0xFFFF5252 : 0xFFFFC24B);
            barLabel.setTextAlign(Paint.Align.LEFT);

            // banner de evento
            String banner = world.crashed ? "BATER! Toque ROTA para recomecar"
                    : (world.eventTimer > 0f ? world.eventText : "");
            if (banner.length() > 0) {
                panelRect.set(cw / 2f - 230f, ch * 0.18f, cw / 2f + 230f, ch * 0.18f + 40f);
                bannerBg.setColor(world.crashed ? 0xCC5A1F27 : 0xCC1E1E28);
                c.drawRoundRect(panelRect, 14f, 14f, bannerBg);
                hudPaint.setTextAlign(Paint.Align.CENTER);
                c.drawText(banner, cw / 2f, ch * 0.18f + 26f, hudPaint);
                hudPaint.setTextAlign(Paint.Align.LEFT);
            }
            if (bridgeStatus.length() > 0) {
                c.drawText(bridgeStatus, 14f, ch - 150f, hudPaint);
            }
            if (btStatus.length() > 0) {
                c.drawText(btStatus, 14f, ch - 130f, hudPaint);
            }
        }

        private void drawBarH(Canvas c, float x, float y, float w, String label,
                              float frac, int color) {
            barRect.set(x, y, x + w, y + 8f);
            c.drawRoundRect(barRect, 4f, 4f, barBg);
            barFg.setColor(color);
            barRect.set(x, y, x + w * Math.max(0f, Math.min(1f, frac)), y + 8f);
            c.drawRoundRect(barRect, 4f, 4f, barFg);
            c.drawText(label, x + w / 2f, y + 22f, barLabel);
        }

        private float roadKm() {
            return world.road.length / 1000f;
        }
    }
}
