package com.nova.local;

import android.os.ParcelFileDescriptor;

/**
 * Small, deliberately dependency-free bridge to the bundled llama.cpp runtime.
 * Model file descriptors are never copied to app storage: the native side mmaps
 * the descriptor and lets llama.cpp keep its own mmap-backed tensor views.
 */
public final class NativeRuntime {
    private static final boolean NATIVE_AVAILABLE;

    static {
        boolean loaded = false;
        try {
            System.loadLibrary("nova_runtime");
            loaded = true;
        } catch (Throwable ignored) {
            // Keep the UI usable on devices where the optional native ABI is not present.
        }
        NATIVE_AVAILABLE = loaded;
    }

    private NativeRuntime() { }

    public static boolean isAvailable() {
        return NATIVE_AVAILABLE;
    }

    public static String probe(ParcelFileDescriptor descriptor, long size) {
        if (!NATIVE_AVAILABLE || descriptor == null) {
            return "{\"ok\":false,\"reason\":\"native runtime unavailable\"}";
        }
        try {
            return nativeProbe(descriptor.getFd(), size);
        } catch (Throwable error) {
            return "{\"ok\":false,\"reason\":\"probe failed\"}";
        }
    }

    public static long load(ParcelFileDescriptor model,
                            long modelSize,
                            ParcelFileDescriptor projector,
                            boolean preferVulkan) {
        if (!NATIVE_AVAILABLE || model == null) return 0L;
        try {
            return nativeLoad(model.getFd(), modelSize,
                    projector == null ? -1 : projector.getFd(), preferVulkan);
        } catch (Throwable error) {
            return 0L;
        }
    }

    public static String modelInfo(long handle) {
        if (!NATIVE_AVAILABLE || handle == 0L) return "{}";
        try {
            return nativeModelInfo(handle);
        } catch (Throwable error) {
            return "{}";
        }
    }

    public static String generate(long handle, String prompt, int maxTokens, float temperature) {
        if (!NATIVE_AVAILABLE || handle == 0L) return "";
        try {
            return nativeGenerate(handle, prompt, maxTokens, temperature);
        } catch (Throwable error) {
            return "";
        }
    }

    public static String generateWithImage(long handle,
                                           String prompt,
                                           int maxTokens,
                                           float temperature,
                                           byte[] rgb,
                                           int width,
                                           int height) {
        if (!NATIVE_AVAILABLE || handle == 0L || rgb == null) return "";
        try {
            return nativeGenerateWithImage(handle, prompt, maxTokens, temperature,
                    rgb, width, height);
        } catch (Throwable error) {
            return "";
        }
    }

    public static void cancel(long handle) {
        if (!NATIVE_AVAILABLE || handle == 0L) return;
        try {
            nativeCancel(handle);
        } catch (Throwable ignored) { }
    }

    public static void release(long handle) {
        if (!NATIVE_AVAILABLE || handle == 0L) return;
        try {
            nativeRelease(handle);
        } catch (Throwable ignored) { }
    }

    public static String vulkanStatus() {
        if (!NATIVE_AVAILABLE) {
            return "{\"available\":false,\"reason\":\"runtime indisponível\"}";
        }
        try {
            return nativeVulkanStatus();
        } catch (Throwable error) {
            return "{\"available\":false,\"reason\":\"Vulkan não respondeu\"}";
        }
    }

    private static native String nativeProbe(int fd, long size);
    private static native long nativeLoad(int modelFd, long modelSize, int projectorFd, boolean preferVulkan);
    private static native String nativeModelInfo(long handle);
    private static native String nativeGenerate(long handle, String prompt, int maxTokens, float temperature);
    private static native String nativeGenerateWithImage(long handle, String prompt, int maxTokens,
                                                         float temperature, byte[] rgb,
                                                         int width, int height);
    private static native void nativeCancel(long handle);
    private static native void nativeRelease(long handle);
    private static native String nativeVulkanStatus();
}
