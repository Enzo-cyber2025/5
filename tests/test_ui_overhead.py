from pathlib import Path
import shutil, subprocess, sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'apk-fix/java/com/ggufchat/app'

def test_preview_cadence_append_only_exact_boundaries(tmp_path):
    if not shutil.which('javac'):pytest.skip('JDK required')
    p=tmp_path/'PreviewTest.java';p.write_text('''import com.ggufchat.app.PreviewCadence;
public class PreviewTest {
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  PreviewCadence c=new PreviewCadence();
  check(!c.needsUpdate(0,0));check(c.needsUpdate(0,1));
  check(!c.needsUpdate(999,80));check(c.needsUpdate(1000,80));
  for(int i=81;i<100000;i++)check(!c.needsUpdate(i*1000L,i));
  c.reset();check(c.needsUpdate(2000,2));check(!c.needsUpdate(3000,2));
  check(c.needsUpdate(3000,3));check(!c.needsUpdate(3999,4));check(c.needsUpdate(4000,4));
  // A screen-off interval does not advance the gate: the latest prefix appears on wake.
  check(c.needsUpdate(100000,1000));check(!c.needsUpdate(101000,1001));
  c.reset();check(c.needsUpdate(0,1000));check(!c.needsUpdate(1000,1001));
 }
}''')
    subprocess.run(['javac','-d',str(tmp_path),str(JAVA/'PreviewCadence.java'),str(p)],check=True)
    subprocess.run(['java','-cp',str(tmp_path),'PreviewTest'],check=True)

def test_patch_real_delivered_smali_and_refuse_double_apply(tmp_path):
    src=ROOT/'.cache/ui-baseline/smali/com/ggufchat/app'
    if not src.exists():pytest.skip('Exact delivered DEX decode required')
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from ui_overhead import patch_delivered_ui, discard_unused_stream_buffer
    for n in ('ChatActivity.smali','GenerationService$2.smali'):shutil.copyfile(src/n,tmp_path/n)
    patch_delivered_ui(tmp_path)
    s=(tmp_path/'ChatActivity.smali').read_text()
    assert s.count('ScrollTail;->request(')==1
    # Other than removing the proven write-only buffer, preserve complete methods.
    old=discard_unused_stream_buffer((src/'ChatActivity.smali').read_text())
    assert 'streamingBuf' not in s
    for name in ('onToken','onSend','onDone','onError','onResume','onPause','renderHistory'):
        def method(text):
            import re
            match=re.search(r'^\.method [^\n]* '+name+r'\([^\n]*\n.*?^\.end method',text,re.M|re.S)
            assert match;return match[0]
        assert method(s)==method(old),name
    cb=(tmp_path/'GenerationService$2.smali').read_text()
    assert 'progressNow(Landroid/app/Service;Ljava/lang/StringBuilder;)Z' in cb
    assert cb.index('StringBuilder;->append')<cb.index('progressNow(')
    assert cb.index('GenerationService;->access$100(')<cb.index('progressNow(')
    with pytest.raises(AssertionError):patch_delivered_ui(tmp_path)

def test_no_animation_or_strong_view_ownership_or_token_throttle():
    s=(JAVA/'ScrollTail.java').read_text()
    assert 'WeakReference<ScrollView>' in s and 'WeakReference<ViewTreeObserver>' in s
    assert 'OnPreDrawListener' in s and 'removeOnPreDrawListener' in s
    assert 'scroll.scrollTo(' in s and 'postInvalidateOnAnimation' in s
    assert 'fullScroll(' not in s and 'smoothScroll' not in s and 'Thread.sleep' not in s
    p=(JAVA/'ReplyNotifications.java').read_text()
    assert 's.preview.reset()' in p and 's.preview.needsUpdate(now,reply.length())' in p
    assert 's.preview' not in p[p.index('void finished'):]
    assert 'PreviewCadence.PREFIX_LENGTH' in (JAVA/'GenerationStats.java').read_text()


