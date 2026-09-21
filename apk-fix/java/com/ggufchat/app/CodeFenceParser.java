package com.ggufchat.app;

/** Incremental, line-based fenced-code parser. No HTML, WebView or code execution. */
public final class CodeFenceParser {
    public interface Sink {
        void text(String text);
        void open(String language);
        void code(String code);
        void close();
    }
    private final Sink sink;
    private final StringBuilder pending=new StringBuilder();
    private boolean inCode,literal;
    private char fence;
    private int fenceLength;
    public CodeFenceParser(Sink sink){this.sink=sink;}
    private static int indent(String s){int i=0;while(i<s.length()&&s.charAt(i)==' '&&i<4)i++;return i;}
    private static int run(String s,int i,char ch){int start=i;while(i<s.length()&&s.charAt(i)==ch)i++;return i-start;}
    private void emit(String s){if(s.length()>0){if(inCode)sink.code(s);else sink.text(s);}}
    private boolean possible(String s){
        int i=indent(s);if(i>3)return false;if(i==s.length())return true;
        char ch=s.charAt(i);if(inCode?ch!=fence:(ch!='`'&&ch!='~'))return false;
        int n=run(s,i,ch),end=i+n;
        if(end==s.length())return true;
        if(n<(inCode?fenceLength:3))return false;
        String rest=s.substring(end);
        if(inCode)return rest.trim().length()==0;
        return ch!='`'||rest.indexOf('`')<0;
    }
    private void endLine(boolean newline){
        if(literal){if(newline)emit("\n");literal=false;return;}
        String raw=pending.toString();pending.setLength(0);
        String s=raw.endsWith("\r")?raw.substring(0,raw.length()-1):raw;
        int i=indent(s);
        if(i<=3&&i<s.length()){
            char ch=s.charAt(i);int n=run(s,i,ch);String rest=s.substring(i+n);
            if(inCode&&ch==fence&&n>=fenceLength&&rest.trim().length()==0){inCode=false;sink.close();return;}
            if(!inCode&&(ch=='`'||ch=='~')&&n>=3&&(ch!='`'||rest.indexOf('`')<0)){
                fence=ch;fenceLength=n;inCode=true;sink.open(rest.trim());return;
            }
        }
        emit(raw+(newline?"\n":""));
    }
    public void feed(String chunk){
        int at=0;
        while(at<chunk.length()){
            int nl=chunk.indexOf('\n',at),end=nl<0?chunk.length():nl;
            String part=chunk.substring(at,end);
            if(literal)emit(part);
            else {
                pending.append(part);
                if(!possible(pending.toString())){emit(pending.toString());pending.setLength(0);literal=true;}
            }
            if(nl>=0)endLine(true);
            at=nl<0?end:end+1;
        }
    }
    public void finish(){endLine(false);}
}
