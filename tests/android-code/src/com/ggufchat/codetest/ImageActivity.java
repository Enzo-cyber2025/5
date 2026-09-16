package com.ggufchat.codetest;
import android.app.Activity;
import android.os.Bundle;
import android.content.Context;
import android.graphics.*;
import android.media.ExifInterface;
import android.widget.TextView;
import android.util.Log;
import java.io.*;
import java.lang.reflect.*;
/** Real Android decoder tests of the installed APK, not model inference. */
public final class ImageActivity extends Activity {
 Method decode,sniff;
 void require(boolean b,String detail){if(!b)throw new AssertionError(detail);}
 File write(Bitmap b,String name,Bitmap.CompressFormat format)throws Exception {
  File f=new File(getCacheDir(),name);try(FileOutputStream out=new FileOutputStream(f)){require(b.compress(format,100,out),"encode");}b.recycle();return f;
 }
 Bitmap read(File f)throws Exception {require((Boolean)sniff.invoke(null,f),"sniff content "+f.getName());return (Bitmap)decode.invoke(null,f);}
 protected void onCreate(Bundle state){super.onCreate(state);TextView text=new TextView(this);text.setPadding(20,60,20,20);setContentView(text);
  new Thread(()->{try{
   Context app=createPackageContext("com.ggufchat.app",CONTEXT_INCLUDE_CODE|CONTEXT_IGNORE_SECURITY);
   decode=app.getClassLoader().loadClass("com.ggufchat.app.ImagePixels").getMethod("decode",File.class);
   sniff=app.getClassLoader().loadClass("com.ggufchat.app.ImageFormats").getMethod("isImage",File.class);
   Bitmap b=Bitmap.createBitmap(2,1,Bitmap.Config.ARGB_8888);b.setPixel(1,0,Color.BLUE);
   b=read(write(b,"opaque-provider-data",Bitmap.CompressFormat.PNG));
   require(b.getPixel(0,0)==Color.WHITE&&b.getPixel(1,0)==Color.BLUE,"alpha compositing");b.recycle();
   b=Bitmap.createBitmap(1025,513,Bitmap.Config.ARGB_8888);b.eraseColor(Color.RED);
   b=read(write(b,"large.data",Bitmap.CompressFormat.PNG));require(b.getWidth()==1024&&b.getHeight()==512,"target-sized decode");b.recycle();
   b=Bitmap.createBitmap(20,40,Bitmap.Config.ARGB_8888);b.eraseColor(Color.BLUE);File jpeg=write(b,"camera.data",Bitmap.CompressFormat.JPEG);
   ExifInterface exif=new ExifInterface(jpeg.getAbsolutePath());exif.setAttribute(ExifInterface.TAG_ORIENTATION,"6");exif.saveAttributes();
   b=read(jpeg);require(b.getWidth()==40&&b.getHeight()==20,"EXIF rotation");b.recycle();
   File broken=new File(getCacheDir(),"broken.jpg");try(FileOutputStream out=new FileOutputStream(broken)){out.write(new byte[]{(byte)255,(byte)216,(byte)255,0});}
   boolean rejected=false;try{Bitmap bad=(Bitmap)decode.invoke(null,broken);bad.recycle();}catch(InvocationTargetException expected){rejected=expected.getCause() instanceof IOException;}
   require(rejected,"corrupt photo must be rejected");
   Log.i("GGUFImageTest","IMAGE_DECODER_PASS unknown_name=1 alpha_white=1 size_1024=1 exif_6=1 corrupt_rejected=1 source="+app.getApplicationInfo().sourceDir);
   runOnUiThread(()->text.setText("Imagens OK: conteúdo sem extensão, transparência, 1024 px, EXIF e arquivo corrompido."));
  }catch(Throwable e){Log.e("GGUFImageTest","IMAGE_DECODER_FAIL",e);runOnUiThread(()->text.setText("Imagens FALHOU: "+e));}}).start();
 }
}
