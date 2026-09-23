package com.ggufchat.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.drawable.GradientDrawable;
import android.os.Looper;
import android.text.TextUtils;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** Visible image attachments with an explicit detach control per image.
 * Detaching removes the private copy and the message link, so the model stops
 * receiving those pixels; nothing is silently kept.
 */
public final class Images {
    private static final String TAG="GGUFImages";
    private static final int THUMB_DP=44, MAX_CHIPS=8;
    private static final Map<String,Holder> HOLDERS=new HashMap<String,Holder>();

    private static final class Holder {
        Activity activity;LinearLayout bar;LinearLayout chips;TextView summary;Button detachAll;
        boolean shown;
    }

    private Images(){}

    private static int dp(Context c,int n){return Math.round(c.getResources().getDisplayMetrics().density*n);}

    static boolean isImage(JSONObject item){
        String mime=item.optString("mime","").toLowerCase(Locale.ROOT);
        if(mime.startsWith("image/"))return true;
        String name=item.optString("name","").toLowerCase(Locale.ROOT);
        return name.matches(".*\\.(png|jpe?g|webp|bmp|gif|heic|heif|avif|tiff?|jxl)$");
    }

    private static ArrayList<JSONObject> images(JSONObject state) throws Exception {
        ArrayList<JSONObject> found=new ArrayList<JSONObject>();
        JSONArray items=state.getJSONArray("items");
        for(int i=0;i<items.length();i++){
            JSONObject item=items.getJSONObject(i);
            if(isImage(item))found.add(item);
        }
        return found;
    }

    public static void install(Activity activity,LinearLayout root,LinearLayout compose){
        Holder holder=HOLDERS.get(chatId(activity));
        if(holder!=null&&holder.activity==activity)return;
        holder=new Holder();
        holder.activity=activity;
        LinearLayout bar=new LinearLayout(activity);
        bar.setOrientation(LinearLayout.VERTICAL);
        LinearLayout line=new LinearLayout(activity);
        line.setOrientation(LinearLayout.HORIZONTAL);
        line.setGravity(Gravity.CENTER_VERTICAL);
        holder.summary=new TextView(activity);
        holder.summary.setTextSize(11.5f);
        holder.summary.setTextColor(0xff9fb4c4);
        holder.summary.setSingleLine(true);
        holder.summary.setEllipsize(TextUtils.TruncateAt.END);
        holder.summary.setContentDescription("Imagens anexadas");
        line.addView(holder.summary,new LinearLayout.LayoutParams(0,-2,1));
        holder.detachAll=new Button(activity);
        CompactUi.style(holder.detachAll);
        holder.detachAll.setText("Desanexar imagens");
        holder.detachAll.setContentDescription("Desanexar todas as imagens");
        line.addView(holder.detachAll,new LinearLayout.LayoutParams(-2,dp(activity,32)));
        bar.addView(line,new LinearLayout.LayoutParams(-1,-2));
        holder.chips=new LinearLayout(activity);
        holder.chips.setOrientation(LinearLayout.HORIZONTAL);
        HorizontalScrollView scroller=new HorizontalScrollView(activity);
        scroller.setHorizontalScrollBarEnabled(false);
        scroller.addView(holder.chips,new LinearLayout.LayoutParams(-2,-2));
        bar.addView(scroller,new LinearLayout.LayoutParams(-1,-2));
        bar.setVisibility(View.GONE);
        holder.bar=bar;
        final Holder created=holder;
        holder.detachAll.setOnClickListener(new View.OnClickListener(){
            @Override public void onClick(View v){detachAll(created.activity);}
        });
        root.addView(bar,root.indexOfChild(compose));
        HOLDERS.put(chatId(activity),holder);
        refresh(activity);
    }

    private static String chatId(Activity activity){
        String id=activity.getIntent()==null?null:activity.getIntent().getStringExtra("chatId");
        return id==null?"":id;
    }

