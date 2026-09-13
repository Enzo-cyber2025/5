package com.ggufchat.app;

import android.content.Context;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import android.widget.Toast;
import android.util.Log;
import java.lang.reflect.*;
import java.io.File;
import java.util.*;

/** Associate only the explicitly selected pair, not an arbitrary stored model.
 * Files remain separate: a projector cannot be concatenated with a language GGUF.
 * Architecture/embedding compatibility is checked by the native mtmd loader.
 */
public final class Pairing {
    private static final Map<Context,Set<String>> beforeImport = new WeakHashMap<>();
    public static void begin(Context context,ArrayList<Uri> uris) {
        synchronized(beforeImport) { beforeImport.remove(context); }
        if(uris.size()!=2) return;
        try {
            Class<?> store=Class.forName("com.ggufchat.app.ModelStore");
            ArrayList<?> models=(ArrayList<?>)store.getMethod("load",Context.class).invoke(null,context);
            Set<String> ids=new HashSet<>();
            for(Object model:models) ids.add(field(model,"id"));
            synchronized(beforeImport) { beforeImport.put(context,ids); }
        } catch(Exception e) { Log.e("GGUFPairing","Cannot start selected-pair transaction",e); }
    }
    /** One library record owns both private files; no standalone projector entry. */
    public static boolean isUnified(Object model) {
        try { return !field(model,"mmprojPath").isEmpty()
                && !field(model,"path").equals(field(model,"mmprojPath")); }
        catch(Exception e) { return false; }
    }
    public static ArrayList<Object> visibleModels(ArrayList<?> models) {
        ArrayList<Object> visible=new ArrayList<>();
        try {
            Set<String> attached=new HashSet<>();
            for(Object model:models) if(isUnified(model)) attached.add(field(model,"mmprojPath"));
            for(Object model:models) if(!attached.contains(field(model,"path"))) visible.add(model);
        } catch(Exception e) { throw new IllegalStateException("Não foi possível ler os modelos",e); }
        return visible;
    }
    public static String displayName(Object model) {
        try { return (isUnified(model)?"\uD83D\uDC41 ":"")+field(model,"name")
                    +(isUnified(model)?" · GGUF + mmproj":""); }
        catch(Exception e) { return "Modelo"; }
    }
    private static Class<?> store() throws Exception { return Class.forName("com.ggufchat.app.ModelStore"); }
    private static Object lock() throws Exception {
        Field f=store().getDeclaredField("LOCK");f.setAccessible(true);return f.get(null);
    }
    private static ArrayList<?> raw(Context c) throws Exception {
        return (ArrayList<?>)store().getMethod("loadRecords",Context.class).invoke(null,c);
    }
    private static void save(Context c,ArrayList<?> models) throws Exception {
        store().getMethod("save",Context.class,ArrayList.class).invoke(null,c,models);
    }
    /** Upgrade old paired records without moving bytes or breaking existing chats. */
    public static ArrayList<?> loadUnified(Context c) {
        try { synchronized(lock()) {
            ArrayList<?> all=raw(c);
            ArrayList<Object> units=visibleModels(all);
            boolean changed=units.size()!=all.size();
            for(Object m:units) {
                boolean paired=isUnified(m);
                Field flag=m.getClass().getField("multimodal");
                if(flag.getBoolean(m)!=paired) {flag.setBoolean(m,paired);changed=true;}
                if(paired) {
                    File language=new File(field(m,"path")),projector=new File(field(m,"mmprojPath"));
                    if(language.isFile() && projector.isFile()) {
                        long total=Math.addExact(language.length(),projector.length());
                        Field size=m.getClass().getField("size");
                        if(size.getLong(m)!=total) {size.setLong(m,total);changed=true;}
                    }
                }
            }
            if(changed) save(c,units);
            return units;
        }} catch(Exception e) { throw new IllegalStateException("Falha ao unificar biblioteca",e); }
    }
    /** Delete the unit; never delete a component still referenced by another unit. */
    public static void removeUnified(Context c,String id) {
        try { synchronized(lock()) {
            ArrayList<Object> units=new ArrayList<Object>(loadUnified(c));
            Object removed=null;
            for(Object m:units) if(field(m,"id").equals(id)) {removed=m;break;}
            if(removed==null) return;
            units.remove(removed);save(c,units); // persist before deleting any bytes
            for(Object m:raw(c)) if(field(m,"id").equals(id))
                throw new IllegalStateException("Exclusão não foi persistida; arquivos preservados");
            Set<String> retained=new HashSet<>();
            for(Object m:units) {retained.add(field(m,"path"));retained.add(field(m,"mmprojPath"));}
            String root=new File(c.getFilesDir(),"models").getCanonicalPath()+File.separator;
            for(String path:Arrays.asList(field(removed,"path"),field(removed,"mmprojPath"))) {
                if(path.isEmpty() || retained.contains(path)) continue;
                File file=new File(path);
                if(!file.getCanonicalPath().startsWith(root)) continue;
                if(file.exists() && !file.delete()) {
                    Log.e("GGUFPairing","Could not delete private component: "+path);
                    Toast.makeText(c,"Modelo removido, mas não foi possível liberar um dos arquivos.",Toast.LENGTH_LONG).show();
                }
            }
        }} catch(Exception e) { throw new IllegalStateException("Falha ao excluir modelo unificado",e); }
    }
    private static String field(Object o,String n) throws Exception {
        Object v=o.getClass().getField(n).get(o); return v==null || "null".equals(v.toString())?"":v.toString();
    }
    public static void linkSelected(Context context,ArrayList<Uri> uris) {
        try {
            if(uris.size()!=2) {
                if(uris.size()>2) Toast.makeText(context,"Importados. Para associar, selecione exatamente um GGUF e seu mmproj.",Toast.LENGTH_LONG).show();
                return;
            }
            Set<String> previous;
            synchronized(beforeImport) { previous=beforeImport.remove(context); }
            if(previous==null) throw new IllegalStateException("Importação sem seleção inicial; não associar arquivos antigos");
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
                    if(previous.contains(field(item,"id")) || !names.contains(field(item,"fileName"))) continue;
                    boolean isProjector=field(item,"fileName").toLowerCase(Locale.ROOT).contains("mmproj") || field(item,"architecture").equals("clip");
                    if(isProjector) { if(projector!=null) throw new IllegalArgumentException("Foram selecionados dois projetores"); projector=item; }
                    else { if(model!=null) throw new IllegalArgumentException("Foram selecionados dois modelos, não um modelo e seu mmproj"); model=item; }
                }
                if(model==null || projector==null) throw new IllegalArgumentException("Selecione um GGUF de linguagem e o mmproj correspondente");
                model.getClass().getField("mmprojPath").set(model,field(projector,"path"));
                model.getClass().getField("multimodal").setBoolean(model,true);
                File languageFile=new File(field(model,"path")),projectorFile=new File(field(projector,"path"));
                String root=new File(context.getFilesDir(),"models").getCanonicalPath()+File.separator;
                if(!languageFile.isFile() || !projectorFile.isFile()
                        || !languageFile.getCanonicalPath().startsWith(root)
                        || !projectorFile.getCanonicalPath().startsWith(root))
                    throw new IllegalArgumentException("Os dois componentes precisam estar no armazenamento privado do app");
                model.getClass().getField("size").setLong(model,Math.addExact(languageFile.length(),projectorFile.length()));
                ArrayList<Object> units=new ArrayList<Object>(models);
                units.remove(projector);
                save(context,units);
                ArrayList<?> persisted=raw(context);
                if(persisted.size()!=units.size()) throw new IllegalStateException("Pacote não foi persistido");
                Log.i("GGUFPairing","Selected pair persisted: "+field(model,"fileName")+" + "+field(projector,"fileName"));
                Toast.makeText(context,"Modelo único salvo: GGUF + mmproj. Compatibilidade verificada no carregamento.",Toast.LENGTH_LONG).show();
            }
        } catch(Exception e) {
            Log.e("GGUFPairing","Pair association failed",e);
            Toast.makeText(context,"Não foi possível associar: "+e.getMessage(),Toast.LENGTH_LONG).show();
        }
    }
}
