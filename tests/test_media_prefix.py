from pathlib import Path
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]


def test_real_cpp_whole_chunk_planner(tmp_path):
    cpp=tmp_path/'prefix.cpp'
    cpp.write_text(r'''#include "media_prefix.h"
#include <cassert>
MediaPrefixChunk text(std::initializer_list<int32_t> t){MediaPrefixChunk c;c.text=t;c.count=c.text.size();return c;}
MediaPrefixChunk image(int key,size_t count=64){MediaPrefixChunk c;c.image=true;c.count=count;c.pixels[0]=key;return c;}
int main(){
 std::vector<MediaPrefixChunk> old{text({1,2}),image(1),text({3}),image(2),text({4,5})};
 auto in=old;in.back()=text({4,5,6,7});
 auto p=media_prefix_plan(old,in,true,0,132);assert(p.chunks==4 && p.tokens==131);
 p=media_prefix_plan(old,old,true,0,132);assert(p.chunks==4 && p.tokens==131); // replay last TEXT, obtain logits
 in=old;in[1]=image(9);p=media_prefix_plan(old,in,true,0,132);assert(p.chunks==1 && p.tokens==2); // same filename cannot identify pixels
 in=old;in[3]=image(2,65);p=media_prefix_plan(old,in,true,0,132);assert(p.chunks==3 && p.tokens==67);
 in=old;in[0]=text({9,2});assert(media_prefix_plan(old,in,true,0,132).tokens==0); // system edit
 in={old[0],old[3],old[4]};p=media_prefix_plan(old,in,true,0,132);assert(p.tokens==2); // reorder/remove images
 assert(media_prefix_plan(old,old,false,0,132).tokens==0);
 assert(media_prefix_plan(old,old,true,1,132).tokens==0); // SWA eviction
 assert(media_prefix_plan(old,old,true,0,131).tokens==0); // incomplete KV
 assert(media_prefix_plan({},old,true,0,132).tokens==0);
 assert(media_prefix_plan(old,{},true,0,132).tokens==0);
 in=old;in.pop_back();assert(media_prefix_plan(old,in,true,0,132).tokens==0); // no trailing text logits
 in=old;in[0].count=0;assert(media_prefix_plan(old,in,true,0,132).tokens==0);
 in=old;in[0].count=8;assert(media_prefix_plan(old,in,true,0,132).tokens==0);
 in=old;in[1].count=size_t(INT32_MAX)+1;assert(media_prefix_plan(old,in,true,0,132).tokens==0);
 auto huge=old;huge[1].count=INT32_MAX;assert(media_prefix_plan(huge,old,true,0,INT32_MAX).tokens==0);
}
''')
    exe=tmp_path/'prefix'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'apk-fix/native'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


def test_bridge_compiles_against_real_pinned_headers(tmp_path):
    source=ROOT/'.cache/llama-mobile'
    if not source.exists():source=ROOT/'.cache/llama-prefix-audit'
    if not source.exists():pytest.skip('Pinned upstream source required')
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()=='b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
    # Public headers plus this app's one declared fingerprint API; not mock types.
    cpp=tmp_path/'bridge.cpp'
    cpp.write_text('#include "mtmd.h"\nextern "C" int32_t mtmd_gguf_image_fingerprint(const mtmd_input_chunk *, unsigned char[32]);\n#include "media_prefix_mtmd.h"\n')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsyntax-only',
        '-I'+str(ROOT/'apk-fix/native'),'-I'+str(source/'include'),'-I'+str(source/'ggml/include'),
        '-I'+str(source/'tools/mtmd'),str(cpp)],check=True)


def test_experimental_build_and_runtime_gates_and_failure_invalidation():
    native=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    cmake=(ROOT/'apk-fix/native/CMakeLists.txt').read_text()
    bridge=(ROOT/'apk-fix/native/media_prefix_mtmd.h').read_text()
    assert 'option(GGUF_EXPERIMENT_MEDIA_PREFIX "Build explicitly opt-in multimodal KV reuse experiment" OFF)' in cmake
    assert 'std::strcmp(value,"1")==0' in bridge
    assert 'e->strict_device && e->cache_supported' in native
    assert 'mtmd_decode_use_mrope(ctx)' in bridge and 'mtmd_decode_use_non_causal(ctx,chunk)' in bridge
    assert 'llama.attention.sliding_window' in bridge and '"llama"' in bridge
    assert 'llama_memory_seq_rm(memory,0,media_plan.tokens,-1)' in native
    assert 'if(!media_plan.tokens && !media_cleared_early)llama_memory_clear(memory,true)' in native
    assert 'optimized!=reference' in native and 'media_eval(0)' in native
    failure=native[native.index('} catch(const std::exception &ex) {',native.index('static jboolean generate')):]
    assert 'e->media_prefix.clear()' in failure
    assert 'switching to text cannot reuse stale media KV' in native
    assert 'cp.n_batch=prefill_batch; cp.n_ubatch=prefill_ubatch;' in native


