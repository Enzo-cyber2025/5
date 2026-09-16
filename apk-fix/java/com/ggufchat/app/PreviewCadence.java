package com.ggufchat.app;

/** Append-only notification preview. No response content is stored here.
 * Once the visible prefix is full, later tokens cannot change this notification.
 * Request-scoped, worker-thread owned; completion notifications are independent.
 */
public final class PreviewCadence {
    public static final int PREFIX_LENGTH=80;
    private int shownLength;
    private long lastUpdate;
    public void reset(){shownLength=0;lastUpdate=0;}
    public boolean needsUpdate(long elapsedMillis,int replyLength){
        int visibleLength=Math.min(PREFIX_LENGTH,replyLength);
        if(visibleLength<=shownLength)return false;
        if(shownLength>0&&elapsedMillis-lastUpdate<1000)return false;
        shownLength=visibleLength;lastUpdate=elapsedMillis;return true;
    }
}