    public static void refresh(final Activity activity){
        if(activity==null)return;
        if(Looper.myLooper()!=Looper.getMainLooper()){
            activity.runOnUiThread(new Runnable(){@Override public void run(){rebuild(activity);}});
            return;
        }
        rebuild(activity);
    }

    private static void rebuild(Activity activity){
        Holder holder=HOLDERS.get(chatId(activity));
        if(holder==null||activity.isDestroyed())return;
        try{
            JSONObject state=AttachmentStore.read(activity.getApplicationContext(),chatId(activity));
            ArrayList<JSONObject> found=images(state);
            if(found.isEmpty()){
                holder.bar.setVisibility(View.GONE);
                holder.shown=false;
                return;
            }
            int pending=0;
            for(JSONObject item:found)if(item.optInt("message",-1)<0)pending++;
            holder.summary.setText(found.size()+" imagem(ns) · "+pending+" pendente(s) · "
                +(found.size()-pending)+" enviada(s) · toque no ✕ para desanexar");
            holder.chips.removeAllViews();
            int shown=Math.min(found.size(),MAX_CHIPS);
            for(int i=0;i<shown;i++){
                final JSONObject item=found.get(i);
                final String id=item.getString("id");
                final int index=i+1;
                LinearLayout chip=new LinearLayout(activity);
                chip.setOrientation(LinearLayout.HORIZONTAL);
                chip.setGravity(Gravity.CENTER_VERTICAL);
                GradientDrawable box=new GradientDrawable();
                box.setColor(0xff152430);box.setCornerRadius(dp(activity,10));
                chip.setBackground(box);
                chip.setPadding(dp(activity,6),dp(activity,4),dp(activity,6),dp(activity,4));
                ImageView preview=new ImageView(activity);
                preview.setScaleType(ImageView.ScaleType.CENTER_CROP);
                Bitmap bitmap=thumbnail(activity,id,dp(activity,THUMB_DP));
                if(bitmap!=null)preview.setImageBitmap(bitmap);
                chip.addView(preview,new LinearLayout.LayoutParams(dp(activity,THUMB_DP),dp(activity,THUMB_DP)));
                TextView label=new TextView(activity);
                label.setTextSize(11);label.setTextColor(0xffc2d2de);label.setMaxWidth(dp(activity,90));
                label.setSingleLine(true);label.setEllipsize(TextUtils.TruncateAt.MIDDLE);
                label.setText((item.optInt("message",-1)<0?"":"")+item.optString("name","imagem"));
                LinearLayout.LayoutParams labelParams=new LinearLayout.LayoutParams(-2,-2);
                labelParams.setMargins(dp(activity,6),0,dp(activity,4),0);
                chip.addView(label,labelParams);
                Button remove=new Button(activity);
                remove.setText("✕");remove.setAllCaps(false);remove.setTextSize(13);
                remove.setMinWidth(0);remove.setMinimumWidth(0);remove.setMinHeight(0);remove.setMinimumHeight(0);
                remove.setPadding(0,0,0,0);
                remove.setContentDescription("Desanexar imagem "+index);
                remove.setLayoutParams(new LinearLayout.LayoutParams(dp(activity,32),dp(activity,32)));
                remove.setOnClickListener(new View.OnClickListener(){
                    @Override public void onClick(View v){confirm(activity,id,index);}
                });
                chip.addView(remove);
                LinearLayout.LayoutParams chipParams=new LinearLayout.LayoutParams(-2,-2);
                chipParams.setMargins(0,dp(activity,4),dp(activity,8),0);
                holder.chips.addView(chip,chipParams);
            }
            if(found.size()>shown){
                TextView more=new TextView(activity);
                more.setTextSize(11.5f);more.setTextColor(0xff9fb4c4);
                more.setText("+"+(found.size()-shown)+" …");
                holder.chips.addView(more);
            }
            holder.bar.setVisibility(View.VISIBLE);
            if(!holder.shown){
                holder.shown=true;
                Log.i(TAG,"GGUF_IMAGE_STRIP shown=1 images="+found.size()+" pending="+pending);
            }
        }catch(Exception ex){
            Log.i(TAG,"GGUF_IMAGE_STRIP_ERROR "+ex.getClass().getSimpleName());
        }
    }

