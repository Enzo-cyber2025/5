package com.ggufchat.texttest;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.Spanned;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.lang.reflect.Method;
import java.util.List;

/** Disposable Android fixture: runs the renderer and parsers installed in the real
 * APK. The fixture text is explicit UI test data, never a generated answer.
 */
public final class TextActivity extends Activity {
    static final String TAG="GGUFTextTest";
    static final String BOLD_FIXTURE="Resposta com **negrito**, *itálico* e `código` inline.\n";
    static final String REASONING="passo 1: somar\npasso 2: conferir";
    static final String ANSWER="A resposta final é 4.\n";
    static final String INDENTED="Veja o trecho:\n\n    def soma(a, b):\n        return a + b\n\n    print(soma(2, 2))\n\nFim.\n";
    static final String DDG_HTML="<a class=\"result__a\" href=\"//duckduckgo.com/l/?uddg=https%3A%2F%2Fpt.wikipedia.org%2Fwiki%2FBrasil\">Brasil &#8211; Wikip&#233;dia</a>\n"
        +"<a class=\"result__snippet\" href=\"x\">Pa&#237;s da Am&#233;rica do Sul &amp; detalhes</a>\n"
        +"<a class=\"result__a\" href=\"https://example.org/b\">Segundo resultado</a>\n"
        +"<a class=\"result__snippet\" href=\"x\">Trecho dois</a>\n";
    static final String SEARX_JSON="{\"results\":[{\"title\":\"Brasil\",\"url\":\"https://pt.wikipedia.org/wiki/Brasil\","
        +"\"content\":\"País da América do Sul\"},{\"title\":\"Brasília\",\"url\":\"https://pt.wikipedia.org/wiki/Bras%C3%ADlia\","
        +"\"content\":\"Capital federal\"}]}";
    static final String WIKI_JSON="{\"query\":{\"search\":[{\"title\":\"Brasil\",\"snippet\":\"País da <b>América</b> do Sul\"},"
        +"{\"title\":\"Brasília\",\"snippet\":\"Capital federal do Brasil\"}]}}";
    static final String SOURCES_JSON="{\"query\":\"capital do Brasil\",\"provider\":\"Wikipédia\",\"error\":null,\"ms\":412,"
        +"\"hits\":[{\"title\":\"Brasília\",\"url\":\"https://pt.wikipedia.org/wiki/Bras%C3%ADlia\",\"snippet\":\"Capital federal do Brasil\"},"
        +"{\"title\":\"Brasil\",\"url\":\"https://pt.wikipedia.org/wiki/Brasil\",\"snippet\":\"País da América do Sul\"}]}";

    private TextView status;
    private final StringBuilder report=new StringBuilder();

