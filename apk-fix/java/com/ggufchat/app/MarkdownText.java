package com.ggufchat.app;

import android.graphics.Typeface;
import android.text.Spannable;
import android.text.SpannableStringBuilder;
import android.text.style.BackgroundColorSpan;
import android.text.style.ForegroundColorSpan;
import android.text.style.RelativeSizeSpan;
import android.text.style.StrikethroughSpan;
import android.text.style.StyleSpan;
import android.text.style.SubscriptSpan;
import android.text.style.SuperscriptSpan;
import android.text.style.TypefaceSpan;
import android.text.style.UnderlineSpan;
import android.widget.TextView;
import java.util.IdentityHashMap;
import java.util.Map;

/** Inline formatting for model output:
 *  **negrito**, *itálico*, `código`, ~~riscado~~, __sublinhado__,
 *  ^sobrescrito, _subscrito, $expressão$.
 *
 * Only inline spans — no HTML, no WebView, no executed content, no unbounded parser.
 * Streaming stays incremental: chunks without markers are appended untouched, so a
 * reply that never uses markers costs exactly the same as plain text.
 *
 * Efeitos que esta classe cobre (pedidos do usuário):
 *  - Negrito (`**texto**`), itálico (`*texto*` ou `_texto_` quando não é subscrito);
 *  - Código inline (`` `texto` ``);
 *  - Tachado (`~~texto~~`);
 *  - Sublinhado (`__texto__`);
 *  - Sobrescrito: `x^2`, `p^+`, `x^(a+b)`, `H^{2}O`, e também `^^texto elevado^^`
 *    (equivalente ao ~~ que o usuário queria usar como expoente por falta da tecla
 *    ^ no teclado);
 *  - Subscrito: `H_2O`, `x_i`, `a_{n+1}` (sublinhado curto no meio de uma palavra);
 *  - Expressões LaTeX curtas `$...$` em monoespaçado com tom sutil (sem renderização
 *    real de equação — sem WebView).
 */
public final class MarkdownText {
    private static final int BOLD=1, ITALIC=2, CODE=4, STRIKE=8, UNDER=16, SUPER=32, SUB=64, MATH=128;
    private static final float SCRIPT_RATIO=0.7f;
    private static final Map<TextView,StringBuilder> RAW=new IdentityHashMap<TextView,StringBuilder>();
    private static final Map<TextView,Boolean> STYLED=new IdentityHashMap<TextView,Boolean>();

    private MarkdownText(){}

    public static void clear(TextView view){ RAW.remove(view);STYLED.remove(view); }

