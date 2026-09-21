"""Exact layout and guarded opt-in tests; host CPU execution is NOT Vulkan proof."""
import sys,subprocess,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from image_upload_patches import LAYOUT,patch_image_upload,GRAPH_NEW,UPLOAD,VERIFY,DIGEST
SRC=ROOT/'.cache/llama-mobile'

def test_patch_is_guarded_idempotent_and_preserves_host_decode(tmp_path):
    if not (SRC/'tools/mtmd/clip.cpp').exists():pytest.skip('Pinned source required')
    dest=tmp_path/'tools/mtmd';dest.mkdir(parents=True)
    p=dest/'clip.cpp';p.write_bytes((SRC/'tools/mtmd/clip.cpp').read_bytes())
    patch_image_upload(tmp_path);once=p.read_text();patch_image_upload(tmp_path);assert p.read_text()==once
    assert GRAPH_NEW in once and UPLOAD in once and VERIFY in once and DIGEST in once
    assert 'model.modality == CLIP_MODALITY_VISION' in GRAPH_NEW
    assert 'ggml_backend_gguf_strict_device()' in GRAPH_NEW and 'GGUF_VULKAN_IMAGE_PACK' in GRAPH_NEW
    assert 'if (verify) ggml_set_output(planar)' in LAYOUT
    assert 'std::vector<float> inp_raw(nelem);' in once # default/audio/CPU behavior retained
    assert 'ggml_backend_tensor_set(rgb, pixels.data(), offset, bytes)' in once
    p.write_text(once.replace('2, 0, 1, 3','0, 1, 2, 3'))
    with pytest.raises(AssertionError,match='Stale'):patch_image_upload(tmp_path)

def test_actual_ggml_graph_matches_cpu_reference_bytes(tmp_path):
    build=ROOT/'.cache/strict-host/ggml/src'
    libs=[build/n for n in ('libggml.a','libggml-cpu.a','libggml-base.a')]
    if not all(p.exists() for p in libs):pytest.skip('Build real ggml with scripts/test_strict_vulkan_host.sh first')
    cpp=tmp_path/'layout.cpp';cpp.write_text('''#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "ggml-alloc.h"
#include <vector>
#include <cassert>
#include <cstring>
'''+LAYOUT+r'''
void check(int w,int h,int batches){
 auto *ctx=ggml_init({1024*1024,nullptr,true});assert(ctx);
 auto *out=gguf_rgb_planar_graph(ctx,w,h,batches,true);
 auto *g=ggml_new_graph(ctx);ggml_build_forward_expand(g,out);
 auto *in=ggml_graph_get_tensor(g,"gguf_inp_rgb");assert(in);
 assert(out->ne[0]==w&&out->ne[1]==h&&out->ne[2]==3&&out->ne[3]==batches);
 auto backend=ggml_backend_cpu_init();assert(backend);
 auto buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);assert(buffer);
 size_t n=(size_t)w*h;std::vector<float> source(n*3*batches),actual(source.size());
 for(size_t i=0;i<source.size();i++)source[i]=float(int(i%1999)-999)/32.0f;
 source[0]=-0.0f;
 ggml_backend_tensor_set(in,source.data(),0,source.size()*sizeof(float));
 assert(ggml_backend_graph_compute(backend,g)==GGML_STATUS_SUCCESS);
 ggml_backend_tensor_get(out,actual.data(),0,actual.size()*sizeof(float));
 for(int b=0;b<batches;b++)for(int c=0;c<3;c++)for(size_t p=0;p<n;p++)
  assert(!memcmp(&actual[(b*3+c)*n+p],&source[(b*n+p)*3+c],sizeof(float)));
 ggml_backend_buffer_free(buffer);ggml_backend_free(backend);ggml_free(ctx);
}
int main(){check(1,1,1);check(5,3,2);check(32,17,3);check(384,384,1);}
''')
    exe=tmp_path/'layout'
    subprocess.run(['g++','-std=c++17','-O2','-I'+str(SRC/'ggml/include'),str(cpp),'-Wl,--start-group',*[str(p) for p in libs],'-Wl,--end-group','-pthread','-ldl','-lm','-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


def test_clean_dependency_replay_prevents_cached_experiment_leaks():
    s=(ROOT/'apk-fix/build_mobile.py').read_text()
    assert s.index("run('git','-C',source,'restore','--source=HEAD','--worktree','.')")<s.index('apply_strict_vulkan(source)')<s.index('patch_image_upload(source)')


def test_android_diagnostic_cannot_hide_layout_behind_embedding_cache():
    s=(ROOT/'scripts/test_image_upload_android.py').read_text()
    assert "'GGUF_DISABLE_IMAGE_EMBED_CACHE':'1'" in s
    assert "'GGUF_VERIFY_IMAGE_PACK':'1'" in s
    assert "before['embedding_digests']==after['embedding_digests']" in s
    assert "before['raw_response']==after['raw_response']" in s
    assert 'benchmark=False' in s and 'both_modes_same_apk=True' in s
