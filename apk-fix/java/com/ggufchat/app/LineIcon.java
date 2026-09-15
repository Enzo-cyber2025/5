package com.ggufchat.app;
import android.graphics.*;
import android.graphics.drawable.Drawable;
import android.widget.Button;
import java.util.Locale;

/** Resolution-independent outline icons drawn with public Canvas/Path APIs.
 * Geometric artwork, no emoji font, network asset or hidden Android API. */
public final class LineIcon extends Drawable {
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);private final String kind;
    public LineIcon(String kind){this.kind=kind;paint.setColor(0xffdcece6);paint.setStrokeWidth(1.7f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);paint.setStyle(Paint.Style.STROKE);}
    private void line(Canvas c,float... xy){Path p=new Path();p.moveTo(xy[0],xy[1]);for(int i=2;i<xy.length;i+=2)p.lineTo(xy[i],xy[i+1]);c.drawPath(p,paint);}
    @Override public void draw(Canvas c){int save=c.save();Rect b=getBounds();c.translate(b.left,b.top);c.scale(b.width()/24f,b.height()/24f);
        switch(kind){
            case "folder":line(c,3,7,3,20,21,20,21,7,12,7,10,4,3,4,3,7);break;
            case "chat":line(c,4,4,20,4,20,17,10,17,4,21,4,4);line(c,8,9,16,9);line(c,8,13,14,13);break;
            case "camera":line(c,3,7,7,7,9,4,15,4,17,7,21,7,21,20,3,20,3,7);c.drawCircle(12,13,4,paint);break;
            case "attach":line(c,8,15,15,8,17,10,9,18,6,18,4,16,4,12,13,3,17,3,21,7,21,11,11,21);break;
            case "tools":line(c,14,3,13,8,17,11,21,9,20,14,16,15,7,22,2,17,10,9,9,5,14,3);break;
            case "send":line(c,3,3,22,12,3,21,6,12,3,3);line(c,6,12,22,12);break;
            case "delete":line(c,3,6,21,6);line(c,8,6,8,3,16,3,16,6);line(c,6,6,7,21,17,21,18,6);line(c,10,10,10,17);line(c,14,10,14,17);break;
            case "settings":line(c,3,6,21,6);line(c,3,12,21,12);line(c,3,18,21,18);c.drawCircle(8,6,2,paint);c.drawCircle(16,12,2,paint);c.drawCircle(10,18,2,paint);break;
            case "model":c.drawRoundRect(5,5,19,19,3,3,paint);c.drawRect(9,9,15,15,paint);for(int i=8;i<=16;i+=4){line(c,i,2,i,5);line(c,i,19,i,22);line(c,2,i,5,i);line(c,19,i,22,i);}break;
            case "download":line(c,12,3,12,16);line(c,7,11,12,16,17,11);line(c,4,17,4,21,20,21,20,17);break;
            default:c.drawCircle(12,12,8,paint);line(c,8,12,16,12);line(c,12,8,12,16);
        }c.restoreToCount(save);
    }
    @Override public void setAlpha(int a){paint.setAlpha(a);invalidateSelf();}
    @Override public void setColorFilter(ColorFilter f){paint.setColorFilter(f);invalidateSelf();}
    @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    public static void apply(Button b){
        String original=b.getText().toString();String desc=b.getContentDescription()==null?"":b.getContentDescription().toString();
        String hint=(original+" "+desc).toLowerCase(Locale.ROOT);String kind=null;
        if(hint.contains("ferrament")||hint.contains("🔧"))kind="tools";
        else if(hint.contains("câmera")||hint.contains("camera")||hint.contains("foto")||hint.contains("📷"))kind="camera";
        else if(hint.contains("anex")||hint.contains("📎"))kind="attach";
        else if(hint.contains("enviar"))kind="send";
        else if(hint.contains("excluir"))kind="delete";
        else if(hint.contains("ajuste")||hint.contains("configura"))kind="settings";
        else if(hint.contains("importar"))kind="folder";
        else if(hint.contains("modelo"))kind="model";
        else if(hint.contains("chat")||hint.contains("conversa"))kind="chat";
        else if(hint.contains("baixar"))kind="download";
        String clean=original.replaceAll("[\\x{1F000}-\\x{1FAFF}\\x{2600}-\\x{27BF}\\x{FE0F}\\x{200D}]","").trim();
        if(!clean.equals(original))b.setText(clean);
        if(kind==null)return;
        if(desc.isEmpty())b.setContentDescription(clean.isEmpty()?kind:clean);
        int size=Math.round(17*b.getResources().getDisplayMetrics().density);LineIcon icon=new LineIcon(kind);icon.setBounds(0,0,size,size);
        if(!b.isEnabled())icon.setAlpha(90);
        b.setCompoundDrawablePadding(Math.round(6*b.getResources().getDisplayMetrics().density));b.setCompoundDrawablesRelative(icon,null,null,null);
    }
}
