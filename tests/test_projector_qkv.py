"""QKV byte-layout and exact small-matrix tests on real ggml CPU, not GPU speed."""
import subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'.cache/llama-mobile'
sys.path.insert(0,str(ROOT/'apk-fix'))
from projector_qkv_patches import JOIN,INIT,patch_projector_qkv

def test_real_ggml_join_bytes_and_f32_projection(tmp_path):
    libs=ROOT/'.cache/strict-host/ggml/src'
    if not (libs/'libggml.a').exists():pytest.skip('Build pinned real ggml first')
    cpp=tmp_path/'qkv.cpp';cpp.write_text('''#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "ggml-alloc.h"
#include <array>
#include <vector>
#include <stdexcept>
#include <cstdint>
#include <cstring>
#include <cassert>
'''+JOIN+r'''
void bytes(ggml_type type,bool bias) {
 auto *ctx=ggml_init({2*1024*1024,nullptr,true});assert(ctx);
 auto make=[&](){return bias?ggml_new_tensor_1d(ctx,type,32):ggml_new_tensor_2d(ctx,type,32,4);};
 auto *q=make(),*k=make(),*v=make();auto join=gguf_qkv_build(ctx,q,k,v,bias);
 auto backend=ggml_backend_cpu_init();auto buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);assert(buffer);
 std::vector<unsigned char> expected;
 for(size_t i=0;i<3;i++){
  std::vector<unsigned char> data(ggml_nbytes(join.sources[i]));
  for(size_t j=0;j<data.size();j++)data[j]=(unsigned char)(j*7+i*47);
  ggml_backend_tensor_set(join.sources[i],data.data(),0,data.size());
  ggml_backend_tensor_copy(join.sources[i],join.views[i]);expected.insert(expected.end(),data.begin(),data.end());
 }
 std::vector<unsigned char> actual(ggml_nbytes(join.combined));ggml_backend_tensor_get(join.combined,actual.data(),0,actual.size());
 assert(expected==actual);
 assert(!gguf_qkv_same(q,nullptr,v,bias));
 auto *bad=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,32,5);assert(!gguf_qkv_same(q,k,bad,false));
 if(!bias){auto *transposed=ggml_transpose(ctx,q);assert(!gguf_qkv_same(transposed,k,v,false));}
 ggml_backend_buffer_free(buffer);ggml_backend_free(backend);ggml_free(ctx);
}
void math(){
 auto *ctx=ggml_init({2*1024*1024,nullptr,true});assert(ctx);
 auto *q=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,32,4),*k=ggml_dup_tensor(ctx,q),*v=ggml_dup_tensor(ctx,q);
 auto *x=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,32,3);auto join=gguf_qkv_build(ctx,q,k,v,false);
 auto *g=ggml_new_graph(ctx);auto *all=ggml_mul_mat(ctx,join.combined,x);
 std::array<ggml_tensor *,3> ref{},part{};
 for(int i=0;i<3;i++){
  ref[i]=ggml_mul_mat(ctx,join.sources[i],x);
  part[i]=ggml_cont(ctx,ggml_view_2d(ctx,all,4,3,all->nb[1],i*4*sizeof(float)));
  ggml_build_forward_expand(g,ref[i]);ggml_build_forward_expand(g,part[i]);
 }
 auto backend=ggml_backend_cpu_init();auto buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);assert(buffer);
 for(int i=0;i<3;i++){
  std::vector<float> w(128);for(int j=0;j<128;j++)w[j]=float((j+i)%7-3)/8;
  ggml_backend_tensor_set(join.sources[i],w.data(),0,w.size()*4);ggml_backend_tensor_copy(join.sources[i],join.views[i]);
 }
 std::vector<float> in(96);for(int j=0;j<96;j++)in[j]=float(j%5-2)/4;
 ggml_backend_tensor_set(x,in.data(),0,in.size()*4);
 assert(ggml_backend_graph_compute(backend,g)==GGML_STATUS_SUCCESS);
 for(int i=0;i<3;i++){
  float a[12],b[12];ggml_backend_tensor_get(ref[i],a,0,sizeof(a));ggml_backend_tensor_get(part[i],b,0,sizeof(b));assert(!memcmp(a,b,sizeof(a)));
 }
 ggml_backend_buffer_free(buffer);ggml_backend_free(backend);ggml_free(ctx);
}
int main(){bytes(GGML_TYPE_F32,false);bytes(GGML_TYPE_F16,false);bytes(GGML_TYPE_Q8_0,false);bytes(GGML_TYPE_F32,true);math();}
''')
    exe=tmp_path/'qkv'
    subprocess.run(['g++','-std=c++17','-O2','-I'+str(SRC/'ggml/include'),str(cpp),'-Wl,--start-group',*[str(libs/n) for n in ('libggml.a','libggml-cpu.a','libggml-base.a')],'-Wl,--end-group','-pthread','-ldl','-lm','-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

def test_patch_is_idempotent_and_device_copy_cannot_fall_back_to_host(tmp_path):
    if not SRC.exists():pytest.skip('Pinned source required')
    for rel in ('tools/mtmd/clip.cpp','tools/mtmd/clip.h','tools/mtmd/mtmd.cpp','tools/mtmd/mtmd.h'):
        p=tmp_path/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(subprocess.check_output(['git','-C',str(SRC),'show','HEAD:'+rel]))
    patch_projector_qkv(tmp_path)
    files=list(tmp_path.rglob('*.*'));first={str(p):p.read_bytes() for p in files}
    patch_projector_qkv(tmp_path);assert first=={str(p):p.read_bytes() for p in files}
    assert 'ggml_backend_buffer_copy_tensor(src,dst)' in INIT
    assert 'ggml_backend_tensor_copy(' not in INIT # this generic API can silently stage through host
    assert 'layer.q_norm || layer.k_norm' in INIT and 'n_head!=model.hparams.n_head_kv' in INIT
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert '~RestoreQkv(){mtmd_gguf_qkv_reference(ctx,false);}' in s
    assert 'GGUF_QKV_DIFF' in s and 'std::memcmp(fused.data(),embd,count*sizeof(float))' in s
    assert 'cp.n_batch=128; cp.n_ubatch=32;' in s
