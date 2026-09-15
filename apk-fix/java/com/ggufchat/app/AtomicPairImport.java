package com.ggufchat.app;

import android.content.Context;
import android.app.Activity;
import android.app.AlertDialog;
import android.net.Uri;
import android.util.Log;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Exactly two selected URIs are ONE transaction, never two ModelStore.add calls.
 * Temporary copies are not library entries. Original provider files are read-only.
 */
public final class AtomicPairImport {
    private static volatile boolean busy;
    public static boolean active(){return busy;}
    public static boolean start(Context c,ArrayList<Uri> selected) {
        boolean alreadyBusy;
        synchronized(AtomicPairImport.class) {
            alreadyBusy=busy;
            if(!alreadyBusy&&selected.size()!=2)return false;
            if(!alreadyBusy)busy=true;
        }
        if(alreadyBusy){Pairing.notify(c,"Aguarde a unificação atual terminar.");return true;}
        ArrayList<Uri> input=new ArrayList<>(selected);
        Pairing.notify(c,"Validando e unificando os dois arquivos. Só um GGUF válido será salvo. Aguarde.");
        ImportProgress.Session progress=ImportProgress.beginPair(c);
        try { ComputeService.submit(c,()->execute(c,input,progress)); }
        catch(RuntimeException e){busy=false;progress.finish(false);Pairing.notify(c,"Não foi possível iniciar o serviço de importação: "+e.getMessage());}
        return true;
    }
    private static void copy(Context c,Uri uri,File dest,ImportProgress.Session progress,int index) throws IOException {
        long total=progress.source(c,uri,index),done=0;
        try(InputStream in=c.getContentResolver().openInputStream(uri);FileOutputStream out=new FileOutputStream(dest)) {
            if(in==null)throw new IOException("O provedor não abriu um dos arquivos selecionados");
            byte[] b=new byte[128*1024];int n;
            while((n=in.read(b))!=-1){if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Importação cancelada");out.write(b,0,n);done=Math.addExact(done,n);progress.update("copy"+index,done,total,false);}
            out.getFD().sync();progress.update("copy"+index,done,done,true);
        }
    }
    /** Real JNI loaders, explicitly CPU for validation, not a GPU-performance claim. */
    static void validate(File gguf) throws Exception {
        Class<?> nativeApi=Class.forName("com.ggufchat.app.Native");
        long handle=(Long)nativeApi.getMethod("create",String.class,String.class,int.class,int.class,int.class,boolean.class)
                .invoke(null,gguf.getAbsolutePath(),gguf.getAbsolutePath(),512,2,0,true);
        if(handle==0)throw new IOException("Validação de linguagem + visão não concluída: "+nativeApi.getMethod("lastError",long.class).invoke(null,0L));
        try {if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Validação cancelada");Log.i("GGUFPairing","GGUF_ATOMIC_NATIVE_VALIDATED same_path=1 backend=CPU");}
        finally {nativeApi.getMethod("destroy",long.class).invoke(null,handle);}
    }
    private static void set(Object model,String field,Object value) throws Exception {model.getClass().getField(field).set(model,value);}
    private static boolean referenced(ArrayList<?> records,File target) throws Exception {
        for(Object m:records)if(target.getAbsolutePath().equals(Pairing.field(m,"path"))||target.getAbsolutePath().equals(Pairing.field(m,"mmprojPath")))return true;
        return false;
    }
    private static void removeTree(File file) throws IOException {
        if(!file.exists())return;
        // Only our private staging directories are passed here. Do not follow symlinks.
        if(file.isDirectory()&&!Files.isSymbolicLink(file.toPath())) {
            File[] children=file.listFiles();if(children==null)throw new IOException("Não foi possível limpar a pasta temporária");
            for(File child:children)removeTree(child);
        }
        if(!file.delete())throw new IOException("Não foi possível remover temporário: "+file.getName());
    }
    static void recover(Context c,ArrayList<?> records) throws Exception {
        synchronized(AtomicPairImport.class) {
            if(busy)return;
            File root=new File(c.getFilesDir(),"pair-import-staging");File[] dirs=root.listFiles();if(dirs==null)return;
            for(File stage:dirs) {
                if(!stage.getName().matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"))continue;
                File target=new File(c.getFilesDir(),"models/"+stage.getName()+"-unified.gguf");
                if(!referenced(records,target)&&target.exists()&&!target.delete())throw new IOException("Não foi possível descartar saída não publicada");
                removeTree(stage);
                Log.i("GGUFPairing","GGUF_ATOMIC_RECOVERED preserve_committed_records=1");
            }
        }
    }
    private static void execute(Context c,ArrayList<Uri> uris,ImportProgress.Session progress) {
        File stage=null,target=null;boolean committed=false;
        try {
            String id=UUID.randomUUID().toString();
            stage=new File(c.getFilesDir(),"pair-import-staging/"+id);
            if(!stage.mkdirs())throw new IOException("Sem acesso/espaço para a pasta temporária");
            File first=new File(stage,"first.gguf"),second=new File(stage,"second.gguf"),output=new File(stage,"result.gguf");
            copy(c,uris.get(0),first,progress,0);
            GgufFile a=GgufFile.read(first,progress.reader(0));
            copy(c,uris.get(1),second,progress,1);
            GgufFile b=GgufFile.read(second,progress.reader(1));
            String ar=a.pairingRole(),br=b.pairingRole();
            if(ar.equals(br))throw new IOException("O par precisa de linguagem + projetor compatível; foram selecionados dois componentes do tipo "+ar);
            GgufFile language=ar.equals("language")?a:b,projector=ar.equals("projector")?a:b;
            GgufFile merged=GgufFile.merge(language,projector,output,progress.merger());
            progress.nativeStart();validate(output);progress.nativeDone();
            String name=language.text("general.name");if(name.isEmpty())name=language.text("general.architecture")+" · unificado";
            // No two private component files may remain when the library commits.
            removeTree(first);removeTree(second);
            File models=new File(c.getFilesDir(),"models");if(!models.isDirectory()&&!models.mkdirs())throw new IOException("Pasta de modelos indisponível");
            target=new File(models,id+"-unified.gguf");
            synchronized(Pairing.lock()) {
                if(target.exists())throw new IOException("Colisão de arquivo; nada foi substituído");
                Files.move(output.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE);
                Object model=Class.forName("com.ggufchat.app.ModelInfo").getConstructor().newInstance();
                set(model,"id",id);set(model,"name",name);set(model,"fileName",target.getName());
                set(model,"path",target.getAbsolutePath());set(model,"mmprojPath",target.getAbsolutePath());
                set(model,"size",target.length());set(model,"importedAt",System.currentTimeMillis());
                set(model,"architecture",merged.text("general.architecture"));set(model,"capability",merged.capability());set(model,"multimodal",true);
                ArrayList<Object> records=new ArrayList<>(Pairing.raw(c));records.add(model);Pairing.save(c,records);
                committed=referenced(Pairing.raw(c),target);
                if(!committed)throw new IOException("Índice não foi persistido; importação recusada");
            }
            Log.i("GGUFPairing","GGUF_PHYSICAL_UNIFICATION_OK tensors="+merged.tensors.size()+" bytes="+target.length());
            Log.i("GGUFPairing","GGUF_ATOMIC_IMPORT_COMMITTED records_added=1 source_files_remaining=0");
            Pairing.notify(c,"Importação concluída: um único GGUF, tensores conferidos e linguagem/visão carregadas pelo motor.");
        } catch(Exception|LinkageError e) {
            Log.e("GGUFPairing","GGUF_ATOMIC_IMPORT_REJECTED",e);
            Throwable reason=e;while(reason.getCause()!=null&&reason.getCause()!=reason)reason=reason.getCause();
            String message="Nenhum par foi importado como dois modelos. Seus arquivos de origem não foram alterados.\n\n"+reason.toString();
            Pairing.notify(c,"Importação recusada: "+reason.getMessage());
            if(c instanceof Activity)((Activity)c).runOnUiThread(()->{
                Activity a=(Activity)c;if(a.isFinishing()||a.isDestroyed())return;
                try{new AlertDialog.Builder(c).setTitle("Importação recusada").setMessage(message).setPositiveButton("OK",null).show();}
                catch(RuntimeException window){Log.w("GGUFPairing","Import error available in notification/log; Activity no longer visible",window);}
            });
        } finally {
            try {
                synchronized(Pairing.lock()) {
                    // A save whose outcome cannot be read must NEVER lose its GGUF.
                    // Keep the staging journal for recovery on the next successful load.
                    if(!committed&&target!=null&&target.exists()&&!referenced(Pairing.raw(c),target))removeTree(target);
                    if(stage!=null)removeTree(stage);
                }
            } catch(Exception e){Log.e("GGUFPairing","Pending private staging recovery; source files untouched",e);}
            progress.finish(committed);
            busy=false;
        }
    }
}
