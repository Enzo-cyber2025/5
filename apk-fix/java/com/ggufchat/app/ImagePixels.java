package com.ggufchat.app;
import android.graphics.*;
import java.io.*;
/** Android 9+ decoder: orientation, target-sized software pixels and sRGB. */
public final class ImagePixels {
 public static Bitmap decode(File file)throws IOException {
  Bitmap bitmap=ImageDecoder.decodeBitmap(ImageDecoder.createSource(file),(decoder,info,source)->{
   int w=info.getSize().getWidth(),h=info.getSize().getHeight();
   if(w<=0||h<=0)throw new IllegalArgumentException("Dimensões inválidas");
   decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);
   decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB));
   double scale=Math.min(1.0,1024.0/Math.max(w,h));
   if(scale<1.0)decoder.setTargetSize(Math.max(1,(int)Math.round(w*scale)),Math.max(1,(int)Math.round(h*scale)));
   decoder.setOnPartialImageListener(error->false); // never accept a truncated photo silently
  });
  // A transparent screenshot otherwise becomes black when the native RGB reader
  // drops alpha. Composite explicitly against white; originals stay untouched.
  if(bitmap.hasAlpha()||bitmap.getConfig()!=Bitmap.Config.ARGB_8888){
   Bitmap rgb=null;
   try {
    rgb=Bitmap.createBitmap(bitmap.getWidth(),bitmap.getHeight(),Bitmap.Config.ARGB_8888);
    Canvas canvas=new Canvas(rgb);canvas.drawColor(Color.WHITE);canvas.drawBitmap(bitmap,0,0,null);
   }catch(RuntimeException|OutOfMemoryError e){if(rgb!=null)rgb.recycle();throw e;}
   finally{bitmap.recycle();}
   bitmap=rgb;
  }
  return bitmap;
 }
}
