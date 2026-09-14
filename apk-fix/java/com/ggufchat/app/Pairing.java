package com.ggufchat.app;

import android.content.Context;
import android.app.Activity;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import android.widget.Toast;
import android.util.Log;
import java.lang.reflect.*;
import java.io.File;
import java.util.*;

/** Selected-pair transaction: rewrite metadata/tensor tables into one physical GGUF.
 * Legacy pairs remain readable; new imports are inspected on their worker. */
public final class Pairing {
    private static volatile boolean active;
    public static boolean merging(){return active;}
    private static final Map<Context,Set<String>> beforeImport = new WeakHashMap<>();
    public static void begin(Context context,ArrayList<Uri> uris) {
        synchronized(beforeImport) { beforeImport.remove(context); }
        if(uris.size()!=2) return;
        active=true;
        try {
            Class<?> store=Class.forName("com.ggufchat.app.ModelStore");
            ArrayList<?> models=(ArrayList<?>)store.getMethod("load",Context.class).invoke(null,context);
            Set<String> ids=new HashSet<>();
            for(Object model:models) ids.add(field(model,"id"));
            synchronized(beforeImport) { beforeImport.put(context,ids); }
        } catch(Exception e) { active=false;Log.e("GGUFPairing","Cannot start selected-pair transaction",e); }
    }
    /** One library record owns both private files; no standalone projector entry. */
    public static boolean isUnified(Object model) {
        try { return !field(model,"mmprojPath").isEmpty(); }
        catch(Exception e) { return false; }
    }
    public static ArrayList<Object> visibleModels(ArrayList<?> models) {
        ArrayList<Object> visible=new ArrayList<>();
        try {
            Set<String> attached=new HashSet<>();
            for(Object model:models) if(isUnified(model) && !field(model,"path").equals(field(model,"mmprojPath"))) attached.add(field(model,"mmprojPath"));
            for(Object model:models) if(!attached.contains(field(model,"path"))) visible.add(model);
        } catch(Exception e) { throw new IllegalStateException("Não foi possível ler os modelos",e); }
        return visible;
    }
    public static String displayName(Object model) {
        try { return (isUnified(model)?"\uD83D\uDC41 ":"")+field(model,"name")
                    +(isUnified(model)?(field(model,"path").equals(field(model,"mmprojPath"))?" · GGUF único · visão":" · par legado (2 arquivos)"):" · "+description(field(model,"capability"))); }
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
                        long total=language.equals(projector)?language.length():Math.addExact(language.length(),projector.length());
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
    /** Invoked on the import worker BEFORE ModelStore.add. */
    public static void inspect(Object model) throws Exception {
        GgufFile g=GgufFile.read(new File(field(model,"path")));
        model.getClass().getField("architecture").set(model,g.text("general.architecture"));
        model.getClass().getField("capability").set(model,g.capability());
        model.getClass().getField("multimodal").setBoolean(model,g.singleVision());
        model.getClass().getField("mmprojPath").set(model,g.singleVision()?field(model,"path"):null);
        Log.i("GGUFInspect","GGUF_INSPECT capability="+g.capability()+" tensors="+g.tensors.size()+" architecture="+g.text("general.architecture"));
    }
    public static boolean isProjector(Object model) {
        try{return "VISION_PROJECTOR".equals(field(model,"capability"))||("NOT_INSPECTED".equals(field(model,"capability"))&&"clip".equals(field(model,"architecture")));}
        catch(Exception e){throw new IllegalStateException("Não foi possível ler os parâmetros do modelo",e);}
    }
    private static String description(String cap) {
        if(cap.equals("TEXT_ONLY"))return "texto";
        if(cap.equals("IMAGE_TOKENS_ONLY"))return "tokens de imagem, sem pesos de visão";
        if(cap.equals("MULTIMODAL_DECLARED_INCOMPLETE"))return "parâmetros multimodais incompletos";
        if(cap.equals("VISION_PROJECTOR"))return "projetor de visão, sem linguagem";
        if(cap.equals("NOT_INSPECTED"))return "não analisado; reimporte";
        return "layout multimodal não suportado";
    }
    private static void notify(Context c,String message) {
        Runnable r=()->{Toast.makeText(c,message,Toast.LENGTH_LONG).show();try{
            java.lang.reflect.Method refresh=c.getClass().getDeclaredMethod("refreshModels");refresh.setAccessible(true);refresh.invoke(c);
            refresh=c.getClass().getDeclaredMethod("refreshImportList");refresh.setAccessible(true);refresh.invoke(c);
        }catch(Exception e){Log.e("GGUFPairing","UI refresh",e);}};
        if(c instanceof Activity)((Activity)c).runOnUiThread(r);else r.run();
    }
    public static void linkSelected(Context context,ArrayList<Uri> uris) {
        Set<String> previous;
        synchronized(beforeImport){previous=beforeImport.remove(context);}
        if(uris.size()!=2)return;
        if(previous==null){active=false;notify(context,"Seleção inicial indisponível; arquivos não foram unificados.");return;}
        notify(context,"Unificando metadados e tensores em um único GGUF. Aguarde.");
        new Thread(()->{
            File merged=null; boolean saved=false;
            try {
                Set<String> names=new HashSet<>();
                for(Uri uri:uris)try(Cursor c=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){
                    if(c!=null&&c.moveToFirst())names.add(c.getString(0));
                }
                if(names.size()!=2)throw new IllegalArgumentException("Seleção deve conter dois arquivos identificáveis");
                Object model=null,projector=null;
                synchronized(lock()) {
                    for(Object item:raw(context)) {
                        if(previous.contains(field(item,"id"))||!names.contains(field(item,"fileName")))continue;
                        if("VISION_PROJECTOR".equals(field(item,"capability"))){if(projector!=null)throw new IllegalArgumentException("Dois projetores selecionados");projector=item;}
                        else {if(model!=null)throw new IllegalArgumentException("Dois modelos de linguagem selecionados");model=item;}
                    }
                }
                if(model==null||projector==null)throw new IllegalArgumentException("Selecione linguagem + projetor de visão; identificação por parâmetros/tensores, não nome");
                File languageFile=new File(field(model,"path")),projectorFile=new File(field(projector,"path"));
                String root=new File(context.getFilesDir(),"models").getCanonicalPath()+File.separator;
                if(!languageFile.getCanonicalPath().startsWith(root)||!projectorFile.getCanonicalPath().startsWith(root))throw new IllegalArgumentException("Componentes fora da pasta privada");
                merged=new File(context.getFilesDir(),"models/"+UUID.randomUUID()+"-unified.gguf");
                GgufFile g=GgufFile.merge(languageFile,projectorFile,merged); // streaming, NOT holding store/UI lock
                synchronized(lock()) {
                    ArrayList<Object> units=new ArrayList<Object>(raw(context));Object live=null,liveProj=null;
                    for(Object item:units){if(field(item,"id").equals(field(model,"id"))&&field(item,"path").equals(languageFile.getPath()))live=item;
                        if(field(item,"id").equals(field(projector,"id"))&&field(item,"path").equals(projectorFile.getPath()))liveProj=item;}
                    if(live==null||liveProj==null)throw new IllegalStateException("Modelos removidos/alterados durante unificação; resultado descartado");
                    live.getClass().getField("path").set(live,merged.getAbsolutePath());
                    live.getClass().getField("mmprojPath").set(live,merged.getAbsolutePath());
                    live.getClass().getField("size").setLong(live,merged.length());
                    live.getClass().getField("multimodal").setBoolean(live,true);
                    live.getClass().getField("capability").set(live,g.capability());
                    units.remove(liveProj);save(context,units);
                    for(Object item:raw(context))if(field(item,"id").equals(field(live,"id"))&&field(item,"path").equals(merged.getAbsolutePath()))saved=true;
                    if(!saved)throw new IllegalStateException("Falha ao persistir unificação; originais preservados");
                    // Delete originals only after the new record is durable, and only if unreferenced.
                    Set<String> keep=new HashSet<>();for(Object item:units){keep.add(field(item,"path"));keep.add(field(item,"mmprojPath"));}
                    for(File f:Arrays.asList(languageFile,projectorFile))if(!keep.contains(f.getPath())&&!f.delete())Log.e("GGUFPairing","Original privado não removido após unificação");
                }
                Log.i("GGUFPairing","GGUF_PHYSICAL_UNIFICATION_OK tensors="+g.tensors.size()+" bytes="+merged.length());
                notify(context,"Salvo: um único arquivo GGUF com linguagem e visão. Compatibilidade final verificada pelo motor.");
            }catch(Exception e){Log.e("GGUFPairing","Physical merge failed",e);notify(context,"Não foi possível unificar: "+e.getMessage()+". Originais preservados.");}
            finally{active=false;if(merged!=null&&!saved)merged.delete();}
        },"GGUF-physical-unification").start();
    }
}
