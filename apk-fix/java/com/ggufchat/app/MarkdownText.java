package com.ggufchat.app;

import android.graphics.Typeface;
import android.text.Spannable;
import android.text.SpannableStringBuilder;
import android.text.style.BackgroundColorSpan;
import android.text.style.ForegroundColorSpan;
import android.text.style.StrikethroughSpan;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.widget.TextView;
import java.util.IdentityHashMap;
import java.util.Map;

/** Inline formatting for model output: **negrito**, *itálico*, `código`, ~~riscado~~.
 * Only inline spans: no HTML, no WebView, no executed content, no unbounded parser.
 * Streaming stays incremental: chunks without markers are appended untouched, so a
 * reply that never uses markers costs exactly the same as plain text.
 */
public final class MarkdownText {
    private static final int BOLD=1, ITALIC=2, CODE=4, STRIKE=8;
    private static final Map<TextView,StringBuilder> RAW=new IdentityHashMap<TextView,StringBuilder>();
    private static final Map<TextView,Boolean> STYLED=new IdentityHashMap<TextView,Boolean>();

    private MarkdownText(){}

    public static void clear(TextView view){
        RAW.remove(view);STYLED.remove(view);
    }

    /** Whole text at once (history rendering and non-streaming callers). */
    public static void set(TextView view,String text){
        StringBuilder buffer=new StringBuilder(text==null?"":text);
        RAW.put(view,buffer);
        if(!markers(text)){STYLED.put(view,Boolean.FALSE);view.setText(buffer.toString());return;}
        STYLED.put(view,Boolean.TRUE);
        view.setText(spans(buffer.toString()));
    }

    /** Streaming chunk. Fast path keeps plain replies allocation-free per token. */
    public static void append(TextView view,String chunk){
        if(chunk==null||chunk.length()==0)return;
        StringBuilder raw=RAW.get(view);
        if(raw==null){raw=new StringBuilder();RAW.put(view,raw);}
        raw.append(chunk);
        boolean previous=STYLED.get(view)==Boolean.TRUE;
        if(!previous&&!markers(chunk)){view.append(chunk);return;}
        STYLED.put(view,Boolean.TRUE);
        view.setText(spans(raw.toString()));
    }

    private static boolean markers(CharSequence text){
        if(text==null)return false;
        for(int i=0;i<text.length();i++){
            char c=text.charAt(i);
            if(c=='*'||c=='`'||c=='~'||c=='\\')return true;
        }
        return false;
    }

    private static void open(SpannableStringBuilder out,int start,int end,Object span){
        if(end>start)out.setSpan(span,start,end,Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
    }

    /** Visible text with inline spans. Marker characters are consumed, never shown. */
    public static CharSequence spans(String text){
        SpannableStringBuilder out=new SpannableStringBuilder();
        if(text==null||text.length()==0)return out;
        int state=0,start=0,codeStart=-1,boldStart=-1,italicStart=-1,strikeStart=-1;
        for(int i=0;i<text.length();i++){
            char c=text.charAt(i);
            if(c=='\\'&&i+1<text.length()){
                char next=text.charAt(i+1);
                if(next=='*'||next=='`'||next=='~'||next=='\\'){out.append(next);i++;continue;}
            }
            if(c=='`'){
                if((state&CODE)!=0){
                    open(out,codeStart,out.length(),new TypefaceSpan("monospace"));
                    open(out,codeStart,out.length(),new BackgroundColorSpan(0x332e2e2e));
                    state&=~CODE;
                }else{
                    codeStart=out.length();state|=CODE;
                }
                continue;
            }
            if((state&CODE)!=0){out.append(c);continue;}
            if(c=='*'){
                boolean doubleStar=i+1<text.length()&&text.charAt(i+1)=='*';
                boolean opens=(state&(BOLD|ITALIC))==0
                    ? (i+1<text.length()&&!(doubleStar? (i+2>=text.length()||text.charAt(i+2)==' ') : text.charAt(i+1)==' '))
                    : true; // closing markers are accepted as they arrive
                if(doubleStar){
                    if((state&BOLD)!=0){open(out,boldStart,out.length(),new StyleSpan(Typeface.BOLD));state&=~BOLD;}
                    else {boldStart=out.length();state|=BOLD;}
                    i++;
                }else{
                    if((state&ITALIC)!=0){open(out,italicStart,out.length(),new StyleSpan(Typeface.ITALIC));state&=~ITALIC;}
                    else {italicStart=out.length();state|=ITALIC;}
                }
                continue;
            }
            if(c=='~'&&i+1<text.length()&&text.charAt(i+1)=='~'){
                if((state&STRIKE)!=0){open(out,strikeStart,out.length(),new StrikethroughSpan());state&=~STRIKE;}
                else {strikeStart=out.length();state|=STRIKE;}
                i++;
                continue;
            }
            out.append(c);
        }
        // Streaming: an open marker keeps styling the tail until its closing marker
        // arrives, so no raw ** is ever shown to the user.
        if((state&BOLD)!=0)open(out,boldStart,out.length(),new StyleSpan(Typeface.BOLD));
        if((state&ITALIC)!=0)open(out,italicStart,out.length(),new StyleSpan(Typeface.ITALIC));
        if((state&STRIKE)!=0)open(out,strikeStart,out.length(),new StrikethroughSpan());
        if((state&CODE)!=0){
            open(out,codeStart,out.length(),new TypefaceSpan("monospace"));
            open(out,codeStart,out.length(),new BackgroundColorSpan(0x332e2e2e));
            open(out,codeStart,out.length(),new ForegroundColorSpan(0xFFD4D4D4));
        }
        return out;
    }

    /** Visible characters of a formatted string, for content descriptions and copy. */
    public static String visible(String text){
        return spans(text).toString();
    }
}
