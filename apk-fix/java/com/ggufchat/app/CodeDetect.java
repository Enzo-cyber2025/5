package com.ggufchat.app;

import java.util.regex.Pattern;

/** Detects the language of a code block and recognises indented code that the
 * model produced without fences. Conservative: only runs of four-space (or tab)
 * indented lines with two or more non-blank lines are converted, and only for
 * presentation — the stored message text is never rewritten. */
public final class CodeDetect {
    private static final String[] PY={"def ","import ","from ","print(","self.","elif ","return ","lambda "};
    private static final String[] JS={"function ","const ","let ","=>","console.log","require(","export "};
    private static final String[] JAVA={"public class ","private static ","System.out","void main","@Override"};
    private static final String[] KOTLIN={"fun ","val ","var ","when ("};
    private static final String[] C={"#include","printf(","int main","std::","nullptr"};
    private static final String[] BASH={"#!/","sudo ","apt ","echo $","mkdir -p","curl -"};
    private static final String[] SQL={"SELECT ","INSERT INTO","UPDATE ","DELETE FROM","CREATE TABLE"," FROM "};
    private static final String[] HTML={"<html","<div","</","<span","<!DOCTYPE"};
    private static final String[] RUST={"fn main","println!","let mut","impl ","pub fn"};
    private static final String[] GO={"package main","func ","fmt.","go func"};
    private static final String[] PHP={"<?php","echo ","$this->"};
    private static final String[] RUBY={"def ","puts ","require '"};
    private static final Pattern JSON_HEADS=Pattern.compile("^\\s*[\\{\\[].*\"[^\"]+\"\\s*:.*",Pattern.DOTALL);
    private static final Pattern YAML_LINE=Pattern.compile("(?m)^[A-Za-z0-9_.-]+: .+$");

    private CodeDetect(){}

    public static String language(String code){
        if(code==null)return "";
        String text=code.trim();
        if(text.length()==0)return "";
        if(JSON_HEADS.matcher(text).matches())return "json";
        if(text.startsWith("<?php"))return "php";
        if((text.startsWith("---")||YAML_LINE.matcher(text).find())&&!text.contains("{")&&!text.contains(";")
            &&!text.contains("</")&&text.contains(": "))return "yaml";
        if(has(text,HTML)&&text.contains(">"))return "html";
        if(has(text,C)&&(text.contains(";")||text.contains("#include")))return "c/c++";
        if(has(text,JAVA))return "java";
        if(has(text,KOTLIN))return "kotlin";
        if(has(text,GO))return "go";
        if(has(text,RUST))return "rust";
        if(has(text,PHP))return "php";
        if(has(text,RUBY)&&text.contains("end"))return "ruby";
        if(has(text,BASH))return "bash";
        if(has(text,SQL))return "sql";
        if(has(text,PY))return "python";
        if(has(text,JS))return "javascript";
        if(text.endsWith("}")&&text.contains("{")&&text.contains(";"))return "c/c++";
        return "";
    }

    private static boolean has(String text,String[] needles){
        for(String needle:needles)if(text.contains(needle))return true;
        return false;
    }

    private static boolean indented(String line){return line.startsWith("    ")||line.startsWith("\t");}
    private static boolean blank(String line){return line.trim().length()==0;}

    /** Marca blocos recuados com cercas para o renderizador já existente. */
    public static String fenced(String text){
        if(text==null||text.length()==0)return text;
        if(text.contains("```")||text.contains("~~~"))return text; // fences explícitas já bastam
        String[] lines=text.split("\n",-1);
        StringBuilder out=new StringBuilder(text.length()+64);
        int i=0;
        while(i<lines.length){
            if(!indented(lines[i])){out.append(lines[i]).append('\n');i++;continue;}
            int start=i,nonBlank=0,j=i;
            while(j<lines.length&&(indented(lines[j])||blank(lines[j]))){
                if(indented(lines[j]))nonBlank++;
                j++;
            }
            if(nonBlank<2){out.append(lines[i]).append('\n');i++;continue;}
            int end=j;
            while(end>start&&blank(lines[end-1]))end--;
            out.append("```").append(language(join(lines,start,end))).append('\n');
            for(int k=start;k<end;k++)out.append(lines[k]).append('\n');
            out.append("```\n");
            for(int k=end;k<j;k++)out.append(lines[k]).append('\n');
            i=j;
        }
        return out.toString();
    }

    private static String join(String[] lines,int from,int to){
        StringBuilder out=new StringBuilder();
        for(int i=from;i<to;i++)out.append(lines[i]).append('\n');
        return out.toString();
    }
}
