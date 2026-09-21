package com.ggufchat.app;
import java.io.*;
/** Bounded content sniffing, independent of provider filenames/MIME. */
public final class ImageFormats {
 private static boolean at(byte[] b,int n,int offset,String text){
  if(offset+text.length()>n)return false;
  for(int i=0;i<text.length();i++)if((b[offset+i]&255)!=text.charAt(i))return false;
  return true;
 }
 public static boolean isImage(File file)throws IOException {
  byte[] b=new byte[64];int n=0;
  try(InputStream in=new FileInputStream(file)){int k;while(n<b.length&&(k=in.read(b,n,b.length-n))>0)n+=k;}
  return matches(b,n);
 }
 public static boolean matches(byte[] b,int n){
  if(n<0||n>b.length)throw new IllegalArgumentException("Invalid header length");
  if(n>=3&&(b[0]&255)==255&&(b[1]&255)==216&&(b[2]&255)==255)return true;
  if(at(b,n,0,"\u0089PNG\r\n\u001a\n")||at(b,n,0,"GIF87a")||at(b,n,0,"GIF89a"))return true;
  if(at(b,n,0,"RIFF")&&at(b,n,8,"WEBP"))return true;
  if(at(b,n,0,"II*\u0000")||at(b,n,0,"MM\u0000*"))return true;
  if(n>=26&&at(b,n,0,"BM")&&(b[14]==12||b[14]==40||b[14]==108||b[14]==124)&&b[15]==0&&b[16]==0&&b[17]==0)return true;
  if(at(b,n,4,"ftyp")){
   for(int i=8;i+4<=n;i+=4){
    if(i==12)continue; // minor version is not a compatible brand
    for(String brand:new String[]{"avif","avis","heic","heix","hevc","hevx","heim","heis","hevm","hevs","mif1","msf1"})
     if(at(b,n,i,brand))return true;
   }
  }
  return false;
 }
}
