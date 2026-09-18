from pathlib import Path
import os,shutil,subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from local_stream import patch


def test_patch_exact_payload_and_reject_second_application(tmp_path):
    source=ROOT/'.cache/text-ui-base/smali/com/ggufchat/app'
    if not source.exists():pytest.skip('Exact candidate DEX decode required')
    for name in ('ChatActivity','ChatActivity$1','GenerationService'):
        shutil.copyfile(source/(name+'.smali'),tmp_path/(name+'.smali'))
    receiver=(tmp_path/'ChatActivity$1.smali').read_bytes()
    patch(tmp_path)
    assert (tmp_path/'ChatActivity$1.smali').read_bytes()==receiver
    assert (tmp_path/'ChatActivity.smali').read_text().count('LocalGenerationStream;->')==3
    assert (tmp_path/'GenerationService.smali').read_text().count('LocalGenerationStream;->send(')==3
    with pytest.raises(AssertionError):patch(tmp_path)


def test_default_off_and_no_native_timing_or_model_change():
    s=(ROOT/'apk-fix/java/com/ggufchat/app/LocalGenerationStream.java').read_text()
    assert '"1".equals(System.getenv("GGUF_LOCAL_STREAM"))' in s
    for forbidden in ('Thread.sleep','postDelayed','Native.','nPredict','SystemClock','setPriority'):
        assert forbidden not in s
    assert 'old.active=false;RECEIVERS.remove(r)' in s
    assert 'r.active' in s and 'new Intent(original)' in s
    assert 'local_stream' not in (ROOT/'apk-fix/build_mobile.py').read_text()


