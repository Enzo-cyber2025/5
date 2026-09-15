"""Measured progress core and exact single-worker wiring; Android UI tested separately."""
import os,shutil,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))

def test_percentage_arithmetic_and_real_work_counters(tmp_path):
    javac=shutil.which('javac')
    if not javac:pytest.skip('JDK compiler required; hosted Android build runs this test')
    from test_physical_gguf import fixture
    fixture(tmp_path/'a.gguf');fixture(tmp_path/'b.gguf','projector')
    program=tmp_path/'ProgressTest.java'
    program.write_text('''import com.ggufchat.app.*;import java.io.*;import java.util.*;
public class ProgressTest {
public static void main(String[] args)throws Exception {
assert ProgressMeter.percent(50,100,false)==50;
assert ProgressMeter.percent(100,100,false)==99;
assert ProgressMeter.percent(Long.MAX_VALUE,Long.MAX_VALUE,false)==99;
assert ProgressMeter.percent(Long.MAX_VALUE/2,Long.MAX_VALUE,false)==50;
assert ProgressMeter.percent(200,100,false)==-1;
assert ProgressMeter.percent(0,0,false)==-1;
assert ProgressMeter.percent(123,-1,false)==-1;
assert ProgressMeter.percent(123,123,true)==100;
Map<String,Long> last=new HashMap<>();Set<String> completed=new HashSet<>();
GgufFile.Progress tracker=(stage,done,total,complete)->{
 if(total<0)return;
 assert done>=last.getOrDefault(stage,0L)&&done<=total;
 assert ProgressMeter.percent(done,total,complete)<=99||complete;
 last.put(stage,done);if(complete){assert done==total;completed.add(stage);}
};
File a=new File(args[0],"a.gguf"),b=new File(args[0],"b.gguf"),out=new File(args[0],"one.gguf");
GgufFile.read(a,tracker);assert completed.contains("identify");
GgufFile g=GgufFile.merge(a,b,out,tracker);assert completed.contains("merge")&&completed.contains("verify");
long bytes=0;for(GgufFile.Tensor t:g.tensors.values())bytes+=t.bytes;
assert last.get("merge")==bytes&&last.get("verify")==bytes;
try(RandomAccessFile f=new RandomAccessFile(out,"rw")){f.seek(g.dataOffset);f.writeByte(250);}
completed.clear();last.clear();
try{GgufFile.verifyPayload(GgufFile.read(a),GgufFile.read(b),GgufFile.read(out),tracker);throw new AssertionError("corruption accepted");}
catch(IOException expected){assert !completed.contains("verify");}
System.out.println("PROGRESS_COUNTERS_PASS");
}}
''')
    sources=[ROOT/'apk-fix/java/com/ggufchat/app'/n for n in ('GgufFile.java','ProgressMeter.java')]
    subprocess.run([javac,'--release','8','-d',str(tmp_path),*map(str,sources),str(program)],check=True)
    subprocess.run([shutil.which('java'),'-ea','-cp',str(tmp_path),'ProgressTest',str(tmp_path)],check=True)

def test_single_progress_wiring_covers_copy_identification_success_failure():
    s=(ROOT/'apk-fix/import_progress.py').read_text()
    for method in ('beginSingle','singleSource','singleCopy','identificationStart','inspectWithProgress','singleFinished','attach','syncCopied'):
        assert '->'+method in s
    assert "[('2',False),('3',True)]" in s
    assert 'patch_import_progress(app)' in (ROOT/'apk-fix/build_mobile.py').read_text()


def test_old_import_shortcuts_use_canonical_progress_screen():
    s=(ROOT/'apk-fix/import_progress.py').read_text()
    assert 'access$600' in s and "[('2','.method public onClick" in s
