package com.ggufchat.app;

import android.content.*;
import android.net.Uri;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.util.*;

/** Non-exported provider: only exact URI grants, never an entire private directory. */
public final class AttachmentProvider extends ContentProvider {
    public static final String AUTHORITY="com.ggufchat.app.attachments";
    public boolean onCreate(){return true;}
    private File resolve(Uri uri) throws FileNotFoundException {
        List<String> p=uri.getPathSegments();
        if(!AUTHORITY.equals(uri.getAuthority()) || p.size()!=2)throw new FileNotFoundException("URI inválida");
        String bucket=p.get(0),id=p.get(1);
        if(!id.matches("[0-9a-f-]{36}"))throw new FileNotFoundException("Identificador inválido");
        File file;
        if(bucket.equals("camera"))file=new File(getContext().getFilesDir(),"attachments-camera/"+id+".jpg");
        else {
            if(!bucket.matches("[0-9a-f]{64}"))throw new FileNotFoundException("Conversa inválida");
            file=new File(getContext().getFilesDir(),"attachments/"+bucket+"/"+id+".data");
        }
        if(!file.isFile())throw new FileNotFoundException("Anexo não encontrado");
        return file;
    }
    private JSONObject metadata(Uri uri) {
        try {
            File file=resolve(uri);
            if(uri.getPathSegments().get(0).equals("camera"))return new JSONObject().put("name","Foto-"+uri.getLastPathSegment()+".jpg").put("mime","image/jpeg").put("size",file.length());
            JSONObject state;
            synchronized(AttachmentStore.LOCK) {state=new JSONObject(new String(new AtomicFile(new File(file.getParentFile(),"index.json")).readFully(),"UTF-8"));}
            JSONArray items=state.getJSONArray("items");
            for(int i=0;i<items.length();i++)if(items.getJSONObject(i).getString("id").equals(uri.getLastPathSegment()))return items.getJSONObject(i);
        } catch(Exception ignored) {}
        return new JSONObject();
    }
    public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        File file=resolve(uri);
        if(!uri.getPathSegments().get(0).equals("camera") && !"r".equals(mode))throw new FileNotFoundException("Anexos salvos são somente leitura");
        return ParcelFileDescriptor.open(file,ParcelFileDescriptor.parseMode(mode));
    }
    public String getType(Uri uri){return metadata(uri).optString("mime","application/octet-stream");}
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
        JSONObject m=metadata(uri);
        String[] columns=projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection;
        MatrixCursor cursor=new MatrixCursor(columns);Object[] row=new Object[columns.length];
        for(int i=0;i<columns.length;i++) {
            if(OpenableColumns.DISPLAY_NAME.equals(columns[i]))row[i]=m.optString("name","anexo");
            else if(OpenableColumns.SIZE.equals(columns[i]))row[i]=m.optLong("size",0);
        }
        cursor.addRow(row);return cursor;
    }
    public Uri insert(Uri uri,ContentValues v){throw new UnsupportedOperationException();}
    public int update(Uri uri,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
    public int delete(Uri uri,String s,String[] a){throw new UnsupportedOperationException();}
}
