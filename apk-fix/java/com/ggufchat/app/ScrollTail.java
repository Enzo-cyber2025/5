package com.ggufchat.app;

import android.view.ViewTreeObserver;
import android.widget.ScrollView;
import java.lang.ref.WeakReference;
import java.util.WeakHashMap;

/** Main-thread automatic tail following. One direct scroll after layout, not
 * a smooth-scroll animation / focus search / queued Runnable for every token.
 * Text still arrives immediately; touch scrolling and fling settings are unchanged.
 */
public final class ScrollTail {
    private static final WeakHashMap<ScrollView,Pending> PENDING=new WeakHashMap<>();
    private static final class Pending implements ViewTreeObserver.OnPreDrawListener {
        final WeakReference<ScrollView> view;
        WeakReference<ViewTreeObserver> observer;
        boolean queued;
        Pending(ScrollView scroll){view=new WeakReference<>(scroll);}
        public boolean onPreDraw(){
            ViewTreeObserver tree=observer==null?null:observer.get();
            if(tree!=null&&tree.isAlive())tree.removeOnPreDrawListener(this);
            observer=null;queued=false;
            ScrollView scroll=view.get();
            if(scroll!=null&&scroll.getChildCount()>0){
                // ScrollView clamps to its actual range. Pre-draw is AFTER the
                // appended text has been laid out, including growing code panels.
                scroll.scrollTo(scroll.getScrollX(),scroll.getChildAt(0).getBottom());
            }
            return true;
        }
    }
    public static void request(ScrollView scroll){
        if(scroll==null)return;
        Pending pending=PENDING.get(scroll);
        if(pending==null){pending=new Pending(scroll);PENDING.put(scroll,pending);}
        ViewTreeObserver previous=pending.observer==null?null:pending.observer.get();
        if(pending.queued&&previous!=null&&previous.isAlive())return;
        ViewTreeObserver tree=scroll.getViewTreeObserver();
        pending.observer=new WeakReference<>(tree);pending.queued=true;
        tree.addOnPreDrawListener(pending);
        scroll.postInvalidateOnAnimation();
    }
}
