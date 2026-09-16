package com.ggufchat.codetest;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.content.Context;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.graphics.Color;
import android.util.Log;
import android.view.View;
import android.widget.*;
import java.lang.reflect.Method;

/** Disposable Android component test; loads renderer from the installed production DEX.
 * The fixture is explicitly UI test data, NOT a generated model answer.
 */
public final class CodeActivity extends Activity {
 static final String PY="def saudacao(nome):\n    return \"Olá, \" + nome\n\nprint(saudacao(\"ação\"))\n";
 static final String JSON="{\"literal\": \"<script>not executed</script>\", \"longLine\": \"abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz\"}\n";
 static final String FIXTURE="Renderizador real — dados de teste, não inferência.\n```python\n"+PY+"```\nEntre os blocos.\n```json\n"+JSON+"```\nFim do teste.";
 TextView status,anchor;LinearLayout column;Method append,decorate;int offset;
 protected void onCreate(Bundle b){super.onCreate(b);
  try {
   Context app=createPackageContext("com.ggufchat.app",Context.CONTEXT_INCLUDE_CODE|Context.CONTEXT_IGNORE_SECURITY);
   Class<?> renderer=app.getClassLoader().loadClass("com.ggufchat.app.CodeBlocks");
   append=renderer.getMethod("append",TextView.class,String.class);
   decorate=renderer.getMethod("decorate",LinearLayout.class,boolean.class);
   Log.i("GGUFCodeTest","sourceApk="+app.getApplicationInfo().sourceDir);
   LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(16,35,16,12);root.setBackgroundColor(0xff09120e);
   status=new TextView(this);status.setText("Renderer do APK instalado");root.addView(status);
   Button py=new Button(this);py.setText("Conferir Python");root.addView(py);py.setOnClickListener(v->check(PY,"Python"));
   Button js=new Button(this);js.setText("Conferir JSON");root.addView(js);js.setOnClickListener(v->check(JSON,"JSON"));
   ScrollView scroll=new ScrollView(this);column=new LinearLayout(this);column.setOrientation(1);scroll.addView(column);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
   anchor=new TextView(this);anchor.setTextColor(Color.WHITE);anchor.setTextSize(14);anchor.setPadding(10,10,10,10);column.addView(anchor,new LinearLayout.LayoutParams(-1,-2));setContentView(root);
   if("plain".equals(getIntent().getStringExtra("mode"))){
    String part="Texto comum com ação, espaços e `literal`. ";StringBuilder expected=new StringBuilder();
    for(int i=0;i<256;i++){append.invoke(null,anchor,part);expected.append(part);}
    if(column.getChildCount()!=1 || column.getChildAt(0)!=anchor || !expected.toString().contentEquals(anchor.getText()))throw new AssertionError("Plain streaming changed view or text");
    status.setText("Texto simples OK");Log.i("GGUFCodeTest","PLAIN_ORIGINAL_VIEW_EXACT_PASS");
   }
   else if("history".equals(getIntent().getStringExtra("mode"))){anchor.setText(FIXTURE);decorate.invoke(null,column,false);status.setText("Histórico pronto");}
   else new Handler().post(new Runnable(){public void run(){try{
    int end=Math.min(FIXTURE.length(),offset+7);append.invoke(null,anchor,FIXTURE.substring(offset,end));offset=end;
    if(offset<FIXTURE.length())new Handler().postDelayed(this,16);else status.setText("Streaming pronto");
   }catch(Exception e){throw new RuntimeException(e);}}});
  }catch(Exception e){throw new RuntimeException(e);}
 }
 void check(String expected,String label){
  ClipboardManager cm=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);ClipData clip=cm.getPrimaryClip();
  boolean ok=clip!=null&&clip.getItemCount()==1&&expected.contentEquals(clip.getItemAt(0).getText())&&clip.getItemAt(0).getHtmlText()==null;
  status.setText("Cópia "+label+(ok?" OK":" FALHOU"));Log.i("GGUFCodeTest","COPY "+label+" exact="+ok);
 }
}
