#!/usr/bin/env python3
from compute_patches import patch_compute
"""Build a coherent native stack and an UNSIGNED APK, for local persistent signing.
No signing key or password is placed in CI, artifacts, logs or Git.
"""
import copy, hashlib, json, os, re, shutil, struct, subprocess, sys, textwrap, zipfile
from mobile_manifest import enforce_min_sdk
from attachment_manifest import attachment_manifest
from attachment_patches import patch_attachments
from unified_mobile import patch_unified_ui, patch_clip_gpu
from physical_gguf import patch_physical_ui, patch_combined_loader
from import_progress import patch_import_progress
from single_import_ui import patch_single_import_ui
from pathlib import Path
from build_apk import ORIGINAL_APK_SHA256, signature_entry, verify_alignment
from build_diagnostics import ndk_root, build_diagnostics
from patch_dex import patch_bytes
from patch_smali import apply

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.cache/mobile'
SOURCE_SHA='b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'

def run(*args): subprocess.run([str(a) for a in args],check=True)
def method_replace(s, signature, replacement):
    start=s.index(signature);end=s.index('.end method',start)+len('.end method')
    return s[:start]+replacement+s[end:]

def ui_patches(app):
    p=app/'Ui.smali';s=p.read_text();a=s.index('.method public static btn(');b=s.index('.end method',a)
    segment=s[a:b].replace('    return-object v0','    invoke-static {v0}, Lcom/ggufchat/app/CompactUi;->style(Landroid/widget/Button;)V\n\n    return-object v0')
    p.write_text(s[:a]+segment+s[b:])
    p=app/'ChatActivity.smali';s=p.read_text();marker='    invoke-virtual {p0, v2}, Lcom/ggufchat/app/ChatActivity;->setContentView(Landroid/view/View;)V'
    assert s.count(marker)==1
    s=s.replace(marker,'    invoke-static {p0, v2, v1, v4, v0}, Lcom/ggufchat/app/CompactUi;->install(Landroid/app/Activity;Landroid/widget/LinearLayout;Landroid/widget/LinearLayout;Landroid/widget/Button;Landroid/widget/Button;)V\n\n'+marker)
    p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text();a=s.index('.method private navButton(');b=s.index('.end method',a);s=s[:a]+s[a:b].replace('    return-object v0','    invoke-static {v0}, Lcom/ggufchat/app/CompactUi;->style(Landroid/widget/Button;)V\n    return-object v0')+s[b:];s=method_replace(s,'.method private linkMmprojs()V','.method private linkMmprojs()V\n    .locals 0\n    invoke-direct {p0}, Lcom/ggufchat/app/MainActivity;->refreshModels()V\n    return-void\n.end method');p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text()
    a=s.index('.method protected onActivityResult(');b=s.index('.end method',a)
    part=s[a:b];marker='    invoke-direct {p0, v1, v2}, Lcom/ggufchat/app/MainActivity;->importModel(Landroid/net/Uri;Ljava/lang/Runnable;)V'
    assert part.count(marker)==1
    part=part.replace(marker,'    invoke-static {p0, v0}, Lcom/ggufchat/app/AtomicPairImport;->start(Landroid/content/Context;Ljava/util/ArrayList;)Z\n    move-result v3\n    if-eqz v3, :not_atomic_pair\n    return-void\n    :not_atomic_pair\n'+marker)
    s=s[:a]+part+s[b:]
    a=s.index('.method private refreshImportList()V');b=s.index('.end method',a)
    part=s[a:b];marker='    move-result-object v1'
    assert part.count(marker)==2
    part=part.replace(marker,marker+'\n    invoke-static {v1}, Lcom/ggufchat/app/Pairing;->visibleModels(Ljava/util/ArrayList;)Ljava/util/ArrayList;\n    move-result-object v1',1)
    s=s[:a]+part+s[b:]
    a=s.index('.method private buildImportRow(');b=s.index('.end method',a)
    part=s[a:b];marker='    iget-object v1, p1, Lcom/ggufchat/app/ModelInfo;->name:Ljava/lang/String;'
    assert part.count(marker)==1
    part=part.replace(marker,'    invoke-static {p1}, Lcom/ggufchat/app/Pairing;->displayName(Ljava/lang/Object;)Ljava/lang/String;\n    move-result-object v1')
    s=s[:a]+part+s[b:];p.write_text(s)
    # Some callers replace Ui.btn's LayoutParams afterwards. Restyle at those
    # actual call sites too, so WRAP_CONTENT cannot collapse the import button.
    for p in app.glob('*.smali'):
        s=p.read_text()
        s=re.sub(r'(    invoke-virtual \{([vp]\d+), [vp]\d+\}, Landroid/widget/Button;->setLayoutParams\(Landroid/view/ViewGroup\$LayoutParams;\)V)',r'\1\n    invoke-static {\2}, Lcom/ggufchat/app/CompactUi;->style(Landroid/widget/Button;)V',s)
        p.write_text(s)
    p=app/'MainActivity$25.smali';s=p.read_text().replace('if-nez v1, :cond_0','if-eqz v1, :cond_0').replace('if-nez v2, :cond_0','if-eqz v2, :cond_0');p.write_text(s)
    # Safer defaults for a mobile memory budget; user can deliberately change them.
    p=app/'Settings.smali';s=p.read_text();a=s.index('.method public static gpuLayers(');b=s.index('.end method',a);s=s[:a]+s[a:b].replace('const/4 v2, -0x1','const/4 v2, 0x0')+s[b:]
    a=s.index('.method public static contextSize(');b=s.index('.end method',a);s=s[:a]+s[a:b].replace('const/16 v2, 0x1000','const/16 v2, 0x400')+s[b:];p.write_text(s)
    # Surface the actual native create error rather than labelling every failure corrupt GGUF.
    p=app/'EngineManager.smali';s=p.read_text();marker='    const-string v1, "N\\u00e3o foi poss\\u00edvel carregar o modelo. Verifique se o arquivo GGUF est\\u00e1 \\u00edntegro."'
    assert marker in s
    s=s.replace(marker,'    invoke-static {v4, v5}, Lcom/ggufchat/app/Native;->lastError(J)Ljava/lang/String;\n    move-result-object v1');p.write_text(s)
    p=app/'ChatActivity$16.smali';s=p.read_text();marker='    const-string v3, "N\\u00e3o foi poss\\u00edvel carregar o modelo. Verifique se o arquivo GGUF est\\u00e1 \\u00edntegro."'
    assert marker in s;s=s.replace(marker,'    invoke-virtual {v0}, Ljava/lang/Throwable;->getMessage()Ljava/lang/String;\n    move-result-object v3');p.write_text(s)
    patch_unified_ui(app)
    patch_attachments(app)
    patch_physical_ui(app)
    patch_import_progress(app)
    patch_single_import_ui(app)
    patch_compute(app)

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    original=ROOT/'.cache/gguf/GGUF-Chat.apk'
    assert hashlib.sha256(original.read_bytes()).hexdigest()==ORIGINAL_APK_SHA256
    ndk=ndk_root(); sdk=Path(os.environ['ANDROID_HOME']); java=Path(os.environ['JAVA_HOME'])/'bin/java'
    apktool=Path(os.environ['APKTOOL_JAR']);source=ROOT/'.cache/llama-mobile'
    if not source.exists(): run('git','clone','--depth','1','--branch','v0.4.1','https://github.com/ggml-org/llama.cpp',source)
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==SOURCE_SHA
    vk=source/'ggml/src/ggml-vulkan/ggml-vulkan.cpp';s=vk.read_text();old='device_extensions.push_back("VK_KHR_16bit_storage");'
    if old in s:
        s=s.replace(old,'// Core Vulkan 1.2 already requires the queried 16-bit storage feature; no extension alias required.')
    # Never publish a half-created device: a failed initialization used to leave
    # a cached object with a null VkDevice, crashing the next loading attempt.
    start=s.index('static vk_device ggml_vk_get_device(size_t idx) {')
    end=s.index('\nstatic ',start+10)
    part=s[start:end]
    early='        vk_instance.devices[idx] = device;'
    if early in part:
        part=part.replace(early,'',1).replace('        return device;','        vk_instance.devices[idx] = device;\n        return device;')
        s=s[:start]+part+s[end:]
    # A thrown vkCreateDevice leaves the local shared_ptr destructing a null
    # device. Guard cleanup too, not just publication into the global cache.
    destructor='        VK_LOG_DEBUG("destroy device " << name);'
    assert s.count(destructor)==1
    if destructor+'\n        if (!device) return;' not in s:
        s=s.replace(destructor,destructor+'\n        if (!device) return; // failed initialization owns no Vulkan resources')
    vk.write_text(s)
    clip=source/'tools/mtmd/clip.cpp';clip.write_text(patch_clip_gpu(clip.read_text()))
    loader=source/'src/llama-model-loader.cpp';loader.write_text(patch_combined_loader(loader.read_text()))
    classes=WORK/'classes';classes.mkdir(exist_ok=True)
    android=sdk/'platforms/android-35/android.jar'
    sys.path.insert(0,str(ROOT/'scripts'))
    from fetch_document_libraries import fetch as fetch_documents
    document_jars,document_assets=fetch_documents()
    sources=list((ROOT/'apk-fix/java').rglob('*.java'))
    run(Path(os.environ['JAVA_HOME'])/'bin/javac','--release','8','-classpath',os.pathsep.join(map(str,[android]+document_jars)),'-d',classes,*sources)
    dexdir=WORK/'helpers';dexdir.mkdir(exist_ok=True)
    run(sdk/'build-tools/35.0.0/d8','--min-api','28','--lib',android,'--output',dexdir,*classes.rglob('*.class'))
    documents_dex=WORK/'documents-dex';documents_dex.mkdir(exist_ok=True)
    run(sdk/'build-tools/35.0.0/d8','--min-api','28','--lib',android,'--output',documents_dex,*document_jars)
    native_origin=None
    if os.environ.get('GGUF_REUSE_TESTED_NATIVE')=='1':
        base=json.loads((ROOT/'ci/mobile-native-base.json').read_text())
        assert base['llama_commit']==SOURCE_SHA
        recipe=Path(__file__).read_text()
        vk_recipe=re.search(r'(?ms)^    vk=source/.*?(?=^    native_origin=)',recipe).group()
        compile_recipe=re.search(r'(?ms)^        libs=build_diagnostics\(WORK\).*?(?=^    intermediate=)',recipe).group()
        digest=hashlib.sha256((vk_recipe+textwrap.dedent(compile_recipe)).encode()).hexdigest()
        assert digest==base['native_recipe_sha256'],'Native recipe changed: disable cache and rebuild'
        for name,digest in base['source_inputs'].items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, 'Native source changed: disable GGUF_REUSE_TESTED_NATIVE and rebuild'
        libs={}
        with zipfile.ZipFile(ROOT/'.delivery/GGUF-Chat-mobile.apk') as cached:
            for name,digest in base['native'].items():
                data=cached.read(name)
                assert hashlib.sha256(data).hexdigest()==digest, 'Tested native cache mismatch'
                libs[name]=data
        native_origin=base['source_commit']
        print('Reusing exact native payload from verified Android run',base['verified_android_run'])
    else:
        libs=build_diagnostics(WORK)
        prebuilt=ndk/'toolchains/llvm/prebuilt/linux-x86_64'
        for abi,triple in [('arm64-v8a','aarch64-linux-android'),('x86_64','x86_64-linux-android')]:
            build=WORK/abi
            run('cmake','-S',ROOT/'apk-fix/native','-B',build,'-G','Ninja',f'-DLLAMA_SOURCE={source}',f'-DGGUF_SPIRV_INCLUDE_DIR={ROOT}/.cache/spirv-install/include',f'-DSPIRV-Headers_DIR={ROOT}/.cache/spirv-install/share/cmake/SPIRV-Headers',f'-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake',f'-DANDROID_ABI={abi}','-DANDROID_PLATFORM=android-28','-DCMAKE_BUILD_TYPE=Release',f'-DVulkan_INCLUDE_DIR={ROOT}/.cache/vulkan-headers',f'-DVulkan_LIBRARY={prebuilt}/sysroot/usr/lib/{triple}/28/libvulkan.so','-DVulkan_GLSLC_EXECUTABLE=/usr/bin/glslc')
            run('cmake','--build',build,'--target','aijni','--parallel','2')
            for name,src in [('libaijni.so',build/'libaijni.so'),('libc++_shared.so',prebuilt/f'sysroot/usr/lib/{triple}/libc++_shared.so')]:
                dest=WORK/f'{abi}-{name}';shutil.copyfile(src,dest);run(prebuilt/'bin/llvm-strip','--strip-debug',dest)
                libs[f'lib/{abi}/{name}']=dest.read_bytes()
    intermediate=WORK/'intermediate.apk'
    with zipfile.ZipFile(original) as a,zipfile.ZipFile(intermediate,'w') as b:
        for n in a.namelist():
            if not signature_entry(n): b.writestr(n,patch_bytes(a.read(n)) if n=='classes.dex' else a.read(n),compress_type=zipfile.ZIP_DEFLATED)
    decoded=WORK/'decoded';run(java,'-jar',apktool,'d','-f','-r','-o',decoded,intermediate)
    apply(decoded);app=decoded/'smali/com/ggufchat/app';ui_patches(app)
    # Decode the helper dex into smali; no handwritten bytecode or compile-only stubs.
    jar=WORK/'helper.apk'
    with zipfile.ZipFile(jar,'w') as z:
        with zipfile.ZipFile(intermediate) as a: z.writestr('AndroidManifest.xml',a.read('AndroidManifest.xml'))
        z.writestr('classes.dex',(dexdir/'classes.dex').read_bytes())
    helper=WORK/'helper-decoded';run(java,'-jar',apktool,'d','-f','-r','-o',helper,jar)
    for p in (helper/'smali/com/ggufchat/app').glob('*.smali'):shutil.copyfile(p,app/p.name)
    compiled=WORK/'compiled.apk';run(java,'-jar',apktool,'b',decoded,'-o',compiled)
    out=ROOT/'dist/GGUF-Chat-mobile-unsigned.apk';out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(original) as a,zipfile.ZipFile(compiled) as c,zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as b:
        for n in a.namelist():
            if signature_entry(n) or n.startswith('lib/'):continue
            data=c.read('classes.dex') if n=='classes.dex' else a.read(n)
            if n=='AndroidManifest.xml':data=attachment_manifest(data)
            info=copy.copy(a.getinfo(n));info.extra=b''
            if info.compress_type==zipfile.ZIP_STORED:
                offset=b.fp.tell()+30+len(n.encode('ascii'))
                if offset%4:
                    padding=(-offset)%4;info.extra=struct.pack('<HH',0xD935,padding)+bytes(padding)
            b.writestr(info,data)
        for i,p in enumerate(sorted(documents_dex.glob('classes*.dex')),2):b.writestr(f'classes{i}.dex',p.read_bytes())
        for n,data in document_assets.items():
            assert n not in a.namelist(),n
            b.writestr(n,data)
        for license in (ROOT/'docs/licenses').iterdir():
            if license.is_file():b.writestr('assets/third-party/'+license.name,license.read_bytes())
        b.writestr('assets/document-libraries-sha256.json',(ROOT/'.cache/document-libs/sha256.json').read_bytes())
        for n,data in libs.items():b.writestr(n,data)
    verify_alignment(out)
    with zipfile.ZipFile(original) as a,zipfile.ZipFile(out) as b:
        for n in a.namelist():
            if n not in ('classes.dex','AndroidManifest.xml') and not signature_entry(n) and not n.startswith('lib/'):assert a.read(n)==b.read(n)
        assert b.read('AndroidManifest.xml')==attachment_manifest(a.read('AndroidManifest.xml'))
        assert {n for n in b.namelist() if n.startswith('lib/')}==set(libs)
    metadata={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'llama_commit':SOURCE_SHA,'min_sdk':28,'native_source_commit':native_origin or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'status':'UNSIGNED_NOT_APPROVED','native':{n:hashlib.sha256(v).hexdigest() for n,v in libs.items()}}
    (out.parent/'mobile-build.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata))
if __name__=='__main__':main()