def test_buffer_removal_refuses_any_extra_reader():
    src=ROOT/'.cache/ui-baseline/smali/com/ggufchat/app/ChatActivity.smali'
    if not src.exists():pytest.skip('Decoded baseline required')
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from ui_overhead import discard_unused_stream_buffer
    original=src.read_text()
    with pytest.raises(AssertionError):
        discard_unused_stream_buffer(original+'\niget-object v0, p0, Lcom/ggufchat/app/ChatActivity;->streamingBuf:Ljava/lang/StringBuilder;')


def test_renderer_flushes_synchronously_at_boundaries():
    s=(JAVA/'CodeBlocks.java').read_text()
    assert 'stream.parser.feed(chunk);\n        stream.flush();' in s
    assert 'stream.parser.finish();stream.flush();' in s
    # O fechamento limpa o estado depois de despejar o que estava pendente. Ele
    # ganhou a detecção de linguagem do bloco; o que este teste protege é o
    # despejo síncrono e a limpeza, não a forma de uma linha só.
    close = s[s.index('public void close(){'):]
    close = close[:close.index('\n        }')]
    assert 'flush();' in close and 'code=null;plain=null;' in close
    assert s.index('flush(); // Mount') < s.index('mount();plain=null;')
    assert 'if(pendingFirst==null)pendingFirst=text;' in s
    # O lote é acumulado por destino (uma única inserção por despejo), não por
    # uma chamada de append direta na view a cada chunk.
    assert 'pendingBatch.append(pendingFirst)' in s and 'pendingTarget=target' in s
    assert 'postDelayed' not in s and 'Thread.sleep' not in s


def test_unused_buffer_removal_in_reassembled_real_dex(tmp_path):
    """Bytecode test only: deliberately omit libraries/secondary DEX, not an APK delivery."""
    import zipfile
    base=ROOT/'.cache/ui-baseline'
    tool=ROOT/'.cache/tools/package/lib/apktool.jar'
    if not (base/'smali/com/ggufchat/app/ChatActivity.smali').exists() or not tool.exists():
        pytest.skip('Decoded released APK and apktool required')
    java=shutil.which('java')
    if not java:
        jdk=pytest.importorskip('jdk4py');java=str(jdk.JAVA_HOME/'bin/java')
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from ui_overhead import discard_unused_stream_buffer
    decoded=tmp_path/'decoded'
    shutil.copytree(base,decoded,ignore=shutil.ignore_patterns('lib','smali_classes2','build','original'))
    app=decoded/'smali/com/ggufchat/app/ChatActivity.smali'
    app.write_text(discard_unused_stream_buffer(app.read_text()))
    output=tmp_path/'bytecode-only.apk'
    subprocess.run([java,'-jar',str(tool),'b',str(decoded),'-o',str(output)],check=True,capture_output=True)
    from androguard.core.dex import DEX
    from loguru import logger
    logger.disable('androguard')
    def activity(apk):
        with zipfile.ZipFile(apk) as z:d=DEX(z.read('classes.dex'))
        return next(c for c in d.get_classes() if c.get_name()=='Lcom/ggufchat/app/ChatActivity;')
    before=activity(ROOT/'.delivery/GGUF-Chat-mobile.apk');after=activity(output)
    def methods(c):
        return {m.get_name()+m.get_descriptor():[(i.get_name(),i.get_output()) for i in m.get_instructions()] for m in c.get_methods()}
    a,b=methods(before),methods(after)
    assert a.keys()==b.keys()
    changed={name for name in a if a[name]!=b[name]}
    assert changed=={'onToken(Ljava/lang/String;)V','onSend()V','onDone()V','onError(Ljava/lang/String;)V'}
    def fields(c):return {(f.get_name(),f.get_descriptor(),f.get_access_flags()) for f in c.get_fields()}
    removed=fields(before)-fields(after)
    assert len(removed)==1 and next(iter(removed))[0]=='streamingBuf'
    assert fields(after)-fields(before)==set()
