package com.ggufchat.app;

import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.provider.MediaStore;
import android.graphics.*;
import android.graphics.drawable.Drawable;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Selection/storage UI; GenerationService reads these files through AttachmentInference. */
public final class Attachments {
    private static final int FILES=6101,PHOTOS=6102,CAMERA=6103;
    private static final ExecutorService IO=Executors.newSingleThreadExecutor();
    private static final ArrayList<WeakReference<Attachments>> screens=new ArrayList<>();
    private static final Map<String,ArrayList<AtomicBoolean>> jobs=new HashMap<>();
    private final Activity activity;
    private final Context context;
    private final String chatId;
    private Button camera,status;
    private static final String NOTICE="Leitura local: imagens com modelo de visão; texto UTF-8/UTF-16, PDF (camada de texto), DOCX/ODT (texto principal). PDF sem texto precisa de visão. Áudio, vídeo e formatos binários não suportados geram aviso. Imagens são ajustadas para até 1024 px, com orientação automática e transparência sobre branco. Imagens animadas usam o primeiro quadro; HEIF/AVIF dependem do suporte do Android; documentos e imagens precisam caber no contexto. Não há corte silencioso de texto. Você pode desativar a leitura de um anexo nesta lista.";
    private Attachments(Activity a) {
        activity=a;context=a.getApplicationContext();chatId=a.getIntent().getStringExtra("chatId");
    }
    private static Object get(Object o,String field) throws Exception {Field f=o.getClass().getDeclaredField(field);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String field,Object value) throws Exception {Field f=o.getClass().getDeclaredField(field);f.setAccessible(true);f.set(o,value);}
    private static Attachments find(Activity a) {
        synchronized(screens) {
            Iterator<WeakReference<Attachments>> i=screens.iterator();
            while(i.hasNext()){Attachments s=i.next().get();if(s==null)i.remove();else if(s.activity==a)return s;}
            Attachments s=new Attachments(a);screens.add(new WeakReference<>(s));return s;
        }
    }
    private void toast(String s){Toast.makeText(activity,s,Toast.LENGTH_LONG).show();}
    private boolean multimodal() {
        try {
            Object chat=get(activity,"chat");Object path=get(chat,"mmprojPath");
            if(path!=null&&!path.toString().isEmpty()&&!"null".equals(path.toString()))return true;
            // Existing chats can lack the redundant projector path even when
            // the imported, inspected GGUF already contains the vision encoder.
            String modelPath=String.valueOf(get(chat,"modelPath"));
            Object model=Pairing.store().getMethod("byPath",Context.class,String.class).invoke(null,context,modelPath);
            return model!=null&&"VISION_SINGLE_GGUF".equals(Pairing.field(model,"capability"));
        }
        catch(Exception e){return false;}
    }
    private static int dp(Activity a,int value){return Math.round(value*a.getResources().getDisplayMetrics().density);}
    private Button icon(boolean isCamera) {
        Button b=new Button(activity);CompactUi.style(b);b.setText("");b.setPadding(dp(activity,6),0,dp(activity,6),0);
        b.setContentDescription(isCamera?"Câmera":"Anexar arquivos");
        Drawable image=new Symbol(isCamera,isCamera&&!multimodal()?0xff777777:0xffe3ece7);
        image.setBounds(0,0,dp(activity,24),dp(activity,24));b.setCompoundDrawables(image,null,null,null);
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(dp(activity,36),dp(activity,36));lp.setMarginEnd(10);b.setLayoutParams(lp);
        return b;
    }
    public static void install(Activity a,LinearLayout root,LinearLayout compose) {
        final Attachments s=find(a);
        s.camera=s.icon(true);s.camera.setEnabled(s.multimodal());s.camera.setAlpha(s.multimodal()?1f:0.5f);
        s.camera.setOnClickListener(v->s.cameraMenu());
        Button clip=s.icon(false);clip.setOnClickListener(v->s.pick("*/*",FILES));
        compose.addView(s.camera,0);compose.addView(clip,1);
        s.status=new Button(a);CompactUi.style(s.status);s.status.setMaxWidth(Integer.MAX_VALUE);
        s.status.setContentDescription("Lista de anexos");s.status.setOnClickListener(v->s.showList());
        root.addView(s.status,root.indexOfChild(compose));
        try {Object old=get(a,"attachLabel");if(old instanceof View)((View)old).setVisibility(View.GONE);AttachmentStore.initialize(s.context,s.chatId);}
        catch(Exception e){s.toast("Falha ao recuperar anexos: "+e.getMessage());}
        s.refresh();
    }
    private void cameraMenu() {
        if(!multimodal())return;
        new AlertDialog.Builder(activity).setTitle("Fotos").setItems(new String[]{"Importar foto","Tirar foto"},(dialog,which)->{
            if(which==0)pick("image/*",PHOTOS);else capture();
        }).show();
    }
    private void pick(String type,int request) {
        if(request==PHOTOS&&!multimodal())return;
        Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType(type).addCategory(Intent.CATEGORY_OPENABLE)
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {activity.startActivityForResult(i,request);}catch(Exception e){toast("Não foi possível abrir o gerenciador de arquivos: "+e.getMessage());}
    }
    /** Old toolbar entry points use the same multi-attachment queue, never the old RAM reader. */
    public static void pickLegacy(Activity a,String type) {Attachments s=find(a);if(type.startsWith("image/"))s.cameraMenu();else s.pick("*/*",FILES);}
    private SharedPreferences cameraState(){return context.getSharedPreferences("attachment_camera",Context.MODE_PRIVATE);}
    private Uri cameraUri(String id){return Uri.parse("content://"+AttachmentProvider.AUTHORITY+"/camera/"+id);}
    private File cameraFile(String id){return new File(context.getFilesDir(),"attachments-camera/"+id+".jpg");}
    private void capture() {
        if(!multimodal())return;
        String id=UUID.randomUUID().toString();File file=cameraFile(id);Uri uri=cameraUri(id);
        try {
            if(!file.getParentFile().isDirectory()&&!file.getParentFile().mkdirs())throw new IOException("Sem espaço para a câmera");
            if(!file.createNewFile())throw new IOException("Não foi possível criar destino da foto");
            if(!cameraState().edit().putString("id",id).putString("chat",chatId).commit())throw new IOException("Não foi possível guardar a captura pendente");
            Intent i=new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT,uri)
                .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
            i.setClipData(ClipData.newRawUri("Foto",uri));
            activity.startActivityForResult(i,CAMERA);
        } catch(Exception e){file.delete();cameraState().edit().clear().commit();toast("Câmera indisponível: "+e.getMessage());}
    }
    public static void single(Activity a,Uri uri){find(a).queue(Collections.singletonList(uri),0,null);}
    public static void result(Activity a,int request,int result,Intent intent) {find(a).onResult(request,result,intent);}
    private void onResult(int request,int result,Intent intent) {
        if(request==CAMERA) {
            String id=cameraState().getString("id",null),owner=cameraState().getString("chat",null);
            if(id==null || !id.matches("[0-9a-f-]{36}"))return;
            cameraState().edit().clear().commit();Uri uri=cameraUri(id);
            context.revokeUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if(result==Activity.RESULT_OK && chatId.equals(owner) && cameraFile(id).length()>0) {
                queue(Collections.singletonList(uri),0,cameraFile(id));
                new AlertDialog.Builder(activity).setTitle("Foto adicionada à fila").setMessage("Você pode tirar outras fotos e enviar todas juntas.")
                    .setPositiveButton("Tirar outra foto",(d,w)->capture()).setNegativeButton("Concluir",null).show();
            } else {cameraFile(id).delete();if(result==Activity.RESULT_OK)toast("A câmera não salvou a foto completa.");}
            return;
        }
        if((request!=FILES&&request!=PHOTOS&&request!=42)||result!=Activity.RESULT_OK||intent==null)return;
        LinkedHashSet<Uri> selected=new LinkedHashSet<>();ClipData clip=intent.getClipData();
        if(clip!=null)for(int n=0;n<clip.getItemCount();n++){Uri uri=clip.getItemAt(n).getUri();if(uri!=null)selected.add(uri);}
        if(intent.getData()!=null)selected.add(intent.getData());
        if(!selected.isEmpty())queue(new ArrayList<>(selected),intent.getFlags(),null);
    }
    private static boolean busy(String chat) {synchronized(jobs){ArrayList<AtomicBoolean> list=jobs.get(chat);return list!=null&&!list.isEmpty();}}
    private static void notifyScreens(String chat) {
        synchronized(screens){for(WeakReference<Attachments> ref:screens){Attachments s=ref.get();if(s!=null&&chat.equals(s.chatId))s.activity.runOnUiThread(()->{if(!s.activity.isDestroyed())s.refresh();});}}
    }
    private void queue(final List<Uri> uris,int flags,final File captured) {
        final String owner=chatId;final Context c=context;final AtomicBoolean cancelled=new AtomicBoolean(false);
        synchronized(jobs){ArrayList<AtomicBoolean> list=jobs.get(owner);if(list==null){list=new ArrayList<>();jobs.put(owner,list);}list.add(cancelled);}
        // Grants are attempted before returning from onActivityResult, then released
        // after copying. Providers without persistable grants still work while open.
        final Set<Uri> persisted=new HashSet<>();
        for(Uri uri:uris)if((flags&Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)!=0)try {
            c.getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);persisted.add(uri);
        }catch(Exception ignored){}
        refresh();
        IO.execute(()->{
            int failures=0;String first="";
            try {
                try{AttachmentStore.error(c,owner,"");}catch(Exception ignored){}
                for(Uri uri:uris) {
                    if(cancelled.get())break;
                    try{if(captured==null)AttachmentStore.importUri(c,owner,uri,cancelled);else AttachmentStore.importCamera(c,owner,captured,cancelled);}
                    catch(Exception e){failures++;if(first.isEmpty())first=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();}
                    notifyScreens(owner);
                }
                String error=cancelled.get()?"Importação cancelada; anexos concluídos foram preservados.":(failures>0?failures+" arquivo(s) não importado(s): "+first:"");
                AttachmentStore.error(c,owner,error);
            } catch(Exception e){android.util.Log.e("GGUFAttachments","Failed to persist attachment state",e);}
            finally {
                for(Uri uri:persisted)try{c.getContentResolver().releasePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(Exception ignored){}
                // Camera bytes move atomically on success; preserve the original on failure.
                if(captured!=null&&cancelled.get())captured.delete();
                synchronized(jobs){ArrayList<AtomicBoolean> list=jobs.get(owner);if(list!=null){list.remove(cancelled);if(list.isEmpty())jobs.remove(owner);}}
                notifyScreens(owner);
            }
        });
    }
    public static void deleteChat(Context c,String id) {
        try {
            // The old ChatStore writer can report an I/O failure only in logs.
            // Never delete files if the conversation itself still exists.
            ArrayList<?> chats=(ArrayList<?>)Class.forName("com.ggufchat.app.ChatStore").getMethod("load",Context.class).invoke(null,c);
            for(Object chat:chats)if(id.equals(get(chat,"id")))return;
            AttachmentStore.markDeleted(id);
            synchronized(jobs){ArrayList<AtomicBoolean> tokens=jobs.get(id);if(tokens!=null)for(AtomicBoolean token:tokens)token.set(true);}
            final Context app=c.getApplicationContext();
            IO.execute(()->{try{AttachmentStore.deleteFiles(app,id);}catch(Exception e){android.util.Log.e("GGUFAttachments","Attachment cleanup failed",e);}});
        } catch(Exception e){android.util.Log.e("GGUFAttachments","Could not delete conversation attachments",e);}
    }
    public static void resume(Activity a){find(a).refresh();}
    private void refresh() {
        if(status==null)return;
        try {
            JSONObject state=AttachmentStore.read(context,chatId);JSONArray items=state.getJSONArray("items");int pending=0;
            for(int i=0;i<items.length();i++)if(items.getJSONObject(i).optInt("message",-1)<0)pending++;
            String error=state.optString("error","");boolean copying=busy(chatId);int images=0;
            for(int i=0;i<items.length();i++)if(Images.isImage(items.getJSONObject(i)))images++;
            status.setVisibility(items.length()>0||copying||!error.isEmpty()?View.VISIBLE:View.GONE);
            status.setText(pending+" anexo(s) pendente(s) · "+(items.length()-pending)+" enviado(s)"
                +(images>0?" · "+images+" imagem(ns)": "")
                +(copying?" · importando…":!error.isEmpty()?" · aviso":""));
            if(camera!=null){camera.setEnabled(multimodal());camera.setAlpha(multimodal()?1f:0.5f);}
        } catch(Exception e){status.setVisibility(View.VISIBLE);status.setText("Falha ao ler anexos — toque para detalhes");}
        Images.refresh(activity);
    }
    private void showList() {
        try {
            JSONObject state=AttachmentStore.read(context,chatId);JSONArray items=state.getJSONArray("items");
            String error=state.optString("error","");
            String[] rows=new String[items.length()];for(int i=0;i<items.length();i++){JSONObject item=items.getJSONObject(i);
                rows[i]=item.getString("name")+" · "+android.text.format.Formatter.formatFileSize(activity,item.getLong("size"))
                    +(item.optInt("message",-1)<0?" · pendente":" · mensagem "+(item.getInt("message")+1))+(item.optBoolean("excluded",false)?" · leitura desativada":"");}
            AlertDialog.Builder dialog=new AlertDialog.Builder(activity).setTitle("Anexos desta conversa")
                .setItems(rows,(d,which)->{try{itemMenu(items.getJSONObject(which));}catch(Exception e){toast(e.getMessage());}})
                .setNegativeButton("Fechar",null).setNeutralButton("Informações",(d,w)->new AlertDialog.Builder(activity).setMessage(NOTICE+(error.isEmpty()?"":"\n\n"+error)).setPositiveButton("OK",null).show());
            if(busy(chatId))dialog.setPositiveButton("Cancelar importação",(d,w)->{synchronized(jobs){ArrayList<AtomicBoolean> list=jobs.get(chatId);if(list!=null)for(AtomicBoolean token:list)token.set(true);}});
            dialog.show();
        } catch(Exception e){toast("Não foi possível abrir os anexos: "+e.getMessage());}
    }
    private void itemMenu(JSONObject item) throws Exception {
        String id=item.getString("id");boolean pending=item.optInt("message",-1)<0;
        AlertDialog.Builder dialog=new AlertDialog.Builder(activity).setTitle(item.getString("name")).setMessage(item.getString("mime")+"\n"+item.getLong("size")+" bytes\n\n"+NOTICE)
            .setPositiveButton("Abrir",(d,w)->{
                try {Uri uri=Uri.parse("content://"+AttachmentProvider.AUTHORITY+"/"+AttachmentStore.key(chatId)+"/"+id);
                    Intent i=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,item.optString("mime","application/octet-stream")).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    activity.startActivity(Intent.createChooser(i,"Abrir anexo"));
                }catch(Exception e){toast("Nenhum aplicativo conseguiu abrir este formato: "+e.getMessage());}
            });
        dialog.setNegativeButton(item.optBoolean("excluded",false)?"Ativar leitura":"Desativar leitura",(d,w)->{
            try{synchronized(AttachmentStore.LOCK){JSONObject state=AttachmentStore.read(context,chatId);JSONArray items=state.getJSONArray("items");for(int i=0;i<items.length();i++){JSONObject entry=items.getJSONObject(i);if(id.equals(entry.getString("id")))entry.put("excluded",!entry.optBoolean("excluded",false));}AttachmentStore.write(context,chatId,state);}refresh();}
            catch(Exception e){toast("Não foi possível alterar a leitura: "+e.getMessage());}
        });
        if(pending)dialog.setNeutralButton("Remover",(d,w)->{try{AttachmentStore.remove(context,chatId,id);refresh();}catch(Exception e){toast(e.getMessage());}});
        else if(Images.isImage(item))dialog.setNeutralButton("Desanexar imagem",(d,w)->Images.detach(activity,id));
        dialog.show();
    }
    public static boolean prepareSend(Activity a) {
        Attachments s=find(a);
        try {
            if(busy(s.chatId)){s.toast("Aguarde a importação terminar ou cancele pela lista de anexos.");return false;}
            JSONArray items=AttachmentStore.read(s.context,s.chatId).getJSONArray("items");int count=0;
            for(int i=0;i<items.length();i++)if(items.getJSONObject(i).optInt("message",-1)<0)count++;
            set(a,"pendingName",count>0?count+" arquivo(s)":null);
            set(a,"pendingContent",count>0?"Anexos vinculados a esta mensagem para leitura.":null);
            return true;
        }catch(Exception e){s.toast("Não foi possível preparar os anexos: "+e.getMessage());return false;}
    }
    public static void sent(Activity a) {
        Attachments s=find(a);
        try {Object chat=get(a,"chat");ArrayList<?> messages=(ArrayList<?>)get(chat,"messages");AttachmentStore.sent(s.context,s.chatId,messages.size()-1);s.refresh();}
        catch(Exception e){s.toast("Não foi possível vincular os anexos; os arquivos continuam preservados: "+e.getMessage());}
    }
    private static final class Symbol extends Drawable {
        final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);final boolean camera;
        Symbol(boolean c,int color){camera=c;paint.setColor(color);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.9f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);}
        public void draw(Canvas canvas){canvas.save();canvas.translate(getBounds().left,getBounds().top);canvas.scale(getBounds().width()/24f,getBounds().height()/24f);
            if(camera){Path p=new Path();p.moveTo(3,7);p.lineTo(7,7);p.lineTo(9,4);p.lineTo(15,4);p.lineTo(17,7);p.lineTo(21,7);p.lineTo(21,20);p.lineTo(3,20);p.close();canvas.drawPath(p,paint);canvas.drawCircle(12,13,4,paint);}
            else {canvas.rotate(30,12,12);Path p=new Path();p.moveTo(17,7);p.lineTo(17,16);p.cubicTo(17,23,6,23,6,16);p.lineTo(6,6);p.cubicTo(6,0,14,0,14,6);p.lineTo(14,16);p.cubicTo(14,19,10,19,10,16);p.lineTo(10,7);canvas.drawPath(p,paint);}
            canvas.restore();}
        public void setAlpha(int alpha){paint.setAlpha(alpha);}public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);}public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
