package com.enzo.ets2ai;

import android.content.Context;

import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;

/**
 * Honest on-device backend benchmark (the "insist on NPU" answer).
 *
 * Publicly, a third-party app on Android can reach hardware acceleration
 * only through delegates: NNAPI (the only public API a vendor NPU driver
 * could plug into — deprecated in Android 15 but still queryable here) and
 * the TFLite GPU delegate. This benchmark loads the SAME policy as
 * ets2ai-float32.tflite (bundled when the CI could fetch the TFLite
 * runtime) and times: Java CPU (always available), TFLite CPU, TFLite GPU
 * and TFLite+NNAPI. Whatever your Galaxy A55 5G actually exposes will show
 * up here — no marketing, just measurements.
 *
 * All TFLite access is via reflection, so the app builds and runs even when
 * the runtime is not embedded in the APK (then only Java CPU is reported).
 */
public final class Backends {

    public interface Report {
        void done(String text);
    }

    public static void benchmark(final Context ctx, final NeuralNet net, final Report cb) {
        new Thread(new Runnable() {
            public void run() {
                final StringBuilder sb = new StringBuilder();
                // typical mid-drive feature vector
                final float[] feat = NeuralNet.features(19.5f, 0.4f, 0.05f,
                        new float[] { 0.0002f, 0.001f, 0.004f, 0.002f, 0f },
                        25f, 0.7f, 0.3f, 4.2f);

                // ---- 1) Java CPU (the one the app actually drives with) ----
                float[] out = net.forward(feat);
                long t0 = System.nanoTime();
                final int N = 200;
                for (int i = 0; i < N; i++) net.forward(feat);
                double javaUs = (System.nanoTime() - t0) / 1000.0 / N;
                sb.append(String.format(java.util.Locale.US,
                        "1) JAVA CPU (em uso no app): %.0f us/decisao — steer %.3f%n%n",
                        javaUs, out[0]));

                // ---- 2..4) TFLite via reflection ----
                if (!tflitePresent()) {
                    sb.append("2) TensorFlow Lite: runtime nao embutido neste APK\n");
                    sb.append("   (build sem runtime TFLite; inferência segue em Java)\n");
                    sb.append("3) GPU delegate: idem\n");
                    sb.append("4) NNAPI (rota publica p/ NPU): idem\n");
                } else {
                    byte[] model = readAsset(ctx, "ets2ai-float32.tflite");
                    if (model == null) {
                        sb.append("2) TensorFlow Lite: modelo .tflite ausente nos assets\n");
                    } else {
                        sb.append(runTflite("2) TFLite CPU (XNNPACK)", model, null, feat));
                        sb.append(runTflite("3) TFLite GPU delegate", model, "gpu", feat));
                        sb.append(runTflite("4) TFLite + NNAPI (rota publica p/ NPU)",
                                model, "nnapi", feat));
                    }
                }
                sb.append("----------------------------------------\n");
                sb.append("Veredito NPU: a NPU do Exynos 1480 nao e\n");
                sb.append("programavel por apps terceiros (SDK Samsung\n");
                sb.append("fechado; NNAPI depreciado). Se o item 4 mostrar\n");
                sb.append("um acelerador real, ele foi medido — nao estimado.\n");
                final String text = sb.toString();
                android.os.Handler h = new android.os.Handler(ctx.getMainLooper());
                h.post(new Runnable() { public void run() { cb.done(text); } });
            }
        }).start();
    }

    private static boolean tflitePresent() {
        try {
            Class.forName("org.tensorflow.lite.Interpreter");
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    private static byte[] readAsset(Context ctx, String name) {
        try {
            InputStream in = ctx.getAssets().open(name);
            try {
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
                return bo.toByteArray();
            } finally {
                in.close();
            }
        } catch (Exception e) {
            return null;
        }
    }

    /** Runs one TFLite configuration via reflection; returns a report line. */
    private static String runTflite(String title, byte[] model, String delegate, float[] feat) {
        Object interpreter = null;
        try {
            Class<?> optionsCls = Class.forName("org.tensorflow.lite.Interpreter$Options");
            Object options = optionsCls.getDeclaredConstructor().newInstance();
            Method setThreads = optionsCls.getMethod("setNumThreads", int.class);
            setThreads.invoke(options, 2);

            Object dele = null;
            if ("gpu".equals(delegate)) {
                Class<?> gpuCls = Class.forName("org.tensorflow.lite.gpu.GpuDelegate");
                dele = gpuCls.getDeclaredConstructor().newInstance();
            } else if ("nnapi".equals(delegate)) {
                Class<?> nnCls = Class.forName("org.tensorflow.lite.nnapi.NnApiDelegate");
                dele = nnCls.getDeclaredConstructor().newInstance();
            }
            if (dele != null) {
                Class<?> delegateIface = Class.forName("org.tensorflow.lite.Delegate");
                Method addDelegate = optionsCls.getMethod("addDelegate", delegateIface);
                addDelegate.invoke(options, dele);
            }

            Class<?> interpCls = Class.forName("org.tensorflow.lite.Interpreter");
            Constructor<?> ctor = interpCls.getConstructor(
                    ByteBuffer.class, optionsCls);
            interpreter = ctor.newInstance(ByteBuffer.wrap(model), options);

            Object input = new float[][] { feat };
            float[][] output = new float[1][3];
            Method invoke = interpCls.getMethod("invoke", Object.class, Object.class);
            invoke.invoke(interpreter, input, output);   // warmup/allocation

            int n = 50;
            long t0 = System.nanoTime();
            for (int i = 0; i < n; i++) {
                output = new float[1][3];
                invoke.invoke(interpreter, new float[][] { feat }, output);
            }
            double us = (System.nanoTime() - t0) / 1000.0 / n;
            return String.format(java.util.Locale.US,
                    "%s: OK — %.0f us/decisao (steer %.3f)%n",
                    title, us, output[0][0]);
        } catch (Throwable t) {
            String reason = t.getClass().getSimpleName();
            Throwable cause = t.getCause();
            if (cause != null) reason += "/" + cause.getClass().getSimpleName();
            return String.format(java.util.Locale.US,
                    "%s: INDISPONIVEL neste aparelho (%s)%n", title, reason);
        } finally {
            if (interpreter != null) {
                try {
                    interpreter.getClass().getMethod("close").invoke(interpreter);
                } catch (Exception ignored) { }
            }
        }
    }

    private Backends() { }
}
