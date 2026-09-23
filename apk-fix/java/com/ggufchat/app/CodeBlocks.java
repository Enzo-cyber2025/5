package com.ggufchat.app;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/** Native code panels; exact copy, selectable monospace text, horizontal scrolling. */
public final class CodeBlocks {
    private static int dp(Context c,int n){return Math.round(c.getResources().getDisplayMetrics().density*n);}
    private static GradientDrawable box(Context c,int color){
        GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(c,12));return d;
    }
    private static final class Stream implements CodeFenceParser.Sink {
        final Context c;final TextView style;final LinearLayout root;final CodeFenceParser parser;
        TextView plain,code,title;String declared="";
        TextView pendingTarget;
        String pendingFirst;
        StringBuilder pendingBatch;
        // A normal single-line token needs no extra copy/allocation. Allocate a
        // join buffer only when the parser emits multiple runs to the SAME view.
        void enqueue(TextView target,String text){
            if(text.length()==0)return;
            if(target!=pendingTarget)flush();
            pendingTarget=target;
            if(pendingFirst==null)pendingFirst=text;
            else {
                if(pendingBatch==null)pendingBatch=new StringBuilder();
                if(pendingBatch.length()==0)pendingBatch.append(pendingFirst);
                pendingBatch.append(text);
            }
        }
        void flush(){
            if(pendingFirst==null)return;
            String text=pendingBatch!=null&&pendingBatch.length()>0?pendingBatch.toString():pendingFirst;
            // Bold/italic/inline code only outside code panels; one edit per burst.
            MarkdownText.append(pendingTarget,text);
            pendingFirst=null;pendingTarget=null;
            if(pendingBatch!=null)pendingBatch.setLength(0);
        }
        final boolean live;boolean mounted;
        Stream(TextView source){this(source,false);}
        Stream(TextView source,boolean live){
            this.live=live;style=source;c=source.getContext();root=new LinearLayout(c);root.setOrientation(LinearLayout.VERTICAL);
            parser=new CodeFenceParser(this);
            if(live)plain=source;
        }
        void mount(){
            if(!live || mounted)return;
            ViewGroup parent=(ViewGroup)style.getParent();
            int index=parent.indexOfChild(style);
            ViewGroup.LayoutParams params=style.getLayoutParams();
            parent.removeViewAt(index);parent.addView(root,index,params);
            if(style.length()>0)root.addView(style,new LinearLayout.LayoutParams(-1,-2));
            mounted=true;
        }
        TextView plain(){
            if(plain==null){
                plain=new TextView(c);plain.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX,style.getTextSize());
                plain.setTextColor(style.getTextColors());plain.setTypeface(style.getTypeface());plain.setTextIsSelectable(true);
                plain.setPadding(style.getPaddingLeft(),style.getPaddingTop(),style.getPaddingRight(),style.getPaddingBottom());
                Drawable bg=style.getBackground();if(bg!=null&&bg.getConstantState()!=null)plain.setBackground(bg.getConstantState().newDrawable(c.getResources()));
                root.addView(plain,new LinearLayout.LayoutParams(-1,-2));
            }
            return plain;
        }
        public void text(String text){enqueue(plain(),text);}
        public void open(String language){
            flush(); // Mount must see preceding plain text, even in this chunk.
            mount();plain=null;
            LinearLayout panel=new LinearLayout(c);panel.setOrientation(LinearLayout.VERTICAL);panel.setBackground(box(c,0xff101b23));
            panel.setContentDescription("Bloco de código");
            LinearLayout.LayoutParams pp=new LinearLayout.LayoutParams(-1,-2);pp.setMargins(0,dp(c,6),0,dp(c,6));root.addView(panel,pp);
            LinearLayout bar=new LinearLayout(c);bar.setGravity(Gravity.CENTER_VERTICAL);bar.setPadding(dp(c,12),dp(c,4),dp(c,6),dp(c,4));
            TextView title=new TextView(c);title.setText(language.length()==0?"Código":language);title.setTextColor(0xffadbdcc);title.setTextSize(12);
            title.setSingleLine(true);title.setEllipsize(TextUtils.TruncateAt.END);bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
            this.title=title;declared=language;
            final TextView body=new TextView(c);code=body;body.setTextColor(0xffe2eaf2);body.setTextSize(13);body.setTypeface(Typeface.MONOSPACE);
            body.setTextIsSelectable(true);body.setHorizontallyScrolling(true);body.setPadding(dp(c,12),dp(c,12),dp(c,12),dp(c,14));
            Button copy=new Button(c);copy.setText("Copiar");copy.setAllCaps(false);copy.setTextSize(12);copy.setTextColor(0xffd3eee2);
            copy.setMinWidth(0);copy.setMinimumWidth(0);copy.setMinHeight(dp(c,40));copy.setMinimumHeight(dp(c,40));
            copy.setBackground(box(c,0xff244234));copy.setContentDescription("Copiar código");
            copy.setOnClickListener(new View.OnClickListener(){public void onClick(View v){
                ClipboardManager clipboard=(ClipboardManager)c.getSystemService(Context.CLIPBOARD_SERVICE);
                if(clipboard!=null){clipboard.setPrimaryClip(ClipData.newPlainText("Código",body.getText().toString()));Toast.makeText(c,"Código copiado",Toast.LENGTH_SHORT).show();}
            }});
            bar.addView(copy,new LinearLayout.LayoutParams(dp(c,82),dp(c,40)));panel.addView(bar,new LinearLayout.LayoutParams(-1,-2));
            HorizontalScrollView scroller=new HorizontalScrollView(c);scroller.setFillViewport(false);scroller.setHorizontalScrollBarEnabled(true);
            scroller.addView(body,new ViewGroup.LayoutParams(-2,-2));panel.addView(scroller,new LinearLayout.LayoutParams(-1,-2));
        }
        public void code(String text){enqueue(code,text);}
        public void close(){
            flush();
            if(code!=null&&declared.length()==0){
                String detected=CodeDetect.language(code.getText().toString());
                if(detected.length()>0&&title!=null){
                    title.setText(detected);
                    panel().setContentDescription("Bloco de código ("+detected+")");
                }
            }
            code=null;plain=null;
        }
        LinearLayout panel(){return (LinearLayout)title.getParent().getParent();}
    }
    public static void decorate(LinearLayout column,boolean user){
        if(user)return;
        for(int i=0;i<column.getChildCount();i++){
            View child=column.getChildAt(i);if(!(child instanceof TextView))continue;
            TextView source=(TextView)child;String text=source.getText().toString();
            text=CodeDetect.fenced(text);
            if(!text.contains("```")&&!text.contains("~~~"))continue;
            Stream stream=new Stream(source);stream.parser.feed(text);stream.parser.finish();stream.flush();
            ViewGroup.LayoutParams params=source.getLayoutParams();column.removeViewAt(i);column.addView(stream.root,i,params);
        }
    }
    public static void append(TextView anchor,String chunk){
        Object tag=anchor.getTag();Stream stream;
        if(tag instanceof Stream)stream=(Stream)tag;
        else {
            if(!(anchor.getParent() instanceof ViewGroup)){anchor.append(chunk);return;}
            // Plain replies stay on the original TextView: no extra hierarchy,
            // no replacement selectable view, and no full-response reparsing.
            String initial=anchor.getText().toString();
            stream=new Stream(anchor,true);anchor.setTag(stream);
            if(initial.length()>0){anchor.setText("");stream.parser.feed(initial);}
        }
        stream.parser.feed(chunk);
        stream.flush(); // Synchronous: no timer, token throttle or first-text delay.
    }

    /** Coluna externa da mensagem em streaming (o balão), mesmo depois de o
     * renderizador de código mover a View para dentro do seu próprio painel. */
    public static LinearLayout column(TextView anchor){
        if(anchor==null)return null;
        android.view.ViewParent parent=anchor.getParent();
        if(!(parent instanceof LinearLayout))return null;
        if(anchor.getTag() instanceof Stream){
            android.view.ViewParent outer=parent.getParent();
            if(outer instanceof LinearLayout)return (LinearLayout)outer;
        }
        return (LinearLayout)parent;
    }
}