def test_fifo_exact_copy_lifecycle_error_and_disabled_route(tmp_path):
    if not shutil.which('javac'):pytest.skip('Host JDK compiler supplied by CI')
    sources={
      'android/content/Intent.java':'''package android.content;import java.util.*;
public class Intent {String action,pkg;Map<String,Object> extras=new HashMap<>();
public Intent(String a){action=a;}public Intent(Intent a){action=a.action;pkg=a.pkg;extras.putAll(a.extras);}
public String getAction(){return action;}public String getPackage(){return pkg;}public Intent setPackage(String p){pkg=p;return this;}
public Intent putExtra(String k,String v){extras.put(k,v);return this;}public Intent putExtra(String k,boolean v){extras.put(k,v);return this;}
public String getStringExtra(String k){return (String)extras.get(k);}public boolean getBooleanExtra(String k,boolean d){return extras.containsKey(k)?(Boolean)extras.get(k):d;}}''',
      'android/content/IntentFilter.java':'''package android.content;import java.util.*;
public class IntentFilter {List<String> a=new ArrayList<>();public void addAction(String s){a.add(s);}public int countActions(){return a.size();}
public int countDataSchemes(){return 0;}public int countDataTypes(){return 0;}public int countCategories(){return 0;}public String getAction(int i){return a.get(i);}}''',
      'android/content/BroadcastReceiver.java':'''package android.content;public abstract class BroadcastReceiver {public abstract void onReceive(Context c,Intent i);}''',
      'android/content/Context.java':'''package android.content;public class Context {public int registered,removed,sent,flags;
public String getPackageName(){return "com.ggufchat.app";}public Intent registerReceiver(BroadcastReceiver r,IntentFilter f){registered++;return null;}
public Intent registerReceiver(BroadcastReceiver r,IntentFilter f,int flags){this.flags=flags;registered++;return null;}
public void unregisterReceiver(BroadcastReceiver r){removed++;}public void sendBroadcast(Intent i){sent++;}}''',
      'android/os/Looper.java':'''package android.os;public class Looper {static final Thread OWNER=Thread.currentThread();static final Looper MAIN=new Looper();public static Looper getMainLooper(){return MAIN;}public static Looper myLooper(){return Thread.currentThread()==OWNER?MAIN:null;}}''',
      'android/os/Handler.java':'''package android.os;import java.util.concurrent.*;public class Handler {public static final ConcurrentLinkedQueue<Runnable> Q=new ConcurrentLinkedQueue<>();public Handler(Looper l){}public boolean post(Runnable r){return Q.add(r);}public static void drain(){Runnable r;while((r=Q.poll())!=null)r.run();}}''',
      'android/util/Log.java':'''package android.util;public class Log {public static int i(String t,String s){return 0;}}''',
      'StreamTest.java':r'''import android.content.*;import android.os.*;import java.util.*;import com.ggufchat.app.LocalGenerationStream;
public class StreamTest {
 static final String PREFIX="com.ggufchat.app.action.";static void check(boolean b){if(!b)throw new AssertionError();}
 static Intent event(String a,String v){return new Intent(PREFIX+a).setPackage("com.ggufchat.app").putExtra("text",v).putExtra("ok",true);}
 public static void main(String[] args)throws Exception {
  boolean enabled="1".equals(System.getenv("GGUF_LOCAL_STREAM"));Context activity=new Context(),service=new Context();
  IntentFilter f=new IntentFilter();for(String a:new String[]{"TOKEN","DONE","ERROR"})f.addAction(PREFIX+a);
  List<String> received=new ArrayList<>();
  BroadcastReceiver r=new BroadcastReceiver(){public void onReceive(Context c,Intent i){check(c==activity);check(Looper.myLooper()==Looper.getMainLooper());check(i.getBooleanExtra("ok",false));received.add(i.getAction()+"|"+i.getStringExtra("text"));}};
  LocalGenerationStream.register(activity,r,f,4);
  if(!enabled){LocalGenerationStream.send(service,event("TOKEN","x"));LocalGenerationStream.unregister(activity,r);check(activity.registered==1&&activity.flags==4&&activity.removed==1&&service.sent==1&&Handler.Q.isEmpty());return;}
  LocalGenerationStream.register(activity,r,f); // no duplicate delivery
  String text=" ação 你好\n```java\n  x();\n```\n";Intent first=event("TOKEN",text);
  Thread worker=new Thread(()->{LocalGenerationStream.send(service,first);LocalGenerationStream.send(service,event("TOKEN","end"));LocalGenerationStream.send(service,event("DONE","saved"));});worker.start();worker.join();
  check(received.isEmpty());first.putExtra("text","mutated");Handler.drain();
  check(received.equals(Arrays.asList(PREFIX+"TOKEN|"+text,PREFIX+"TOKEN|end",PREFIX+"DONE|saved")));
  LocalGenerationStream.send(service,event("TOKEN","stale"));LocalGenerationStream.unregister(activity,r);LocalGenerationStream.register(activity,r,f);Handler.drain();check(received.size()==3);
  LocalGenerationStream.send(service,event("ERROR","explicit failure"));Handler.drain();check(received.get(3).equals(PREFIX+"ERROR|explicit failure"));
  LocalGenerationStream.unregister(activity,r);LocalGenerationStream.send(service,event("TOKEN","offscreen"));check(Handler.Q.isEmpty());
  try{LocalGenerationStream.send(service,event("OTHER","bad"));throw new AssertionError();}catch(IllegalArgumentException expected){}
  try{LocalGenerationStream.send(service,event("TOKEN","bad").setPackage("other.app"));throw new AssertionError();}catch(IllegalArgumentException expected){}
  check(activity.registered==0&&activity.removed==0&&service.sent==0);
 }
}'''}
    files=[]
    for name,content in sources.items():
        p=tmp_path/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(content);files.append(p)
    files.append(ROOT/'apk-fix/java/com/ggufchat/app/LocalGenerationStream.java')
    subprocess.run(['javac','-encoding','UTF-8','--release','8','-d',str(tmp_path),*map(str,files)],check=True)
    for mode in ('0','1'):
        subprocess.run(['java','-cp',str(tmp_path),'StreamTest'],env=dict(os.environ,GGUF_LOCAL_STREAM=mode),check=True)
