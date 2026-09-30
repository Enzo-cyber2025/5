package com.enzo.ets2ai;

import android.content.pm.PackageManager;
import android.os.Build;

/**
 * Honest NPU/hardware diagnostics for this device.
 *
 * Context: the Samsung Neural SDK is no longer distributed to third-party
 * developers, and Android's NNAPI is deprecated as of Android 15. This probe
 * reports what the device exposes publicly and what a third-party app can
 * actually use today. See ets2-ai/README.md for the full verdict and sources.
 */
public final class NpuProbe {

    public static String report(android.content.Context ctx) {
        PackageManager pm = ctx.getPackageManager();
        StringBuilder sb = new StringBuilder();

        sb.append("APARELHO\n");
        sb.append("  modelo: ").append(Build.MODEL).append('\n');
        sb.append("  fabricante: ").append(Build.MANUFACTURER).append('\n');
        sb.append("  placa: ").append(Build.BOARD).append('\n');
        if (Build.VERSION.SDK_INT >= 31) {
            sb.append("  SoC: ").append(Build.SOC_MANUFACTURER)
              .append(" ").append(Build.SOC_MODEL).append('\n');
        } else {
            sb.append("  SoC: (API < 31 nao expoe SOC_MODEL)\n");
        }
        sb.append("  Android: ").append(Build.VERSION.RELEASE)
          .append(" (SDK ").append(Build.VERSION.SDK_INT).append(")\n\n");

        sb.append("ACELERADORES DECLARADOS\n");
        sb.append("  NNAPI (android.hardware.neuralnetworks): ")
          .append(pm.hasSystemFeature("android.hardware.neuralnetworks") ? "SIM" : "NAO").append('\n');
        sb.append("  Vulkan (android.hardware.vulkan.version): ")
          .append(pm.hasSystemFeature("android.hardware.vulkan.version") ? "SIM" : "NAO").append('\n');
        sb.append("  Vulkan compute: ")
          .append(pm.hasSystemFeature("android.hardware.vulkan.compute") ? "SIM" : "NAO").append('\n');
        sb.append("  Vulkan 1.1: ")
          .append(pm.hasSystemFeature("android.hardware.vulkan.version_1_1") ? "SIM" : "NAO").append("\n\n");

        sb.append("RUNTIMES ML DETECTAVEIS POR APP TERCEIRO\n");
        sb.append("  TensorFlow Lite (org.tensorflow.lite.Interpreter): ")
          .append(classExists("org.tensorflow.lite.Interpreter")).append('\n');
        sb.append("  LiteRT (com.google.ai.edge.litert.LlmInference): ")
          .append(classExists("com.google.ai.edge.litert.LlmInference")).append('\n');
        sb.append("  NNAPI delegate TF Lite: ")
          .append(classExists("org.tensorflow.lite.nnapi.NnApiDelegate")).append('\n');
        sb.append("  MediaPipe tasks: ")
          .append(classExists("com.google.mediapipe.tasks.core.BaseTaskApi")).append("\n\n");

        sb.append("VEREDITO PARA ESTE APP\n");
        if (Build.VERSION.SDK_INT >= 35) {
            sb.append("  Android 15+: NNAPI foi DEPRECIADO pelo Google.\n");
        }
        sb.append("  Samsung Neural SDK: fechado para desenvolvedores terceiros\n");
        sb.append("  (policy oficial da Samsung). A NPU do Exynos nao e\n");
        sb.append("  programavel por apps comuns hoje.\n\n");
        sb.append("  Este app roda a politica em JAVA puro (CPU, precisao\n");
        sb.append("  float32) — mesmo resultado numerico do treino. Os .tflite\n");
        sb.append("  (float32 e int8) ja sao gerados no CI e prontos para um\n");
        sb.append("  delegate acelerado (GPU/LiteRT) quando disponivel no app.\n");
        return sb.toString();
    }

    private static String classExists(String name) {
        try {
            Class.forName(name);
            return "DISPONIVEL";
        } catch (Throwable t) {
            return "nao embarcado no app";
        }
    }

    private NpuProbe() { }
}
