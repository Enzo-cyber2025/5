"""Real Pairing.java logic with explicit Android/store doubles, NOT Android inference."""
from pathlib import Path
import subprocess
import sys
import shutil
import pytest
import jdk4py

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from unified_mobile import patch_clip_gpu


def test_pairing_single_record_migration_selection_delete_and_eye(tmp_path):
    javac=shutil.which("javac")
    if not javac: pytest.skip("JDK compiler required; CI installs Temurin 17 (jdk4py is runtime-only)")
    sources={
        'android/content/Context.java': '''package android.content; import java.io.File;
public class Context { public File root; public Context(File r){root=r;} public File getFilesDir(){return root;}
public ContentResolver getContentResolver(){return new ContentResolver();} }''',
        'android/content/ContentResolver.java': '''package android.content; import android.net.Uri; import android.database.Cursor;
public class ContentResolver { public Cursor query(Uri u,String[] p,String a,String[] b,String c){return new Cursor(u.name);} }''',
        'android/net/Uri.java': '''package android.net; public class Uri {public String name;public Uri(String n){name=n;}}''',
        'android/database/Cursor.java': '''package android.database; public class Cursor implements AutoCloseable {
String name;public Cursor(String n){name=n;}public boolean moveToFirst(){return true;}public String getString(int n){return name;}public void close(){}}''',
        'android/provider/OpenableColumns.java': '''package android.provider;public class OpenableColumns {public static final String DISPLAY_NAME="name";}''',
        'android/widget/Toast.java': '''package android.widget;import android.content.Context;public class Toast {
public static final int LENGTH_LONG=1;public static Toast makeText(Context c,String s,int n){return new Toast();} public void show(){}}''',
        'android/util/Log.java': '''package android.util;public class Log {
public static int e(String a,String b,Throwable t){return 0;} public static int e(String a,String b){return 0;}public static int i(String a,String b){return 0;}}''',
        'com/ggufchat/app/ModelInfo.java': '''package com.ggufchat.app;public class ModelInfo {
public String id,name,fileName,path,mmprojPath,architecture;public long size,importedAt;public boolean multimodal;
public ModelInfo copy() {ModelInfo n=new ModelInfo();n.id=id;n.name=name;n.fileName=fileName;n.path=path;n.mmprojPath=mmprojPath;n.architecture=architecture;n.size=size;n.importedAt=importedAt;n.multimodal=multimodal;return n;}}''',
        'com/ggufchat/app/ModelStore.java': '''package com.ggufchat.app;import android.content.Context;import java.util.*;
public class ModelStore {private static final Object LOCK=new Object();public static ArrayList<ModelInfo> data=new ArrayList<>();
public static ArrayList<ModelInfo> loadRecords(Context c){ArrayList<ModelInfo> copy=new ArrayList<>();for(ModelInfo m:data)copy.add(m.copy());return copy;}
public static ArrayList<?> load(Context c){return Pairing.loadUnified(c);}
public static void save(Context c,ArrayList<ModelInfo> m){data=new ArrayList<>();for(ModelInfo n:m)data.add(n.copy());}}''',
        'UnitTest.java': r'''import com.ggufchat.app.*;import android.content.Context;import android.net.Uri;import java.io.*;import java.nio.file.*;import java.util.*;
public class UnitTest {
static ModelInfo model(Context c,String id,String filename) throws Exception {ModelInfo m=new ModelInfo();m.id=id;m.name="Llama vision";m.fileName=filename;m.architecture=filename.contains("mmproj")?"clip":"llama";m.path=new File(c.getFilesDir(),"models/"+id+"_"+filename).getPath();Files.write(Paths.get(m.path),new byte[16]);m.size=16;return m;}
static ArrayList<Uri> uris(String a,String b){return new ArrayList<>(Arrays.asList(new Uri(a),new Uri(b)));}
public static void main(String[] args) throws Exception {
Context c=new Context(new File(args[0]));new File(c.getFilesDir(),"models").mkdirs();
ModelInfo original=model(c,"old","language.gguf"),oldProj=model(c,"old-p","mmproj.gguf");original.mmprojPath=oldProj.path;original.multimodal=true;
ModelStore.save(c,new ArrayList<>(Arrays.asList(original,oldProj)));
ArrayList<?> list=Pairing.loadUnified(c);assert list.size()==1;assert ModelStore.data.size()==1;
ModelInfo restored=(ModelInfo)list.get(0);assert restored.size==32;assert restored.path.equals(original.path);assert restored.mmprojPath.equals(oldProj.path);
assert Pairing.isUnified(restored);assert Pairing.displayName(restored).contains("\uD83D\uDC41");
Pairing.loadUnified(c);assert ModelStore.data.get(0).size==32; // idempotent, no double counting
ModelInfo text=model(c,"text","text.gguf");text.multimodal=true;
ModelStore.data.add(text);Pairing.loadUnified(c);assert !ModelStore.data.get(1).multimodal;assert !Pairing.displayName(text).contains("\uD83D\uDC41");
ArrayList<Uri> selection=uris("language.gguf","mmproj.gguf");Pairing.begin(c,selection);
ModelInfo newer=model(c,"new","language.gguf"),proj=model(c,"new-p","mmproj.gguf");ModelStore.data.add(newer);ModelStore.data.add(proj);
Pairing.linkSelected(c,selection);assert ModelStore.data.size()==3;
ModelInfo unit=ModelStore.data.get(2);assert unit.mmprojPath.equals(proj.path);assert unit.size==32;assert unit.multimodal;
assert ModelStore.data.get(0).mmprojPath.equals(oldProj.path); // reimport doesn't steal old pair
Pairing.linkSelected(c,selection);assert ModelStore.data.size()==3; // no fresh transaction, no mutation
Pairing.removeUnified(c,"new");assert ModelStore.data.size()==2;assert !new File(newer.path).exists();assert !new File(proj.path).exists();
assert new File(original.path).isFile() && new File(oldProj.path).isFile();
ModelInfo shared=model(c,"shared","shared.gguf");shared.mmprojPath=oldProj.path;shared.multimodal=true;ModelStore.data.add(shared);
Pairing.removeUnified(c,"old");assert new File(oldProj.path).isFile(); // still referenced
Pairing.removeUnified(c,"shared");assert !new File(oldProj.path).exists();assert !new File(shared.path).exists();
ArrayList<Uri> invalid=uris("a.gguf","b.gguf");Pairing.begin(c,invalid);ModelInfo a=model(c,"a","a.gguf"),b=model(c,"b","b.gguf");ModelStore.data.add(a);ModelStore.data.add(b);Pairing.linkSelected(c,invalid);assert ModelStore.data.size()==3;assert ModelStore.data.get(1).mmprojPath==null;
ModelInfo nullPath=model(c,"null","normal.gguf");nullPath.mmprojPath="null";assert !Pairing.isUnified(nullPath);
System.out.println("Single unit, eye, legacy migration, fresh selection, total size, reimport and component deletion: PASS");
}}'''
    }
    for name,source in sources.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source)
    pair=tmp_path/'com/ggufchat/app/Pairing.java'
    pair.write_text((ROOT/'apk-fix/java/com/ggufchat/app/Pairing.java').read_text())
    java=jdk4py.JAVA_HOME/'bin'
    subprocess.run([javac,'-d',str(tmp_path),*[str(p) for p in tmp_path.rglob('*.java')]],check=True)
    subprocess.run([str(java/'java'),'-ea','-cp',str(tmp_path),'UnitTest',str(tmp_path/'private')],check=True)