def test_default_native_body_unchanged_by_experiment():
    # Preprocess only the experiment blocks, compare the entire prior native file.
    import hashlib
    # Corpo nativo depois da entrega de desempenho/interface: lote de prefill
    # proporcional ao contexto, recusa de Vulkan por software e aviso visível do
    # backend. Independente da profundidade do checkout no CI.
    # Atualizado com o aquecimento de prefixo e os avisos de backend/NPU.
    # Recomputado ao tornar o sub-lote do pré-preenchimento ajustável por
    # propriedade de depuração (padrão inalterado: 128 com contexto >= 1024).
    # e ao poder medir/registrar o tipo de cache K/V (padrão inalterado: F16).
    before_sha='6fe5c4d17d741ee1d375410bc3517fe153c2bf01aa115b9f3459b3ad73aee83b'
    current=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    # Any top-level single #else guard of an opt-in experiment macro must keep
    # its #else branch byte-identical to the shipped body, not only media prefix.
    def opens(line):
        text=line.strip()
        return (text.startswith('#ifdef GGUF_EXPERIMENT_') or
                (text.startswith('#if defined(GGUF_EXPERIMENT_') and text.endswith(')')))
    lines=[];inside=False;keep=True
    for line in current.splitlines(keepends=True):
        if opens(line):
            assert not inside;inside=True;keep=False
        elif inside and line.strip()=='#else':keep=True
        elif inside and line.strip()=='#endif':inside=False;keep=True
        elif keep:lines.append(line)
    assert not inside
    computed=hashlib.sha256(''.join(lines).encode()).hexdigest()
    # A mensagem traz o valor medido: atualizar o pin é uma decisão, não uma adivinhação.
    assert computed==before_sha, f'corpo nativo padrão mudou: {computed}'


def test_actual_eligibility_function_rejects_noncausal_and_swa_metadata(tmp_path):
    source=ROOT/'.cache/llama-mobile'
    if not source.exists():source=ROOT/'.cache/llama-prefix-audit'
    if not source.exists():pytest.skip('Pinned upstream headers required')
    cpp=tmp_path/'eligibility.cpp'
    cpp.write_text(r'''#include "mtmd.h"
extern "C" int32_t mtmd_gguf_image_fingerprint(const mtmd_input_chunk *, unsigned char[32]);
#include "media_prefix_mtmd.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <string>
// Metadata API fixture only; exercise the actual C++ eligibility function.
std::map<std::string,std::string> metadata;
extern "C" int32_t llama_model_meta_val_str(const llama_model *,const char *key,char *dst,size_t size){
 auto it=metadata.find(key);if(it==metadata.end())return -1;
 return snprintf(dst,size,"%s",it->second.c_str());
}
int main(){
 assert(!media_prefix_model(nullptr));
 metadata["general.architecture"]="llama";assert(media_prefix_model(nullptr));
 metadata["llama.attention.causal"]="true";assert(media_prefix_model(nullptr));
 metadata["llama.attention.causal"]="false";assert(!media_prefix_model(nullptr));
 metadata["llama.attention.causal"]="unknown";assert(!media_prefix_model(nullptr));
 metadata.erase("llama.attention.causal");
 metadata["llama.attention.sliding_window"]="0";assert(media_prefix_model(nullptr));
 metadata["llama.attention.sliding_window"]="4096";assert(!media_prefix_model(nullptr));
 metadata.erase("llama.attention.sliding_window");
 metadata["general.architecture"]="gemma3";assert(!media_prefix_model(nullptr));
 metadata["general.architecture"]=std::string(1000,'a');assert(!media_prefix_model(nullptr));
}
''')
    exe=tmp_path/'eligibility'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'apk-fix/native'),
        '-I'+str(source/'include'),'-I'+str(source/'ggml/include'),'-I'+str(source/'tools/mtmd'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


def test_control_and_cold_clear_keep_original_timing():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'media_cleared_early=!media_requested || e->media_prefix.empty()' in s
    at=s.index('if(media_cleared_early)')
    assert at<s.index('const auto bitmap_started=Clock::now()')
    assert s.index('llama_memory_clear(memory,true);e->media_prefix.clear()',at)<s.index('const auto bitmap_started=Clock::now()')
