package ai.arena.ggufchat;

public final class NativeBridge {
    static {
        try { System.loadLibrary("ggufbridge"); } catch (Throwable ignored) {}
    }
    public static native String nativeInfo();
    public static native String inspectFd(int fd, long size, String displayName);
    public static native String draftAnswer(String prompt, String modelA, String modelB, boolean thinking, boolean search);
}
