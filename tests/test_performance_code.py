from pathlib import Path
import subprocess,shutil,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]

def test_runtime_cpu_dispatch_and_auto_threads(tmp_path):
    p=tmp_path/'cpu.cpp';p.write_text('''#include "cpu_dispatch.h"
#include "cpu_threads.h"
#include <cassert>
int main(){
 uint64_t required=(1ULL<<9)|(1ULL<<10)|(1ULL<<20);
 assert(cpu_variant(0,0)==0);
 for(int bit: {9,10,20})assert(cpu_variant(required&~(1ULL<<bit),1ULL<<13)==0);
 assert(cpu_variant(required,0)==1);assert(cpu_variant(required,1ULL<<13)==2);
 assert(resolve_cpu_threads(0,8,{})==4);assert(resolve_cpu_threads(0,1,{})==1);
 assert(resolve_cpu_threads(0,8,{400,400,400,400,800,800,800,1024})==4);
 assert(resolve_cpu_threads(0,8,{400,400,400,400,400,400,1024,1024})==2);
 assert(resolve_cpu_threads(0,8,{1024})==4); // incomplete sysfs, fallback
 assert(resolve_cpu_threads(0,8,{0,0,0,0,0,0,0,0})==4);
 assert(resolve_cpu_threads(2,8,{})==2);assert(resolve_cpu_threads(1,8,{})==1);
}''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Iapk-fix/native',str(p),'-o',str(tmp_path/'cpu')],check=True)
    subprocess.run([str(tmp_path/'cpu')],check=True)

def test_parser_exact_code_every_chunk_boundary(tmp_path):
    javac=shutil.which('javac');java=shutil.which('java')
    if not javac or not java:pytest.skip('JDK needed; also run in hosted build')
    p=tmp_path/'CodeTest.java';p.write_text(r'''import com.ggufchat.app.CodeFenceParser;
public class CodeTest {
 static class S implements CodeFenceParser.Sink {
  StringBuilder text=new StringBuilder(),code=new StringBuilder(); int opens,closes;
  public void text(String s){text.append(s);}public void code(String s){code.append(s);}
  public void open(String s){opens++;}public void close(){closes++;}
 }
 static void check(String input,String text,String code,int opens,int closes){
  for(int chunk=1;chunk<=input.length()+1;chunk++){
   S s=new S();CodeFenceParser p=new CodeFenceParser(s);
   for(int i=0;i<input.length();i+=chunk)p.feed(input.substring(i,Math.min(input.length(),i+chunk)));
   p.finish();if(!s.text.toString().equals(text)||!s.code.toString().equals(code)||s.opens!=opens||s.closes!=closes)
    throw new AssertionError("chunk="+chunk+" text="+s.text+" code="+s.code);
  }
 }
 public static void main(String[] args){
  check("Antes\n```python\n  print(\"ação\")\n\n```\nDepois","Antes\nDepois","  print(\"ação\")\n\n",1,1);
  check("~~~~js\r\nlet n = 1;\r\n~~~~\r\n","","let n = 1;\r\n",1,1);
  check("```txt\nx\n```not closing\ny","","x\n```not closing\ny",1,0);
  check("````txt\n```\n````","","```\n",1,1);
  check("a `b` c\n    ```not a fence\n","a `b` c\n    ```not a fence\n","",0,0);
  check("``","``","",0,0);check("```","","",1,0);
  check("```a\nx\n```\n```b\ny\n```","","x\ny\n",2,2);
  check("```\n<script>alert(1)</script>\n```","","<script>alert(1)</script>\n",1,1);
 }
}''')
    subprocess.run([javac,'-d',str(tmp_path),'apk-fix/java/com/ggufchat/app/CodeFenceParser.java',str(p)],check=True)
    subprocess.run([java,'-cp',str(tmp_path),'CodeTest'],check=True)

def test_build_variants_have_safe_baseline_dispatch_and_no_quality_changes():
    s=(ROOT/'apk-fix/build_mobile.py').read_text();cpp=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'armv8-a+dotprod+fp16' in s and 'armv8-a+dotprod+fp16+i8mm' in s
    assert 'libggufcpu.so' in s and "'-UHAVE_*'" in s
    assert 'cp.n_batch=prefill_batch; cp.n_ubatch=prefill_ubatch;' in cpp
    assert 'prefill_batch=context>=1024?512:(context>=512?256:128)' in cpp
    assert 'software_vulkan_device(vulkan_devices[0],&description)' in cpp
    assert 'output_mask.back()=1' in cpp and 'batch.logits=output_mask.data()' in cpp
    assert 'generation_threads(threads)' in cpp
    java=(ROOT/'apk-fix/java/com/ggufchat/app/NativeDispatch.java').read_text()
    assert java.index('cpuVariant()')<java.index('library="aijni_i8mm"')
    assert 'UnsatisfiedLinkError' in java and 'System.loadLibrary(library)' in java

def test_real_bytecode_wiring(tmp_path):
    base=ROOT/'.cache/perf-base/smali/com/ggufchat/app'
    if not base.exists():pytest.skip('Decoded baseline required')
    sys.path.insert(0,str(ROOT/'apk-fix'));from performance_ui import patch_performance_ui
    for name in ['ChatActivity.smali','Native.smali']:shutil.copyfile(base/name,tmp_path/name)
    patch_performance_ui(tmp_path)
    s=(tmp_path/'ChatActivity.smali').read_text()
    assert s.count('CodeBlocks;->append(')==1 and s.count('CodeBlocks;->decorate(')==1
    assert s.count('ResponseTiming;->sent(')==1 and s.count('ResponseTiming;->first(')==1
    assert 'NativeDispatch;->load()' in (tmp_path/'Native.smali').read_text()


def test_gpu_sampler_lifetime_and_original_parameters():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    binding=s[s.index('        // Full backend chain required'):s.index('        LOG("GGUF_GPU_SAMPLING')]
    assert 'if(e->layers>0)' in binding and 'binding.attached=llama_set_sampler(e->ctx,0,sampler.get())' in binding
    assert 'if(!binding.attached)throw std::runtime_error' in binding
    assert 'llama_synchronize(ctx);' in s and 'llama_set_sampler(ctx,0,nullptr)' in s
    assert s.index('std::unique_ptr<llama_sampler')<s.index('BackendSamplerBinding binding')<s.index('if(n_images)')
    assert 'llama_sampler_init_dist(seed)' in s and 'llama_sampler_init_penalties' in s
    assert 'GGUF_GPU_SAMPLING_RESULT backend_selected=' in s


def test_gpu_prefill_is_completed_before_decode_clock_starts():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    boundary=s[s.index('prompt_tokens=input_size;'):s.index('int limit=std::min<int>')]
    assert boundary.index('llama_synchronize(e->ctx)')<boundary.index('decode_started=Clock::now()')
    j=(ROOT/'apk-fix/java/com/ggufchat/app/GenerationStats.java').read_text()
    assert 'prefill_synchronized_before_decode' in j and 'j.put("version",3)' in j
