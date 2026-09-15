package com.ggufchat.app;

/** Pure progress arithmetic. 100 means an explicitly completed stage, never a timer. */
public final class ProgressMeter {
    public static int percent(long done,long total,boolean complete) {
        if(complete)return 100;
        if(total<=0||done>total)return -1;
        if(done<=0)return 0;
        return Math.min(99,(int)(100.0*((double)done/(double)total)));
    }
    public static String amount(long bytes) {
        return String.format(java.util.Locale.ROOT,"%.1f MiB",Math.max(0,bytes)/(1024.0*1024.0));
    }
}
