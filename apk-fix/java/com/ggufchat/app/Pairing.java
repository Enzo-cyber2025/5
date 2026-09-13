package com.ggufchat.app;

import android.content.Context;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import android.widget.Toast;
import android.util.Log;
import java.lang.reflect.*;
import java.util.*;

/** Associate only the explicitly selected pair, not an arbitrary stored model.
 * Files remain separate: a projector cannot be concatenated with a language GGUF.
 * Architecture/embedding compatibility is checked by the native mtmd loader.
 */
public final class Pairing {
    private static String field(Object o,String n) throws Exception {
        Object v=o.getClass().getField(n).get(o); return v==null?"":v.toString();
    }
    public static void linkSelected(Context context,ArrayList<Uri> uris) {
        try {
            if(uris.size()!=2) {
                if(uris.size()>2) Toast.makeText(context,"Importados. Para associar, selecione exatamente um GGUF e seu mmproj.",Toast.LENGTH_LONG).show();
                return;
            }
            Set<String> names=new HashSet<>();
            for(Uri uri:uris) {
                try(Cursor c=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
                    if(c!=null && c.moveToFirst()) names.add(c.getString(0));
                }
            }
            if(names.size()!=2) throw new IllegalArgumentException("Não foi possível identificar os dois arquivos selecionados");
            Class<?> store=Class.forName("com.ggufchat.app.ModelStore");
            Field lockField=store.getDeclaredField("LOCK"); lockField.setAccessible(true);
            synchronized(lockField.get(null)) {
                ArrayList<?> models=(ArrayList<?>)store.getMethod("load",Context.class).invoke(null,context);
                Object model=null,projector=null;
                for(Object item:models) {
                    if(!names.contains(field(item,"fileName"))) continue;
                    boolean isProjector=field(item,"fileName").toLowerCase(Locale.ROOT).contains("mmproj") || field(item,"architecture").equals("clip");
                    if(isProjector) { if(projector!=null) throw new IllegalArgumentException("Foram selecionados dois projetores"); projector=item; }
                    else { if(model!=null) throw new IllegalArgumentException("Foram selecionados dois modelos, não um modelo e seu mmproj"); model=item; }
                }
                if(model==null || projector==null) throw new IllegalArgumentException("Selecione um GGUF de linguagem e o mmproj correspondente");
                model.getClass().getField("mmprojPath").set(model,field(projector,"path"));
                model.getClass().getField("multimodal").setBoolean(model,true);
                store.getMethod("save",Context.class,ArrayList.class).invoke(null,context,models);
                Log.i("GGUFPairing","Selected pair persisted: "+field(model,"fileName")+" + "+field(projector,"fileName"));
                Toast.makeText(context,"GGUF + mmproj associados. A compatibilidade será verificada no carregamento.",Toast.LENGTH_LONG).show();
            }
        } catch(Exception e) {
            Log.e("GGUFPairing","Pair association failed",e);
            Toast.makeText(context,"Não foi possível associar: "+e.getMessage(),Toast.LENGTH_LONG).show();
        }
    }
}
