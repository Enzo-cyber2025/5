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
    public static boolean merging(){return AtomicPairImport.active();}
    /** One library record owns both private files; no standalone projector entry. */
    public static boolean isUnified(Object model) {
        try {
            String path=field(model,"path"),proj=field(model,"mmprojPath");
            if(path.isEmpty()||proj.isEmpty())return false;
            if(path.equals(proj))return "VISION_SINGLE_GGUF".equals(field(model,"capability"));
            // Preserve explicitly labelled legacy pairs; never call them one physical file.
            return new File(path).isFile()&&new File(proj).isFile();
        }
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
        try { return (isUnified(model)?"Visão · ":"")+field(model,"name")
                    +(isUnified(model)?(field(model,"path").equals(field(model,"mmprojPath"))?" · GGUF único · visão":" · par legado (2 arquivos)"):" · "+description(field(model,"capability"))); }
        catch(Exception e) { return "Modelo"; }
    }
    static Class<?> store() throws Exception { return Class.forName("com.ggufchat.app.ModelStore"); }
    static Object lock() throws Exception {
        Field f=store().getDeclaredField("LOCK");f.setAccessible(true);return f.get(null);
    }
    static ArrayList<?> raw(Context c) throws Exception {
        return (ArrayList<?>)store().getMethod("loadRecords",Context.class).invoke(null,c);
    }
    static void save(Context c,ArrayList<?> models) throws Exception {
        store().getMethod("save",Context.class,ArrayList.class).invoke(null,c,models);
    }
    /** Upgrade old paired records without moving bytes or breaking existing chats. */
    public static ArrayList<?> loadUnified(Context c) {
        try { synchronized(lock()) {
            ArrayList<?> all=raw(c);
            AtomicPairImport.recover(c,all);
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
    static String field(Object o,String n) throws Exception {
        Object v=o.getClass().getField(n).get(o); return v==null || "null".equals(v.toString())?"":v.toString();
    }
    /** Invoked on the import worker BEFORE ModelStore.add. */
    public static void inspect(Object model) throws Exception {inspectWithProgress(null,model);}
    public static void inspectWithProgress(Context c,Object model) throws Exception {
        ImportProgress.Session progress=ImportProgress.get(c);
        GgufFile g=GgufFile.read(new File(field(model,"path")),progress==null?GgufFile.Progress.NONE:progress.reader(0));
        if(g.singleVision()) {
            if(progress!=null)progress.nativeStart();
            AtomicPairImport.validate(g.file);
            if(progress!=null)progress.nativeDone();
        }else if(progress!=null)progress.noNative();
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
        if(cap.equals("UNKNOWN_MODEL"))return "estrutura de linguagem não reconhecida";
        if(cap.equals("NOT_INSPECTED"))return "não analisado; reimporte";
        return "layout multimodal não suportado";
    }
    static void notify(Context c,String message) {
        Runnable r=()->{Toast.makeText(c,message,Toast.LENGTH_LONG).show();try{
            java.lang.reflect.Method refresh=c.getClass().getDeclaredMethod("refreshModels");refresh.setAccessible(true);refresh.invoke(c);
            refresh=c.getClass().getDeclaredMethod("refreshImportList");refresh.setAccessible(true);refresh.invoke(c);
        }catch(Exception e){Log.e("GGUFPairing","UI refresh",e);}};
        if(c instanceof Activity)((Activity)c).runOnUiThread(r);else r.run();
    }
}
