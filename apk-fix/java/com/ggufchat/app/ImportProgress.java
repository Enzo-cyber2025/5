package com.ggufchat.app;

import android.app.Activity;
import android.app.ProgressDialog;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.util.Log;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.util.*;

/** Live per-file and per-stage UI. All updates come from actual work counters.
 * Unknown source lengths and native loading remain explicitly indeterminate.
 */
public final class ImportProgress {
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Map<Context,Session> SESSIONS=new WeakHashMap<>();
    private static Session active;
    public static final class Session {
        private WeakReference<Activity> activity;
        private ProgressDialog dialog;
        private boolean owned,terminal,queued;
        private long lastPaint;
        private String current="",result="";
        private final LinkedHashMap<String,Row> rows=new LinkedHashMap<>();
        private final long[] sizes={-1,-1};
        Session(Context c,boolean pair,ProgressDialog existing) {
            activity=new WeakReference<>(c instanceof Activity?(Activity)c:null);
            dialog=existing;owned=existing==null;
            int count=pair?2:1;
            for(int i=0;i<count;i++){
                rows.put("copy"+i,new Row("Importação "+(i+1)+" — Arquivo "+(i+1),true));
                rows.put("identify"+i,new Row("Identificação "+(i+1),false));
            }
            if(pair){rows.put("merge",new Row("Unificação (pesos)",true));rows.put("verify",new Row("Conferência dos tensores",true));}
            rows.put("native",new Row("Validação no motor",false));
            rows.put("save",new Row("Salvar na biblioteca",false));
        }
        public long source(Context c,Uri uri,int index) {
            String name="Arquivo "+(index+1);long size=-1;
            try(Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE},null,null,null)) {
                if(cursor!=null&&cursor.moveToFirst()) {
                    int n=cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME),s=cursor.getColumnIndex(OpenableColumns.SIZE);
                    if(n>=0&&!cursor.isNull(n))name=cursor.getString(n).replace('\n',' ').replace('\r',' ');
                    if(s>=0&&!cursor.isNull(s))size=cursor.getLong(s);
                }
            }catch(Exception e){Log.i("GGUFProgress","Source size unavailable; using byte counter");}
            synchronized(this){sizes[index]=size;rows.get("copy"+index).label="Importação "+(index+1)+" — "+name;}
            update("copy"+index,0,size,false);return size;
        }
        public GgufFile.Progress reader(int index) {return (stage,done,total,complete)->update("identify"+index,done,total,complete);}
        public GgufFile.Progress merger() {return (stage,done,total,complete)->update(stage,done,total,complete);}
        public void update(String key,long done,long total,boolean complete) {
            synchronized(this) {
                if(terminal)return;
                Row row=rows.get(key);if(row==null)return;
                row.started=true;row.done=done;row.total=total;row.complete=complete;current=key;
                int pct=ProgressMeter.percent(done,total,complete);
                int bucket=pct<0?-1:pct/5;
                if(bucket!=row.logged||complete&&!row.loggedComplete) {
                    Log.i("GGUFProgress","GGUF_IMPORT_PROGRESS stage="+key+" percent="+pct+" done="+done+" total="+total+" complete="+complete);
                    row.logged=bucket;row.loggedComplete=complete;
                }
                schedule();
            }
        }
        public void nativeStart(){update("native",0,-1,false);}
        public void nativeDone(){update("native",1,1,true);}
        public void noNative(){synchronized(this){rows.get("native").skip=true;schedule();}}
        public void finish(boolean success) {
            synchronized(this) {
                if(terminal)return;
                if(success)update("save",1,1,true);
                terminal=true;result=success?"Concluído — 100%":"Interrompido — importação não concluída";
                Log.i("GGUFProgress","GGUF_IMPORT_PROGRESS_FINISHED success="+success);
                schedule();
            }
            synchronized(SESSIONS){SESSIONS.values().removeAll(Collections.singleton(this));if(active==this)active=null;}
        }
        private void schedule() {
            if(queued)return;queued=true;
            long delay=Math.max(0,180-(android.os.SystemClock.uptimeMillis()-lastPaint));
            MAIN.postDelayed(()->paint(),delay);
        }
        private synchronized void paint() {
            queued=false;lastPaint=android.os.SystemClock.uptimeMillis();
            Activity a=activity.get();if(a==null||a.isFinishing()||a.isDestroyed())return;
            try {
                if(dialog==null){dialog=new ProgressDialog(a);dialog.setProgressStyle(ProgressDialog.STYLE_HORIZONTAL);dialog.setCancelable(false);dialog.setTitle("Progresso da importação");dialog.setMessage("Preparando importação…");owned=true;dialog.show();}
                StringBuilder message=new StringBuilder();
                Row activeRow=rows.get(current);
                if(!terminal&&activeRow!=null)message.append("Etapa atual: ").append(activeRow.label).append("\n\n");
                for(Row row:rows.values()) {
                    message.append(row.label).append(": ");
                    if(row.skip)message.append("não necessária");
                    else if(!row.started)message.append("aguardando");
                    else {
                        int pct=ProgressMeter.percent(row.done,row.total,row.complete);
                        if(pct>=0)message.append(pct).append('%');
                        else message.append(row.bytes?(row.label.startsWith("Importação")?"tamanho não informado":"calculando o total"):"em andamento, sem percentual disponível");
                        if(row.bytes)message.append(" · ").append(ProgressMeter.amount(row.done));
                    }
                    message.append('\n');
                }
                if(terminal)message.append(result);
                // Percentages belong to their named rows. The default numeric
                // footer would display a fabricated 0/100 during native/unknown work.
                dialog.setProgressNumberFormat(null);dialog.setProgressPercentFormat(null);
                dialog.setMessage(message.toString());dialog.setMax(100);
                Row row=rows.get(current);int pct=row==null?-1:ProgressMeter.percent(row.done,row.total,row.complete);
                dialog.setIndeterminate(!terminal&&pct<0);dialog.setProgress(terminal?(result.startsWith("Concluído")?100:0):Math.max(0,pct));
                if(terminal&&owned){ProgressDialog closing=dialog;MAIN.postDelayed(()->{try{closing.dismiss();}catch(Exception ignored){}},result.startsWith("Concluído")?700:0);}
            }catch(Exception e){Log.e("GGUFProgress","Progress window unavailable; import continues",e);}
        }
    }
    private static final class Row {
        String label;final boolean bytes;long done,total=-1;boolean started,complete,skip,loggedComplete;int logged=-99;
        Row(String label,boolean bytes){this.label=label;this.bytes=bytes;}
    }
    public static Session beginPair(Context c) {
        Session session=new Session(c,true,null);
        synchronized(SESSIONS){SESSIONS.put(c,session);active=session;}
        session.update("copy0",0,-1,false);return session;
    }
    public static void beginSingle(Context c,Uri uri) {
        ProgressDialog existing=null;
        try{Field f=c.getClass().getDeclaredField("progress");f.setAccessible(true);existing=(ProgressDialog)f.get(c);}catch(Exception ignored){}
        Session session=new Session(c,false,existing);
        synchronized(SESSIONS){SESSIONS.put(c,session);active=session;}
        // Query and byte updates are performed on the existing import worker, not UI.
        session.update("copy0",0,-1,false);
    }
    public static void syncCopied(java.io.OutputStream stream) throws java.io.IOException {
        if(!(stream instanceof java.io.FileOutputStream))throw new java.io.IOException("Destino de importação inválido");
        ((java.io.FileOutputStream)stream).getFD().sync();
    }
    public static Session get(Context c){synchronized(SESSIONS){return SESSIONS.get(c);}}
    public static void singleCopy(Context c,long done,long total){if(Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException("Importação cancelada");Session s=get(c);if(s!=null)s.update("copy0",done,total,false);}
    public static void singleSource(Context c,Uri uri){Session s=get(c);if(s!=null)s.source(c,uri,0);}
    public static void identificationStart(Context c) {
        Session s=get(c);if(s==null)return;
        synchronized(s){Row r=s.rows.get("copy0");s.update("copy0",r.done,r.done,true);}
        s.update("identify0",0,-1,false);
    }
    public static void singleFinished(Context c,boolean success){Session s=get(c);if(s!=null)s.finish(success);}
    /** Restore a live progress window when the Activity is recreated. */
    public static void attach(Activity a) {
        Session s;synchronized(SESSIONS){s=active;}
        if(s==null)return;
        synchronized(s){if(s.terminal||s.activity.get()==a)return;
            try{if(s.dialog!=null)s.dialog.dismiss();}catch(Exception ignored){}
            s.activity=new WeakReference<>(a);s.dialog=null;s.owned=true;s.schedule();}
    }
}