    static Bitmap thumbnail(Context context,String id,int target){
        try{
            String chat=HOLDERS.isEmpty()?"":null;
            File file=null;
            for(Map.Entry<String,Holder> entry:HOLDERS.entrySet()){
                File candidate=new File(AttachmentStore.directory(context,entry.getKey()),id+".data");
                if(candidate.isFile()){file=candidate;break;}
            }
            if(file==null||!file.isFile())return null;
            BitmapFactory.Options bounds=new BitmapFactory.Options();
            bounds.inJustDecodeBounds=true;
            BitmapFactory.decodeFile(file.getAbsolutePath(),bounds);
            if(bounds.outWidth<=0||bounds.outHeight<=0)return null;
            int sample=1;
            while(bounds.outWidth/(sample*2)>=target&&bounds.outHeight/(sample*2)>=target)sample*=2;
            BitmapFactory.Options options=new BitmapFactory.Options();
            options.inSampleSize=sample;
            return BitmapFactory.decodeFile(file.getAbsolutePath(),options);
        }catch(Exception ex){return null;}
    }

    private static void confirm(final Activity activity,final String id,final int index){
        new AlertDialog.Builder(activity)
            .setTitle("Imagem "+index)
            .setMessage("Desanexar esta imagem desta conversa? A cópia privada e o vínculo com a mensagem são removidos, "
                +"então o modelo deixa de lê-la. O arquivo original no seu aparelho não é apagado.")
            .setPositiveButton("Desanexar",new android.content.DialogInterface.OnClickListener(){
                @Override public void onClick(android.content.DialogInterface dialog,int which){detach(activity,id);}
            })
            .setNegativeButton("Cancelar",null)
            .show();
    }

    /** Remove cópia privada e vínculo; nunca apaga o original escolhido pelo usuário. */
    public static void detach(Activity activity,String id){
        try{
            AttachmentStore.remove(activity.getApplicationContext(),chatId(activity),id);
            Log.i(TAG,"GGUF_IMAGE_DETACHED id="+id);
            toast(activity,"Imagem desanexada");
        }catch(Exception ex){
            toast(activity,"Não foi possível desanexar: "+ex.getMessage());
        }
        refresh(activity);
        Attachments.resume(activity);
    }

    public static void detachAll(final Activity activity){
        try{
            JSONObject state=AttachmentStore.read(activity.getApplicationContext(),chatId(activity));
            final ArrayList<String> ids=new ArrayList<String>();
            for(JSONObject item:images(state))ids.add(item.getString("id"));
            if(ids.isEmpty()){toast(activity,"Nenhuma imagem anexada");return;}
            new AlertDialog.Builder(activity)
                .setTitle("Desanexar "+ids.size()+" imagem(ns)?")
                .setMessage("Todas as imagens desta conversa serão desanexadas. Conversas, textos e arquivos originais não são alterados.")
                .setPositiveButton("Desanexar todas",new android.content.DialogInterface.OnClickListener(){
                    @Override public void onClick(android.content.DialogInterface dialog,int which){
                        int removed=0;
                        for(String id:ids)try{AttachmentStore.remove(activity.getApplicationContext(),chatId(activity),id);removed++;}
                        catch(Exception ex){Log.i(TAG,"GGUF_IMAGE_DETACH_FAILED id="+id);}
                        Log.i(TAG,"GGUF_IMAGES_DETACHED_ALL removed="+removed);
                        toast(activity,removed+" imagem(ns) desanexada(s)");
                        refresh(activity);Attachments.resume(activity);
                    }
                })
                .setNegativeButton("Cancelar",null)
                .show();
        }catch(Exception ex){toast(activity,"Não foi possível desanexar: "+ex.getMessage());}
    }

    private static void toast(Activity activity,String message){
        Toast.makeText(activity,message,Toast.LENGTH_SHORT).show();
    }
}