    public static void set(TextView view,String text){
        StringBuilder buffer=new StringBuilder(text==null?"":text);
        RAW.put(view,buffer);
        if(!markers(text)){STYLED.put(view,Boolean.FALSE);view.setText(buffer.toString());return;}
        STYLED.put(view,Boolean.TRUE);
        view.setText(spans(buffer.toString()));
    }

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
            if(c=='*'||c=='`'||c=='~'||c=='\\'||c=='^'||c=='_'||c=='$')return true;
        }
        return false;
    }

    private static void open(SpannableStringBuilder out,int start,int end,Object span){
        if(end>start)out.setSpan(span,start,end,Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
    }

    private static boolean isWordChar(char c){
        return Character.isLetterOrDigit(c)||c=='+'||c=='-'||c=='='||c=='/'||c=='.';
    }

    public static CharSequence spans(String text){
        SpannableStringBuilder out=new SpannableStringBuilder();
        if(text==null||text.length()==0)return out;
        int state=0;
        int codeStart=-1,boldStart=-1,italicStart=-1,strikeStart=-1;
        int underlineStart=-1,superStart=-1,subStart=-1,mathStart=-1;
        // Super/sub curtos (^x / _x) têm fechamento implícito por separador;
        // super/sub duplos (^^x^^, __x__) exigem o par de marcadores.
        boolean superDouble=false,subDouble=false;
        int i=0,n=text.length();
        while(i<n){
            char c=text.charAt(i);
            // Fechamento implícito de script CURTO quando o próximo caractere é
            // separador OU é um marcador que inicia outro estilo. O fechamento
            // acontece ANTES de consumir o caractere, para que ele não fique
            // elevado/subscrito por engano.
            if(((state&SUPER)!=0&&!superDouble)||((state&SUB)!=0&&!subDouble)){
                boolean atEnd=(i+1>=n);
                char next=atEnd?' ':text.charAt(i+1);
                boolean closeNow=false;
                if(c=='\\'||c=='`'||c=='$'){ closeNow=true; }
                else if(c=='*'){ closeNow=true; }
                else if(c=='~'){ closeNow=true; }
                else if(c=='^'){ closeNow=!(i+1<n&&text.charAt(i+1)=='^'); }
                else if(c=='_'){ closeNow=!(i+1<n&&text.charAt(i+1)=='_'); }
                else if(!isWordChar(c)&&c!='('&&c!='['&&c!='{'){ closeNow=true; }
                if(closeNow||atEnd){
                    if((state&SUPER)!=0){applyScript(out,superStart,true);state&=~SUPER;superDouble=false;}
                    if((state&SUB)!=0){applyScript(out,subStart,false);state&=~SUB;subDouble=false;}
                    if(atEnd)break;
                }
            }
            // Escape de marcador: \* \` \~ \^ \_ \$ \\
            if(c=='\\'&&i+1<n){
                char next=text.charAt(i+1);
                if(next=='*'||next=='`'||next=='~'||next=='\\'||next=='^'||next=='_'||next=='$'){
                    out.append(next);i+=2;continue;
                }
            }
            // Código inline (`...`) vence outros marcadores.
            if(c=='`'&&(state&CODE)==0&&(state&MATH)==0){
                codeStart=out.length();state|=CODE;i++;continue;
            }
            if(c=='`'&&(state&CODE)!=0){
                open(out,codeStart,out.length(),new TypefaceSpan("monospace"));
                open(out,codeStart,out.length(),new BackgroundColorSpan(0x332e2e2e));
                open(out,codeStart,out.length(),new ForegroundColorSpan(0xFFD4D4D4));
                state&=~CODE;i++;continue;
            }
            if((state&CODE)!=0){out.append(c);i++;continue;}
            // LaTeX/math $...$ (mono, tom suave).
            if(c=='$'&&(state&MATH)==0){mathStart=out.length();state|=MATH;i++;continue;}
            if(c=='$'&&(state&MATH)!=0){
                open(out,mathStart,out.length(),new TypefaceSpan("monospace"));
                open(out,mathStart,out.length(),new BackgroundColorSpan(0x22B7C7D1));
                open(out,mathStart,out.length(),new ForegroundColorSpan(0xFFB7C7D1));
                state&=~MATH;i++;continue;
            }
            if((state&MATH)!=0){out.append(c);i++;continue;}
            // Sublinhado __...__
            if(c=='_'&&i+1<n&&text.charAt(i+1)=='_'&&(state&UNDER)==0){
                underlineStart=out.length();state|=UNDER;i+=2;continue;
            }
            if(c=='_'&&i+1<n&&text.charAt(i+1)=='_'&&(state&UNDER)!=0){
                open(out,underlineStart,out.length(),new UnderlineSpan());state&=~UNDER;i+=2;continue;
            }
            // Tachado ~~...~~
            if(c=='~'&&i+1<n&&text.charAt(i+1)=='~'&&(state&STRIKE)==0){
                strikeStart=out.length();state|=STRIKE;i+=2;continue;
            }
            if(c=='~'&&i+1<n&&text.charAt(i+1)=='~'&&(state&STRIKE)!=0){
                open(out,strikeStart,out.length(),new StrikethroughSpan());state&=~STRIKE;i+=2;continue;
            }
            // Negrito **...**
            if(c=='*'&&i+1<n&&text.charAt(i+1)=='*'&&(state&BOLD)==0){
                boldStart=out.length();state|=BOLD;i+=2;continue;
            }
            if(c=='*'&&i+1<n&&text.charAt(i+1)=='*'&&(state&BOLD)!=0){
                open(out,boldStart,out.length(),new StyleSpan(Typeface.BOLD));state&=~BOLD;i+=2;continue;
            }
            // Sobrescrito ^^...^^ (bloco)
            if(c=='^'&&i+1<n&&text.charAt(i+1)=='^'&&(state&SUPER)==0){
                superStart=out.length();state|=SUPER;superDouble=true;i+=2;continue;
            }
            if(c=='^'&&i+1<n&&text.charAt(i+1)=='^'&&(state&SUPER)!=0&&superDouble){
                applyScript(out,superStart,true);state&=~SUPER;superDouble=false;i+=2;continue;
            }
            // Sobrescrito curto ^x, ^+, ^(...), ^{...}
            if(c=='^'&&(state&SUPER)==0&&i+1<n&&text.charAt(i+1)!='^'&&text.charAt(i+1)!=' '){
                superStart=out.length();state|=SUPER;superDouble=false;i++;continue;
            }
            // Itálico *...*
            if(c=='*'&&(state&BOLD)==0){
                if((state&ITALIC)!=0){
                    open(out,italicStart,out.length(),new StyleSpan(Typeface.ITALIC));state&=~ITALIC;
                }else{italicStart=out.length();state|=ITALIC;}
                i++;continue;
            }
            // Itálico _..._  vs  subscrito curto _x
            if(c=='_'&&(state&ITALIC)==0){
                // Fechamento de itálico por _ único:
                if((state&ITALIC)==0&&out.length()>0){
                    boolean wordBefore=Character.isLetterOrDigit(out.charAt(out.length()-1));
                    char next=i+1<n?text.charAt(i+1):' ';
                    boolean subCandidate=wordBefore&&(Character.isLetterOrDigit(next)||next=='('||next=='['||next=='{');
                    if(!subCandidate&&(state&SUB)==0){
                        italicStart=out.length();state|=ITALIC;i++;continue;
                    }
                }else if((state&ITALIC)!=0){
                    open(out,italicStart,out.length(),new StyleSpan(Typeface.ITALIC));state&=~ITALIC;i++;continue;
                }
                // Subscrito curto: só no meio de palavra, com próximo caractere
                // alfanumérico ou grupo (parênteses/chaves/colchetes).
                if((state&SUB)==0&&out.length()>0&&Character.isLetterOrDigit(out.charAt(out.length()-1))
                   &&i+1<n&&text.charAt(i+1)!='_'&&text.charAt(i+1)!=' '){
                    subStart=out.length();state|=SUB;subDouble=false;i++;continue;
                }
                // Caso contrário, é underline literal.
                out.append(c);i++;continue;
            }
            out.append(c);i++;
        }
        // Spans abertos ao fim do buffer (streaming): estilizam o restante como o
        // negrito já fazia — nenhum ** cru aparece na tela.
        if((state&BOLD)!=0)open(out,boldStart,out.length(),new StyleSpan(Typeface.BOLD));
        if((state&ITALIC)!=0)open(out,italicStart,out.length(),new StyleSpan(Typeface.ITALIC));
        if((state&STRIKE)!=0)open(out,strikeStart,out.length(),new StrikethroughSpan());
        if((state&UNDER)!=0)open(out,underlineStart,out.length(),new UnderlineSpan());
        if((state&SUPER)!=0)applyScript(out,superStart,true);
        if((state&SUB)!=0)applyScript(out,subStart,false);
        if((state&CODE)!=0){
            open(out,codeStart,out.length(),new TypefaceSpan("monospace"));
            open(out,codeStart,out.length(),new BackgroundColorSpan(0x332e2e2e));
            open(out,codeStart,out.length(),new ForegroundColorSpan(0xFFD4D4D4));
        }
        if((state&MATH)!=0){
            open(out,mathStart,out.length(),new TypefaceSpan("monospace"));
            open(out,mathStart,out.length(),new BackgroundColorSpan(0x22B7C7D1));
            open(out,mathStart,out.length(),new ForegroundColorSpan(0xFFB7C7D1));
        }
        return out;
    }

    private static void applyScript(SpannableStringBuilder out,int start,boolean superscript){
        if(start<0||start>=out.length())return;
        open(out,start,out.length(),superscript?new SuperscriptSpan():new SubscriptSpan());
        open(out,start,out.length(),new RelativeSizeSpan(SCRIPT_RATIO));
    }

    public static String visible(String text){ return spans(text).toString(); }
}
