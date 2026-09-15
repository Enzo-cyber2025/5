package com.ggufchat.app;
import android.app.Service;
import android.os.*;
import java.util.*;

/** CPU only: never turns the display on. Bounded leases are renewed only while
 * the owning foreground service has outstanding work; all exits release. */
public final class WorkWakeLocks {
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Map<Service,Lease> LEASES=new HashMap<>();
    private static final class Lease implements Runnable {
        final PowerManager.WakeLock lock;boolean closed;
        Lease(Service s){lock=s.getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"GGUFChat:LocalCompute");lock.setReferenceCounted(false);}
        public synchronized void run(){if(closed)return;lock.acquire(10*60*1000L);MAIN.postDelayed(this,5*60*1000L);}
        synchronized void close(){closed=true;MAIN.removeCallbacks(this);if(lock.isHeld())lock.release();}
    }
    public static synchronized void acquire(Service s){release(s);Lease lease=new Lease(s);LEASES.put(s,lease);lease.run();}
    public static synchronized void release(Service s){Lease lease=LEASES.remove(s);if(lease!=null)lease.close();}
}
