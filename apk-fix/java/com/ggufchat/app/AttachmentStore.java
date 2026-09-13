package com.ggufchat.app;

import android.content.Context;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Private streamed file storage. Limits of disk/providers still apply; no file-size/count quota. */
public final class AttachmentStore {
    static final Object LOCK=new Object();
    private static final Set<String> initialized=new HashSet<>();
    static String key(String chat) throws Exception {
        if(chat==null || chat.isEmpty()) throw new IOException("Conversa ausente");
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(chat.getBytes("UTF-8"));
        StringBuilder s=new StringBuilder();for(byte b:hash)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
    static File directory(Context c,String chat) throws Exception {
        File dir=new File(c.getFilesDir(),"attachments/"+key(chat));
        if(!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Sem acesso ao armazenamento de anexos");
        return dir;
    }
    static AtomicFile index(Context c,String chat) throws Exception {return new AtomicFile(new File(directory(c,chat),"index.json"));}
    static JSONObject read(Context c,String chat) throws Exception {
        synchronized(LOCK) {
            AtomicFile file=index(c,chat);
            try {return new JSONObject(new String(file.readFully(),"UTF-8"));}
            catch(FileNotFoundException missing) {return new JSONObject().put("items",new JSONArray()).put("error","");}
        }
    }
    static void write(Context c,String chat,JSONObject value) throws Exception {
        synchronized(LOCK) {
            AtomicFile file=index(c,chat);FileOutputStream out=null;
            try {out=file.startWrite();out.write(value.toString().getBytes("UTF-8"));file.finishWrite(out);}
            catch(Exception e) {if(out!=null)file.failWrite(out);throw e;}
        }
    }
    static void initialize(Context c,String chat) throws Exception {
        synchronized(LOCK) {
            String key=directory(c,chat).getAbsolutePath();if(initialized.contains(key))return;
            JSONObject state=read(c,chat);Set<String> keep=new HashSet<>();JSONArray items=state.getJSONArray("items");
            for(int i=0;i<items.length();i++)keep.add(items.getJSONObject(i).getString("id")+".data");
            File[] files=directory(c,chat).listFiles();if(files!=null)for(File f:files)
                if(f.getName().endsWith(".part") || (f.getName().endsWith(".data") && !keep.contains(f.getName())))f.delete();
            initialized.add(key);
        }
    }
    static long copy(InputStream in,OutputStream out,AtomicBoolean cancelled) throws IOException {
        byte[] buffer=new byte[128*1024];long total=0;int n;
        while((n=in.read(buffer))!=-1) {
            if(cancelled.get())throw new InterruptedIOException("Importação cancelada");
            if(n==0)continue;
            out.write(buffer,0,n);total=Math.addExact(total,n);
        }
        if(cancelled.get())throw new InterruptedIOException("Importação cancelada");
        return total;
    }
    static JSONObject importUri(Context c,String chat,Uri uri,AtomicBoolean cancelled) throws Exception {
        initialize(c,chat);
        String name="arquivo",type=null;
        try {type=c.getContentResolver().getType(uri);}catch(Exception ignored){}
        try(Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
            if(cursor!=null && cursor.moveToFirst() && !cursor.isNull(0))name=cursor.getString(0);
        } catch(Exception ignored) {} // Providers may omit metadata; bytes still remain importable.
        String id=UUID.randomUUID().toString();File dir=directory(c,chat),part=new File(dir,id+".part"),dest=new File(dir,id+".data");
        boolean committed=false;
        try {
            long bytes;
            try(InputStream in=c.getContentResolver().openInputStream(uri);FileOutputStream out=new FileOutputStream(part)) {
                if(in==null)throw new IOException("O provedor não abriu o arquivo");
                bytes=copy(in,out,cancelled);out.getFD().sync();
            }
            if(!part.renameTo(dest))throw new IOException("Não foi possível concluir a cópia privada");
            JSONObject item=new JSONObject().put("id",id).put("name",name).put("mime",type==null?"application/octet-stream":type)
                .put("size",bytes).put("message",-1);
            synchronized(LOCK) {
                if(cancelled.get())throw new InterruptedIOException("Importação cancelada");
                JSONObject state=read(c,chat);state.getJSONArray("items").put(item);write(c,chat,state);committed=true;
            }
            return item;
        } finally {part.delete();if(!committed)dest.delete();}
    }
    static JSONObject importCamera(Context c,String chat,File source,AtomicBoolean cancelled) throws Exception {
        initialize(c,chat);
        String id=UUID.randomUUID().toString();File dest=new File(directory(c,chat),id+".data");
        synchronized(LOCK) {
            if(cancelled.get())throw new InterruptedIOException("Importação cancelada");
            JSONObject state=read(c,chat);
            JSONObject item=new JSONObject().put("id",id).put("name","Foto-"+id+".jpg").put("mime","image/jpeg")
                .put("size",source.length()).put("message",-1);
            if(!source.renameTo(dest))throw new IOException("Não foi possível armazenar a foto");
            try {state.getJSONArray("items").put(item);write(c,chat,state);}
            catch(Exception e){dest.renameTo(source);throw e;}
            return item;
        }
    }
    static void error(Context c,String chat,String error) throws Exception {
        synchronized(LOCK){JSONObject state=read(c,chat);state.put("error",error);write(c,chat,state);}
    }
    static void sent(Context c,String chat,int message) throws Exception {
        if(message<0)throw new IOException("Mensagem não foi salva");
        synchronized(LOCK){JSONObject state=read(c,chat);JSONArray items=state.getJSONArray("items");
            for(int i=0;i<items.length();i++){JSONObject item=items.getJSONObject(i);if(item.optInt("message",-1)<0)item.put("message",message);}
            write(c,chat,state);
        }
    }
    static void remove(Context c,String chat,String id) throws Exception {
        synchronized(LOCK) {
            JSONObject state=read(c,chat);JSONArray old=state.getJSONArray("items"),next=new JSONArray();boolean found=false;
            for(int i=0;i<old.length();i++) {JSONObject item=old.getJSONObject(i);
                if(item.getString("id").equals(id) && item.optInt("message",-1)<0)found=true;else next.put(item);
            }
            state.put("items",next);write(c,chat,state);
            if(found){File f=new File(directory(c,chat),id+".data");if(f.exists()&&!f.delete())throw new IOException("Anexo removido, mas não foi possível liberar espaço");}
        }
    }
}
