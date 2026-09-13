#!/usr/bin/env python3
"""Build a coherent native stack and an UNSIGNED APK, for local persistent signing.
No signing key or password is placed in CI, artifacts, logs or Git.
"""
import hashlib, json, os, shutil, subprocess, sys, zipfile
from pathlib import Path
from build_apk import ORIGINAL_APK_SHA256, signature_entry, verify_alignment
from build_diagnostics import ndk_root, build_diagnostics
from patch_dex import patch_bytes
from patch_smali import apply

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.cache/mobile'
SOURCE_SHA='a7a98e0fffed794396b3fbad4dcdbbc184963645'

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
    # Link precisely the selection and remove the old global guesser.
    p=app/'MainActivity$26.smali';s=p.read_text();marker='    invoke-static {v0}, Lcom/ggufchat/app/MainActivity;->access$1900(Lcom/ggufchat/app/MainActivity;)V'
    assert s.count(marker)==1
    s=s.replace(marker,'    invoke-static {v0, v1}, Lcom/ggufchat/app/Pairing;->linkSelected(Landroid/content/Context;Ljava/util/ArrayList;)V\n\n'+marker);p.write_text(s)
    p=app/'MainActivity.smali';s=p.read_text();a=s.index('.method private navButton(');b=s.index('.end method',a);s=s[:a]+s[a:b].replace('    return-object v0','    invoke-static {v0}, Lcom/ggufchat/app/CompactUi;->style(Landroid/widget/Button;)V\n    return-object v0')+s[b:];s=method_replace(s,'.method private linkMmprojs()V','.method private linkMmprojs()V\n    .locals 0\n    invoke-direct {p0}, Lcom/ggufchat/app/MainActivity;->refreshModels()V\n    return-void\n.end method');p.write_text(s)
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

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    original=ROOT/'.cache/gguf/GGUF-Chat.apk'
    assert hashlib.sha256(original.read_bytes()).hexdigest()==ORIGINAL_APK_SHA256
    ndk=ndk_root(); sdk=Path(os.environ['ANDROID_HOME']); java=Path(os.environ['JAVA_HOME'])/'bin/java'
    apktool=Path(os.environ['APKTOOL_JAR']);source=ROOT/'.cache/llama-mobile'
    if not source.exists(): run('git','clone','--depth','1','--branch','b6500','https://github.com/ggml-org/llama.cpp',source)
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
    vk.write_text(s)
    libs=build_diagnostics(WORK)
    prebuilt=ndk/'toolchains/llvm/prebuilt/linux-x86_64'
    for abi,triple in [('arm64-v8a','aarch64-linux-android'),('x86_64','x86_64-linux-android')]:
        build=WORK/abi
        run('cmake','-S',ROOT/'apk-fix/native','-B',build,'-G','Ninja',f'-DLLAMA_SOURCE={source}',f'-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake',f'-DANDROID_ABI={abi}','-DANDROID_PLATFORM=android-28','-DCMAKE_BUILD_TYPE=Release',f'-DVulkan_INCLUDE_DIR={ROOT}/.cache/vulkan-headers',f'-DVulkan_LIBRARY={prebuilt}/sysroot/usr/lib/{triple}/28/libvulkan.so','-DVulkan_GLSLC_EXECUTABLE=/usr/bin/glslc')
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
    classes=WORK/'classes';classes.mkdir(exist_ok=True)
    android=sdk/'platforms/android-35/android.jar'
    sources=list((ROOT/'apk-fix/java').rglob('*.java'))
    run(Path(os.environ['JAVA_HOME'])/'bin/javac','-source','8','-target','8','-bootclasspath',android,'-d',classes,*sources)
    dexdir=WORK/'helpers';dexdir.mkdir(exist_ok=True)
    run(sdk/'build-tools/35.0.0/d8','--min-api','28','--lib',android,'--output',dexdir,*classes.rglob('*.class'))
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
            b.writestr(n,c.read('classes.dex') if n=='classes.dex' else a.read(n))
        for n,data in libs.items():b.writestr(n,data)
    verify_alignment(out)
    with zipfile.ZipFile(original) as a,zipfile.ZipFile(out) as b:
        for n in a.namelist():
            if n!='classes.dex' and not signature_entry(n) and not n.startswith('lib/'):assert a.read(n)==b.read(n)
        assert {n for n in b.namelist() if n.startswith('lib/')}==set(libs)
    metadata={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'llama_commit':SOURCE_SHA,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'status':'UNSIGNED_NOT_APPROVED','native':{n:hashlib.sha256(v).hexdigest() for n,v in libs.items()}}
    (out.parent/'mobile-build.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata))
if __name__=='__main__':main()
