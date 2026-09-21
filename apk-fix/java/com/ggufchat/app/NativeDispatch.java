package com.ggufchat.app;

import android.util.Log;

/** Select once per process, using the kernel's common CPU capabilities, not model names. */
public final class NativeDispatch {
    private static boolean loaded;
    private static native int cpuVariant();
    public static synchronized void load() {
        if(loaded)return;
        String library="aijni";
        try {
            System.loadLibrary("ggufcpu");
            int variant=cpuVariant();
            if(variant==2)library="aijni_i8mm";
            else if(variant==1)library="aijni_dotprod";
        } catch(UnsatisfiedLinkError e) {
            Log.w("GGUFDispatch","CPU probe unavailable; using baseline",e);
        }
        try {System.loadLibrary(library);}
        catch(UnsatisfiedLinkError e) {
            if("aijni".equals(library))throw e;
            Log.w("GGUFDispatch","Optimized library unavailable; using baseline",e);
            library="aijni";System.loadLibrary(library);
        }
        loaded=true;
        Log.i("GGUFDispatch","GGUF_CPU_DISPATCH library="+library);
    }
}