def test_projector_patch_checks_allocation_and_refuses_cpu_fallback():
    # Structural regression only. Compilation and Vulkan placement require CI.
    sample='''        if (ctx_params.use_gpu) { old_gpu_fallback(); }
        if (backend) { anything(); }
            ggml_backend_buffer_set_usage(ctx_clip.buf.get(), GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
            fin.close();'''
    out=patch_clip_gpu(sample)
    assert 'ggml_backend_init_by_name("Vulkan0"' in out
    assert 'CPU fallback disabled' in out
    assert 'if (!ctx_clip.buf)' in out
    assert 'GGUF_PROJECTOR_WEIGHTS' in out
    assert patch_clip_gpu(out)==out


def test_android_single_unit_assertion_rejects_two_records_and_wrong_size(tmp_path, monkeypatch):
    sys.path.insert(0,str(ROOT/'scripts'))
    import test_mobile
    model=tmp_path/'model.gguf';proj=tmp_path/'mmproj.gguf'
    model.write_bytes(b'1234');proj.write_bytes(b'56')
    monkeypatch.setattr(test_mobile,'MODEL',model);monkeypatch.setattr(test_mobile,'PROJ',proj)
    unit=dict(id='one',fileName=model.name,path=str(model),mmprojPath=str(proj),multimodal=True,size=6)
    assert test_mobile.unified_pair([unit],model.name,proj.name)==('one',str(model),str(proj))
    for bad in ([unit,dict(id='projector',path=str(proj))],[dict(unit,size=4)],[dict(unit,multimodal=False)]):
        with pytest.raises(AssertionError):test_mobile.unified_pair(bad,model.name,proj.name)
