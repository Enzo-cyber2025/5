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
        'android/app/Activity.java': 'package android.app;import android.content.Context;public class Activity extends Context {public Activity(){super(null);}public void runOnUiThread(Runnable r){r.run();}}',
        'org/json/JSONObject.java': 'package org.json;public class JSONObject {public String optString(String k,String d){return d;}public JSONObject put(String k,Object v){return this;}}',
        'UnitTest.java': r'''import com.ggufchat.app.*;import android.content.Context;import android.net.Uri;import java.io.*;import java.nio.file.*;import java.util.*;
public class UnitTest {
static File fixtures;
static ModelInfo model(Context c,String id,String filename,boolean projector) throws Exception {ModelInfo m=new ModelInfo();m.id=id;m.name="Test";m.fileName=filename;m.path=new File(c.getFilesDir(),"models/"+id+"_"+filename).getPath();Files.copy(new File(fixtures,projector?"vision.gguf":"language.gguf").toPath(),Paths.get(m.path));m.size=new File(m.path).length();Pairing.inspect(m);return m;}
static ArrayList<Uri> uris(String a,String b){return new ArrayList<>(Arrays.asList(new Uri(a),new Uri(b)));}
static void waitMerge() throws Exception {long end=System.currentTimeMillis()+10000;while(Pairing.merging()&&System.currentTimeMillis()<end)Thread.sleep(10);assert !Pairing.merging();}
public static void main(String[] args) throws Exception {
fixtures=new File(args[1]);Context c=new Context(new File(args[0]));new File(c.getFilesDir(),"models").mkdirs();
ModelInfo original=model(c,"old","language.gguf",false),oldProj=model(c,"old-p","vision.gguf",true);original.mmprojPath=oldProj.path;original.multimodal=true;
ModelStore.save(c,new ArrayList<>(Arrays.asList(original,oldProj)));
ArrayList<?> list=Pairing.loadUnified(c);assert list.size()==1;assert ModelStore.data.size()==1;
assert ((ModelInfo)list.get(0)).size==original.size+oldProj.size;
ModelInfo text=model(c,"text","mmproj-misleading.gguf",false);ModelStore.data.add(text);
assert !text.multimodal;assert !Pairing.displayName(text).contains("\uD83D\uDC41");
ArrayList<Uri> selection=uris("mmproj-language.gguf","ordinary.gguf");Pairing.begin(c,selection);
ModelInfo newer=model(c,"new","mmproj-language.gguf",false),proj=model(c,"new-p","ordinary.gguf",true);ModelStore.data.add(newer);ModelStore.data.add(proj);
Pairing.linkSelected(c,selection);waitMerge();assert ModelStore.data.size()==3;
ModelInfo unit=ModelStore.data.get(2);assert unit.path.equals(unit.mmprojPath);assert unit.size==new File(unit.path).length();assert unit.multimodal;
assert GgufFile.read(new File(unit.path)).singleVision();assert Pairing.displayName(unit).contains("\uD83D\uDC41");
assert !new File(newer.path).exists()&&!new File(proj.path).exists();
assert ModelStore.data.get(0).mmprojPath.equals(oldProj.path);
Pairing.loadUnified(c);assert ModelStore.data.get(2).size==unit.size; // self path counted once
Pairing.removeUnified(c,"new");assert !new File(unit.path).exists();assert new File(original.path).exists()&&new File(oldProj.path).exists();
ArrayList<Uri> invalid=uris("a.gguf","b.gguf");Pairing.begin(c,invalid);ModelStore.data.add(model(c,"a","a.gguf",false));ModelStore.data.add(model(c,"b","b.gguf",false));Pairing.linkSelected(c,invalid);waitMerge();assert ModelStore.data.size()==4;
System.out.println("Physical single file, parameter detection, misleading filenames, persistence, legacy preservation, deletion and invalid selection: PASS");
}}'''
    }
    sources['com/ggufchat/app/ModelInfo.java']=sources['com/ggufchat/app/ModelInfo.java'].replace('public String id,','public String capability,id,').replace('n.id=id;','n.capability=capability;n.id=id;')
    from test_physical_gguf import fixture
    fixture(tmp_path/'language.gguf');fixture(tmp_path/'vision.gguf','projector')
    for name,source in sources.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source)
    pair=tmp_path/'com/ggufchat/app/Pairing.java'
    pair.write_text((ROOT/'apk-fix/java/com/ggufchat/app/Pairing.java').read_text())
    (tmp_path/'com/ggufchat/app/GgufFile.java').write_text((ROOT/'apk-fix/java/com/ggufchat/app/GgufFile.java').read_text())
    java=jdk4py.JAVA_HOME/'bin'
    subprocess.run([javac,'-d',str(tmp_path),*[str(p) for p in tmp_path.rglob('*.java')]],check=True)
    subprocess.run([str(java/'java'),'-ea','-cp',str(tmp_path),'UnitTest',str(tmp_path/'private'),str(tmp_path)],check=True)


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
