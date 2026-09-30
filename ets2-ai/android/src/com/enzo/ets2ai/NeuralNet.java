package com.enzo.ets2ai;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

/**
 * The trained driving policy, evaluated in plain Java float math.
 *
 * Weights come from assets/model-weights.txt (CSV, exported by
 * ets2ai/ets2ai/contract.py::save_device_format). The forward pass is a
 * bit-for-bit port of ets2ai/model.py::forward (tanh hidden layers, linear
 * output). Cross-checked against numpy and TFLite by the CI tests.
 */
public final class NeuralNet {

    public final int nIn;
    public final int nOut;
    private final float[][][] layers; // [layer][0]=W (fanIn x fanOut), [layer][1]=b

    private NeuralNet(float[][][] layers, int nIn, int nOut) {
        this.layers = layers;
        this.nIn = nIn;
        this.nOut = nOut;
    }

    public static NeuralNet fromAssets(android.content.res.AssetManager am, String path)
            throws Exception {
        return fromStream(am.open(path));
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
            List<Integer> hidden = new ArrayList<Integer>();
            for (int i = 4; i < h.length; i++) hidden.add(Integer.parseInt(h[i]));

            List<Integer> sizes = new ArrayList<Integer>();
            sizes.add(nIn);
            sizes.addAll(hidden);
            sizes.add(nOut);

            List<float[][][]> parsed = new ArrayList<float[][][]>();
            for (int li = 0; li < sizes.size() - 1; li++) {
                int fanIn = sizes.get(li), fanOut = sizes.get(li + 1);
                float[][] w = new float[fanIn][fanOut];
                for (int row = 0; row < fanIn; row++) {
                    String line = r.readLine();
                    String[] parts = line.split(",");
                    for (int col = 0; col < fanOut; col++)
                        w[row][col] = Float.parseFloat(parts[col]);
                }
                String[] bParts = r.readLine().split(",");
                float[] b = new float[fanOut];
                for (int col = 0; col < fanOut; col++)
                    b[col] = Float.parseFloat(bParts[col]);
                float[][][] layer = new float[][][] { w, new float[][] { b } };
                parsed.add(layer);
            }
            return new NeuralNet(parsed.toArray(new float[0][][]), nIn, nOut);
        } finally {
            in.close();
        }
    }

    /** raw forward pass; out.length == nOut */
    public float[] forward(float[] x) {
        float[] a = new float[x.length];
        System.arraycopy(x, 0, a, 0, x.length);
        int last = layers.length - 1;
        for (int li = 0; li < layers.length; li++) {
            float[][] w = layers[li][0];
            float[] b = layers[li][1][0];
            float[] z = new float[b.length];
            for (int j = 0; j < b.length; j++) {
                float s = b[j];
                for (int i = 0; i < a.length; i++) s += a[i] * w[i][j];
                z[j] = (li == last) ? s : tanh(s);
            }
            a = z;
        }
        return a;
    }

    private static float tanh(float v) {
        return (float) Math.tanh(v);
    }

    /** Contract clamp (ets2ai.contract.clamp_action). */
    public static float[] clampAction(float steer, float throttle, float brake) {
        return new float[] {
            Math.max(-1f, Math.min(1f, steer)),
            Math.max(0f, Math.min(1f, throttle)),
            Math.max(0f, Math.min(1f, brake)),
        };
    }

    /** Normalizes raw physical values into the model input vector (contract). */
    public static float[] features(float speedMps, float laneOffsetM, float headingErrRad,
                                   float[] curvAhead5, float speedLimitMps, float fuel,
                                   float fatigue, float jobLeftKm) {
        float[] f = new float[12];
        f[0] = speedMps / 25f;
        f[1] = laneOffsetM / 3.5f;
        f[2] = headingErrRad / 0.6f;
        for (int i = 0; i < 5; i++) f[3 + i] = curvAhead5[i] / 0.05f;
        f[8] = speedLimitMps / 25f;
        f[9] = fuel;
        f[10] = fatigue;
        f[11] = Math.min(jobLeftKm, 100f) / 100f;
        return f;
    }
}
