package com.enzo.ets2ai;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;

/**
 * The trained driving policy, evaluated in plain Java float math.
 *
 * Pure Java (no Android imports) so it can be compiled and verified on the
 * host (android/check_java.sh) and packaged into the APK unchanged.
 *
 * Weights come from assets/model-weights.txt (CSV, exported by
 * ets2ai/ets2ai/contract.py::save_device_format). The forward pass is a
 * bit-for-bit port of ets2ai/model.py::forward (tanh hidden layers, linear
 * output). Cross-checked against numpy and TFLite by the CI.
 */
public final class NeuralNet {

    public final int nIn;
    public final int nOut;
    private final float[][][] w;   // [layer][in][out]
    private final float[][] b;     // [layer][out]
    private final int nLayers;

    private NeuralNet(float[][][] w, float[][] b, int nIn, int nOut) {
        this.w = w;
        this.b = b;
        this.nLayers = w.length;
        this.nIn = nIn;
        this.nOut = nOut;
    }

    /** Loads the CSV device format (see contract.py::save_device_format). */
    public static NeuralNet fromStream(InputStream in) throws Exception {
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
            String header = r.readLine();
            if (header == null) throw new IllegalStateException("pesos vazios");
            String[] h = header.split(",");
            if (!"ETS2AI".equals(h[0]) || !"v1".equals(h[1]))
                throw new IllegalStateException("formato invalido: " + header);
            int nIn = Integer.parseInt(h[2]);
            int nOut = Integer.parseInt(h[3]);
            int[] hidden = new int[h.length - 4];
            for (int i = 4; i < h.length; i++) hidden[i - 4] = Integer.parseInt(h[i]);

            int[] sizes = new int[hidden.length + 2];
            sizes[0] = nIn;
            for (int i = 0; i < hidden.length; i++) sizes[1 + i] = hidden[i];
            sizes[hidden.length + 1] = nOut;

            int nLayers = sizes.length - 1;
            float[][][] w = new float[nLayers][][];
            float[][] b = new float[nLayers][];
            for (int li = 0; li < nLayers; li++) {
                int fanIn = sizes[li], fanOut = sizes[li + 1];
                w[li] = new float[fanIn][fanOut];
                for (int row = 0; row < fanIn; row++) {
                    String[] parts = r.readLine().split(",");
                    for (int col = 0; col < fanOut; col++)
                        w[li][row][col] = Float.parseFloat(parts[col]);
                }
                String[] bParts = r.readLine().split(",");
                b[li] = new float[fanOut];
                for (int col = 0; col < fanOut; col++)
                    b[li][col] = Float.parseFloat(bParts[col]);
            }
            return new NeuralNet(w, b, nIn, nOut);
        } finally {
            in.close();
        }
    }

    /** raw forward pass; out.length == nOut */
    public float[] forward(float[] x) {
        float[] a = new float[x.length];
        System.arraycopy(x, 0, a, 0, x.length);
        int last = nLayers - 1;
        for (int li = 0; li < nLayers; li++) {
            float[][] lw = w[li];
            float[] lb = b[li];
            float[] z = new float[lb.length];
            for (int j = 0; j < lb.length; j++) {
                float s = lb[j];
                for (int i = 0; i < a.length; i++) s += a[i] * lw[i][j];
                z[j] = (li == last) ? s : (float) Math.tanh(s);
            }
            a = z;
        }
        return a;
    }

    /** Contract clamp (ets2ai.contract.clamp_action). */
    public static float[] clampAction(float steer, float throttle, float brake) {
        return new float[] {
            Math.max(-1f, Math.min(1f, steer)),
            Math.max(0f, Math.min(1f, throttle)),
            Math.max(0f, Math.min(1f, brake)),
        };
    }

    /** Normalizes raw physical values into the model input vector (contract v2). */
    public static float[] features(float speedMps, float laneOffsetM, float headingErrRad,
                                   float[] curvAhead5, float speedLimitMps, float fuel,
                                   float fatigue, float jobLeftKm, float radarDistM) {
        float[] f = new float[13];
        f[0] = speedMps / 25f;
        f[1] = laneOffsetM / 3.5f;
        f[2] = headingErrRad / 0.6f;
        for (int i = 0; i < 5; i++) f[3 + i] = curvAhead5[i] / 0.05f;
        f[8] = speedLimitMps / 25f;
        f[9] = fuel;
        f[10] = fatigue;
        f[11] = Math.min(jobLeftKm, 20f) / 20f;
        f[12] = Math.min(radarDistM, 500f) / 500f;
        return f;
    }
}