    @Override protected void onCreate(Bundle state){
        super.onCreate(state);
        Log.i(TAG,"TEXT_RENDER_START sdk="+android.os.Build.VERSION.SDK_INT);
        LinearLayout root=new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(16,35,16,12);
        root.setBackgroundColor(0xff09120e);
        status=new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setText("Teste de texto");
        root.addView(status);
        ScrollView scroll=new ScrollView(this);
        LinearLayout column=new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(column);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);
        try{
            ClassLoader loader=productionLoader();
            Log.i(TAG,"TEXT_RENDER_LOADER "+loader.getClass().getName());
            Class<?> markdown=loader.loadClass("com.ggufchat.app.MarkdownText");
            Class<?> thinking=loader.loadClass("com.ggufchat.app.ThinkingView");
            Class<?> search=loader.loadClass("com.ggufchat.app.SearchTool");
            Class<?> codes=loader.loadClass("com.ggufchat.app.CodeBlocks");
            Method set=markdown.getMethod("set",TextView.class,String.class);
            Method visible=markdown.getMethod("visible",String.class);
            Method upgrade=thinking.getMethod("upgrade",Context.class,LinearLayout.class);
            Method decorate=search.getMethod("decorate",Context.class,LinearLayout.class,String.class);
            Method parseDdg=search.getMethod("parseDuckDuckGo",String.class,int.class);
            Method parseLite=search.getMethod("parseDuckDuckGoLite",String.class,int.class);
            Method parseSearx=search.getMethod("parseSearxng",String.class,int.class);
            Method parseWiki=search.getMethod("parseWikipedia",String.class,int.class);
            Method decorateCodes=codes.getMethod("decorate",LinearLayout.class,boolean.class);

            // 1. Negrito, itálico e código inline sobre o texto que o modelo envia.
            TextView bubble=new TextView(this);
            column.addView(bubble,new LinearLayout.LayoutParams(-1,-2));
            set.invoke(null,bubble,BOLD_FIXTURE);
            require(hasSpan(bubble,StyleSpan.class,true),"nenhum negrito/itálico aplicado");
            require(hasSpan(bubble,TypefaceSpan.class,false),"código inline sem monoespaçado");
            String shown=bubble.getText().toString();
            require(!shown.contains("**")&&!shown.contains("`"),"marcador visível: "+shown);
            require(shown.contains("negrito")&&shown.contains("código"),"texto formatado incompleto: "+shown);
            String plain=String.valueOf(visible.invoke(null,BOLD_FIXTURE));
            require(plain.equals("Resposta com negrito, itálico e código inline.\n"),"visible() divergente: "+plain);
            report.append("inline=ok;");

            // 2. Bloco de código reconhecido sem cercas, com linguagem do conteúdo.
            TextView code=new TextView(this);
            column.addView(code,new LinearLayout.LayoutParams(-1,-2));
            code.setText(INDENTED);
            decorateCodes.invoke(null,column,false);
            View codePanel=panelView(column,"Bloco de código");
            require(codePanel!=null,"painel de código ausente para bloco recuado");
            TextView title=firstText(codePanel);
            require(title!=null&&title.getText().toString().contains("python"),
                "linguagem não detectada: "+(title==null?"<sem título>":title.getText()));
            require(find(codePanel,"Copiar código"),"botão de cópia ausente no painel de código");
            TextView body=firstContaining(codePanel,"return a + b");
            require(body!=null&&body.getText().toString().contains("return a + b"),"corpo do código incompleto");
            report.append("codigo=").append(title.getText()).append(";");

            // 3. Raciocínio separado do balão da resposta (mesma marcação do app).
            LinearLayout message=new LinearLayout(this);
            message.setOrientation(LinearLayout.VERTICAL);
            TextView reasoning=new TextView(this);
            reasoning.setText("Raciocínio:\n"+REASONING);
            message.addView(reasoning);
            TextView answer=new TextView(this);
            answer.setText(ANSWER);
            message.addView(answer);
            column.addView(message,new LinearLayout.LayoutParams(-1,-2));
            upgrade.invoke(null,this,message);
            boolean reasoningPanel=false,raw=false;
            for(int i=0;i<message.getChildCount();i++){
                if(!(message.getChildAt(i) instanceof TextView))continue;
                TextView view=(TextView)message.getChildAt(i);
                if("Raciocínio".equals(view.getContentDescription()))reasoningPanel=true;
                if(view.getText().toString().contains("Raciocínio:")||view.getText().toString().contains("<thinking>"))
                    raw=true;
            }
            require(reasoningPanel,"painel de raciocínio ausente no histórico");
            require(!raw,"raciocínio ainda misturado ao balão da resposta");
            require(find(message,"Alternar raciocínio"),"alternador do raciocínio ausente");
            report.append("raciocinio=ok;");

            // 4. Fontes da busca: consulta, provedor, fontes numeradas e falha explícita.
            LinearLayout sources=new LinearLayout(this);
            sources.setOrientation(LinearLayout.VERTICAL);
            column.addView(sources,new LinearLayout.LayoutParams(-1,-2));
            decorate.invoke(null,this,sources,SOURCES_JSON);
            require(find(sources,"O que foi pesquisado"),"painel de fontes ausente");
            require(find(sources,"Consulta pesquisada"),"consulta pesquisada não exibida");
            require(find(sources,"Fonte 1")&&find(sources,"Fonte 2"),"fontes numeradas ausentes");
            LinearLayout failure=new LinearLayout(this);
            failure.setOrientation(LinearLayout.VERTICAL);
            column.addView(failure,new LinearLayout.LayoutParams(-1,-2));
            decorate.invoke(null,this,failure,"{\"query\":\"x\",\"provider\":\"nenhum\",\"error\":\"sem rede/DNS\","
                +"\"ms\":12,\"hits\":[]}");
            require(find(failure,"Falha na busca"),"falha de busca não foi mostrada");
            report.append("fontes=ok;");

            // 5. Analisadores dos provedores reais com respostas HTTP gravadas.
            List<?> ddg=(List<?>)parseDdg.invoke(null,DDG_HTML,5);
            require(ddg.size()==2,"DuckDuckGo: "+ddg.size()+" resultados");
            require("https://pt.wikipedia.org/wiki/Brasil".equals(field(ddg.get(0),"url")),"URL: "+field(ddg.get(0),"url"));
            require(field(ddg.get(0),"title").contains("Wikipédia"),"título: "+field(ddg.get(0),"title"));
            require(field(ddg.get(0),"snippet").contains("América do Sul")&&field(ddg.get(0),"snippet").contains("&"),
                "trecho: "+field(ddg.get(0),"snippet"));
            require(((List<?>)parseLite.invoke(null,DDG_HTML,5)).isEmpty(),"lite aceitou marcação html");
            require(((List<?>)parseSearx.invoke(null,SEARX_JSON,5)).size()==2,"SearXNG");
            List<?> wiki=(List<?>)parseWiki.invoke(null,WIKI_JSON,5);
            require(wiki.size()==2,"Wikipédia");
            require(field(wiki.get(0),"url").startsWith("https://pt.wikipedia.org/wiki/"),"URL wiki: "+field(wiki.get(0),"url"));
            require(field(wiki.get(0),"snippet").indexOf('<')<0,"trecho wiki com HTML");
            report.append("parsers=ok");

            status.setText("Ok: "+report);
            Log.i(TAG,"TEXT_RENDER_PASS "+report);
        }catch(Throwable error){
            status.setText("Falhou: "+error);
            Log.e(TAG,"TEXT_RENDER_FAIL",error);
            throw new RuntimeException(error);
        }
    }

    /** Carrega o DEX instalado do app: contexto do pacote e, se o Android negar,
     * o caminho do APK informado pelo próprio PackageManager (mesma origem real). */
    private ClassLoader productionLoader() throws Exception {
        try{
            Context app=createPackageContext("com.ggufchat.app",
                Context.CONTEXT_INCLUDE_CODE|Context.CONTEXT_IGNORE_SECURITY);
            Log.i(TAG,"TEXT_RENDER_SOURCE apk="+app.getApplicationInfo().sourceDir+" via=createPackageContext");
            return app.getClassLoader();
        }catch(Exception error){
            Log.i(TAG,"TEXT_RENDER_CONTEXT_DENIED "+error.getClass().getSimpleName());
            String apk=getPackageManager().getApplicationInfo("com.ggufchat.app",0).sourceDir;
            Log.i(TAG,"TEXT_RENDER_SOURCE apk="+apk+" via=PathClassLoader");
            return new dalvik.system.PathClassLoader(apk,getClassLoader());
        }
    }

    private static String field(Object hit,String name) throws Exception {
        return String.valueOf(hit.getClass().getField(name).get(hit));
    }

    private static void require(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }

    private static boolean hasSpan(TextView view,Class<?> type,boolean styleSpan){
        CharSequence text=view.getText();
        if(!(text instanceof Spanned))return false;
        @SuppressWarnings("unchecked")
        Object[] spans=((Spanned)text).getSpans(0,text.length(),(Class)type);
        for(Object span:spans){
            if(styleSpan){
                if(span instanceof StyleSpan){
                    int mask=((StyleSpan)span).getStyle();
                    if(mask==Typeface.BOLD||mask==Typeface.ITALIC)return true;
                }
            }else if(!(span instanceof StyleSpan))return true;
        }
        return false;
    }

    private static View panelView(View root,String descriptionPrefix){
        String description=String.valueOf(root.getContentDescription());
        if(description.startsWith(descriptionPrefix))return root;
        if(root instanceof ViewGroup){
            ViewGroup group=(ViewGroup)root;
            for(int i=0;i<group.getChildCount();i++){
                View found=panelView(group.getChildAt(i),descriptionPrefix);
                if(found!=null)return found;
            }
        }
        return null;
    }

    /** Primeiro TextView do painel: a barra de título vem antes do corpo. */
    private static TextView firstText(View root){
        if(root instanceof TextView)return (TextView)root;
        if(root instanceof ViewGroup){
            ViewGroup group=(ViewGroup)root;
            for(int i=0;i<group.getChildCount();i++){
                TextView found=firstText(group.getChildAt(i));
                if(found!=null)return found;
            }
        }
        return null;
    }

    /** Primeiro TextView cujo texto contém o trecho pedido. */
    private static TextView firstContaining(View root,String needle){
        if(root instanceof TextView){
            TextView view=(TextView)root;
            if(view.getText().toString().contains(needle))return view;
        }
        if(root instanceof ViewGroup){
            ViewGroup group=(ViewGroup)root;
            for(int i=0;i<group.getChildCount();i++){
                TextView found=firstContaining(group.getChildAt(i),needle);
                if(found!=null)return found;
            }
        }
        return null;
    }

    private static boolean find(View view,String description){
        if(description.equals(view.getContentDescription()))return true;
        if(view instanceof ViewGroup){
            ViewGroup group=(ViewGroup)view;
            for(int i=0;i<group.getChildCount();i++)if(find(group.getChildAt(i),description))return true;
        }
        return false;
    }
}
