package com.enzo.ets2ai;

import android.content.Context;

import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;

/**
 * Auto-selected inference engine: measures every backend AVAILABLE on this
 * phone (pure-Java CPU, TFLite CPU, TFLite GPU delegate, TFLite+NNAPI —
 * the only public route a vendor NPU driver could plug into) and drives
 * with the fastest one. The choice and the measured latency show up in the
 * HUD. This is the honest maximum a third-party app can do today: the
 * Exynos NPU itself is not programmable by external apps (Samsung Neural
 * SDK is closed to third parties; NNAPI deprecated since Android 15).
 */
public final class InferenceEngine {

    public interface Net {
        float[] forward(float[] x);
        String name();
    }

    /** Pure-Java backend (always available — the same math as training). */
    static final class JavaNet implements Net {
        private final NeuralNet net;
        JavaNet(NeuralNet n) { this.net = n; }
        public float[] forward(float[] x) { return net.forward(x); }
        public String name() { return "Java CPU"; }
    }

    /** Persistent TFLite interpreter via reflection (runtime optional). */
    static final class TfliteNet implements Net {
        private final Object interpreter;
        private final Method invoke;
        private final String name;

        TfliteNet(Object interpreter, Method invoke, String name) {
            this.interpreter = interpreter;
            this.invoke = invoke;
            this.name = name;
        }

        public float[] forward(float[] x) {
            try {
                float[][] out = new float[1][3];
                invoke.invoke(interpreter, new Object[] { new float[][] { x }, out });
                return out[0];
            } catch (Throwable t) {
                throw new RuntimeException(t);
            }
        }

        public String name() { return name; }
    }

    /** Builds and measures all backends; returns the fastest usable one. */
    public static Net create(Context ctx, NeuralNet javaNet) {
        Net best = new JavaNet(javaNet);
        double bestUs = measure(best);
        byte[] model = readAsset(ctx, "ets2ai-float32.tflite");
        if (model != null) {
            String[] names = { "TFLite CPU", "TFLite GPU", "TFLite GPU (Vulkan)",
                               "TFLite GPU (OpenCL)", "TFLite+NNAPI" };
            String[] delegates = { null, "gpu", "gpu-vulkan", "gpu-cl", "nnapi" };
            for (int i = 0; i < delegates.length; i++) {
                TfliteNet n = buildTflite(model, delegates[i], names[i]);
                if (n == null) continue;
                double us;
                try {
                    us = measure(n);
                } catch (Throwable t) {
                    continue;
                }
                if (us < bestUs) {
                    bestUs = us;
                    best = n;
                }
            }
        }
        try {
            android.util.Log.i("ETS2AI", "engine escolhido: " + best.name()
                    + String.format(java.util.Locale.US, " (%.0f us)", bestUs));
        } catch (Throwable ignored) { }
        return best;
    }

    private static double measure(Net n) {
        float[] f = NeuralNet.features(19.5f, 0.4f, 0.05f,
                new float[] { 0.0002f, 0.001f, 0.004f, 0.002f, 0f },
                25f, 0.7f, 0.3f, 4.2f, 120f);
        n.forward(f);                       // warmup
        int reps = 40;
        long t0 = System.nanoTime();
        for (int i = 0; i < reps; i++) n.forward(f);
        return (System.nanoTime() - t0) / 1000.0 / reps;
    }

    private static byte[] readAsset(Context ctx, String name) {
        try {
            InputStream in = ctx.getAssets().open(name);
            try {
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int k;
                while ((k = in.read(buf)) > 0) bo.write(buf, 0, k);
                return bo.toByteArray();
            } finally {
                in.close();
            }
        } catch (Exception e) {
            return null;
        }
    }

    private static TfliteNet buildTflite(byte[] model, String delegate, String name) {
        Object interpreter = null;
        Object dele = null;
        try {
            Class<?> optionsCls = Class.forName("org.tensorflow.lite.Interpreter$Options");
            Object options = optionsCls.getDeclaredConstructor().newInstance();
            optionsCls.getMethod("setNumThreads", int.class).invoke(options, 2);
            if (delegate != null && delegate.startsWith("gpu")) {
                boolean forced = delegate.length() > 3;   // "gpu-vulkan"/"gpu-cl"
                Class<?> gpuCls = Class.forName("org.tensorflow.lite.gpu.GpuDelegate");
                Object opts = forced ? forceGpuOptions(delegate.substring(4)) : null;
                if (forced && opts == null) return null;  // runtime sem setForceBackend
                if (opts != null) {
                    for (Constructor<?> c : gpuCls.getConstructors()) {
                        Class<?>[] ps = c.getParameterTypes();
                        if (ps.length == 1 && ps[0].isInstance(opts)) {
                            dele = c.newInstance(opts);
                            break;
                        }
                    }
                    if (dele == null) return null;
                } else {
                    dele = gpuCls.getDeclaredConstructor().newInstance();
                }
            } else if ("nnapi".equals(delegate)) {
                dele = Class.forName("org.tensorflow.lite.nnapi.NnApiDelegate")
                        .getDeclaredConstructor().newInstance();
            }
            if (dele != null) {
                Class<?> delegateIface = Class.forName("org.tensorflow.lite.Delegate");
                optionsCls.getMethod("addDelegate", delegateIface).invoke(options, dele);
            }
            Class<?> interpCls = Class.forName("org.tensorflow.lite.Interpreter");
            Constructor<?> ctor = interpCls.getConstructor(ByteBuffer.class, optionsCls);
            interpreter = ctor.newInstance(ByteBuffer.wrap(model), options);
            Method invoke = interpCls.getMethod("invoke", Object.class, Object.class);
            return new TfliteNet(interpreter, invoke, name);
        } catch (Throwable t) {
            if (dele != null) {
                try {
                    dele.getClass().getMethod("close").invoke(dele);
                } catch (Exception ignored) { }
            }
            if (interpreter != null) {
                try {
                    interpreter.getClass().getMethod("close").invoke(interpreter);
                } catch (Exception ignored) { }
            }
            return null;
        }
    }


    /** Options com backend FORCADO (VULKAN/OPENCL) via reflection; null se o
     *  runtime nao suportar setForceBackend (o caminho 'auto' segue valendo).
     *  Rota Vulkan pedida pelo usuario: GPU do aparelho via driver Vulkan. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private static Object forceGpuOptions(String backend) {
        Class<?> optsCls;
        try {
            optsCls = Class.forName("org.tensorflow.lite.gpu.GpuDelegateFactory$Options");
        } catch (Throwable t) {
            try {
                optsCls = Class.forName("org.tensorflow.lite.gpu.GpuDelegate$Options");
            } catch (Throwable t2) {
                return null;
            }
        }
        try {
            Class<?> enumCls = Class.forName(
                    "org.tensorflow.lite.gpu.GpuDelegateFactory$Options$GpuBackend");
            Object opts = optsCls.getDeclaredConstructor().newInstance();
            Object be = Enum.valueOf(
                    (Class<? extends Enum>) enumCls.asSubclass(Enum.class),
                    backend.toUpperCase(java.util.Locale.US));
            optsCls.getMethod("setForceBackend", enumCls).invoke(opts, be);
            return opts;
        } catch (Throwable t) {
            return null;
        }
    }

    private InferenceEngine() { }
}
