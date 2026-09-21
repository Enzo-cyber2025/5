"""Content bridge regressions; real format/model execution is in test_inference_android.py."""
from pathlib import Path
import shutil,subprocess,re
import pytest,jdk4py
ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'apk-fix/java/com/ggufchat/app/AttachmentInference.java'

def test_actual_multimodal_bridge_is_not_a_filename_notice():
    s=JAVA.read_text();native=(ROOT/'apk-fix/native/mobile.cpp').read_text();hooks=(ROOT/'apk-fix/attachment_patches.py').read_text()
    assert 'prependContents(contents,rows.get(row)[1])' in s
    assert 'AttachmentStore.directory(c,chatId)' in s and 'f.length()!=item.getLong("size")' in s
    assert 'mtmd_tokenize(e->projector' in native and 'mtmd_helper_eval_chunk_single(e->projector,e->ctx' in native
    assert 'input_size=mtmd_helper_get_n_tokens' in native
    assert native.index('mtmd_helper_eval_chunk_single(e->projector')<native.index('GGUF_IMAGE_EVALUATED')
    assert 'AttachmentInference;->prepare' in hooks and 'AttachmentInference;->generate' in hooks
    assert 'finally{release();}' in s and 'if(!images)e->cancel=false' in native
    assert 'FEATURE_PROCESS_DOCDECL,false' in s and 'XmlPullParser.DOCDECL' in s
    assert 'for(int i=0;i<doc.getNumberOfPages();i++)' in s
    assert 'getInputStream(e)' in s and 'count+=k' in s
    assert 'Desativar leitura' in (JAVA.parent/'Attachments.java').read_text()

def test_real_bounded_text_reader_and_cancellation(tmp_path):
    javac=shutil.which('javac')
    if not javac:pytest.skip('CI supplies the JDK compiler')
    s=JAVA.read_text()
    body=s[s.index('    static final class Budget'):s.index('    private static String office')]
    get=re.search(r'    private static Object get\(.*?\n    }',s,re.S).group()
    cancel=s[s.index('    private static void checkCancelled'):s.index('    private static native void begin')]
    source='import java.io.*;import java.nio.charset.*;import java.lang.reflect.*;\npublic class ReaderTest {\n'+get+cancel+body+'''
    static String clean(String s){return s;}
    static String read(byte[] b,int cap) throws Exception {return readText(new ByteArrayInputStream(b),new Budget(cap));}
    private boolean abortRequested=true;
    public static void main(String[] args)throws Exception {
        assert read("ação 🌍".getBytes("UTF-8"),20).equals("ação 🌍");
        assert read(new byte[]{(byte)255,(byte)254,65,0},2).equals("A");
        assert read(new byte[]{(byte)254,(byte)255,0,65},2).equals("A");
        assert read(new byte[0],0).equals("");
        assert read("abc".getBytes("UTF-8"),3).equals("abc");
        try{read("abcd".getBytes("UTF-8"),3);throw new AssertionError();}catch(IOException expected){}
        try{read(new byte[]{65,0,66},9);throw new AssertionError();}catch(IOException expected){}
        try{read(new byte[]{(byte)0xff,65},9);throw new AssertionError();}catch(IOException expected){}
        Budget budget=new Budget(20);budget.owner=new ReaderTest();
        try{readText(new ByteArrayInputStream("abc".getBytes("UTF-8")),budget);throw new AssertionError();}catch(InterruptedIOException expected){}
        InputStream endless=new InputStream(){public int read(){return 'x';}public int read(byte[] b,int o,int n){java.util.Arrays.fill(b,o,o+n,(byte)'x');return n;}};
        try{readText(endless,new Budget(131072));throw new AssertionError();}catch(IOException expected){}
    }
}'''
    p=tmp_path/'ReaderTest.java';p.write_text(source)
    subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),str(p)],check=True)
    subprocess.run([str(jdk4py.JAVA_HOME/'bin/java'),'-Xmx32m','-ea','-cp',str(tmp_path),'ReaderTest'],check=True)


def test_current_mtmd_input_uses_full_byte_length(tmp_path):
    # Compile the actual adapter helper against pinned upstream headers. A bool
    # positional initializer compiles too, but sends only one byte on v0.4.
    import re,subprocess,shutil
    from pathlib import Path
    import pytest
    root=Path(__file__).resolve().parents[1]
    source=(root/'apk-fix/native/mobile.cpp').read_text()
    helper=re.search(r'static mtmd_input_text media_input\(.*?\n}',source,re.S).group()
    upstream=next((p for p in (root/'.cache/llama-mobile',root/'.cache/llama-gemma4') if (p/'tools/mtmd/mtmd.h').exists() and 'size_t text_len;' in (p/'tools/mtmd/mtmd.h').read_text()),None)
    if upstream is None:pytest.skip('Pinned current mtmd headers required')
    cpp=tmp_path/'media.cpp';exe=tmp_path/'media'
    cpp.write_text('#include <string>\n#include <cassert>\n#include "mtmd.h"\n'+helper+'\nint main(){std::string s=u8"Olá <__media__> ônibus"; auto t=media_input(s); assert(t.text_len==s.size()); assert(std::string(t.text,t.text_len)==s); assert(t.add_special && t.parse_special); assert(media_input(std::string()).text_len==0); }')
    subprocess.run(['g++','-std=c++17','-I'+str(upstream/'tools/mtmd'),'-I'+str(upstream/'include'),'-I'+str(upstream/'ggml/include'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


def test_attachment_free_history_preserves_string_and_prefix_bytes(tmp_path):
    s=JAVA.read_text()
    assert 'StringBuilder contents=null;' in s
    assert s.index('if(item.optInt("message",-1)!=m)continue;')<s.index('if(contents==null)contents=new StringBuilder();')
    javac=shutil.which('javac')
    if not javac:pytest.skip('CI supplies the JDK compiler')
    method=re.search(r'    static String prependContents\(.*?\n    }',s,re.S).group()
    cpp=tmp_path/'HistoryTest.java'
    cpp.write_text('''public class HistoryTest {\n'''+method+'''
 public static void main(String[] args){
  String text=new String(new char[100000]).replace('\\0','x')+"ação\\r\\n  code  ";
  assert prependContents(null,text)==text;
  assert prependContents(new StringBuilder(),text)==text;
  StringBuilder prefix=new StringBuilder("\\n--- Anexo ---\\n");
  String result=prependContents(prefix,text);
  assert result.equals(prefix.toString()+text);
  prefix.append("changed");assert !result.equals(prefix.toString()+text);
  for(int i=0;i<10000;i++)assert prependContents(null,text)==text;
 }
}''')
    subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),str(cpp)],check=True)
    subprocess.run([str(jdk4py.JAVA_HOME/'bin/java'),'-ea','-cp',str(tmp_path),'HistoryTest'],check=True)
