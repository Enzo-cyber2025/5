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
    from ui_overhead import patch_delivered_ui
    for n in ('ChatActivity.smali','GenerationService$2.smali'):shutil.copyfile(src/n,tmp_path/n)
    patch_delivered_ui(tmp_path)
    s=(tmp_path/'ChatActivity.smali').read_text()
    assert s.count('ScrollTail;->request(')==1
    # No streaming, Send timing, code parsing, completion/history or token-budget edits.
    old=(src/'ChatActivity.smali').read_text()
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
