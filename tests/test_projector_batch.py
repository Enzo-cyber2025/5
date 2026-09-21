"""Synthetic lifetime tests plus actual ggml pixel-merge graphs; NOT speed evidence."""
from pathlib import Path
import sys,subprocess,re
import pytest
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'.cache/llama-mobile'
sys.path.insert(0,str(ROOT/'apk-fix'))
from projector_batch_patches import MERGE,patch_projector_batch

def test_pair_owns_only_two_outputs_and_never_retries_failed_compute(tmp_path):
    (tmp_path/'mtmd.h').write_text('''#pragma once
#include <cstddef>
struct mtmd_context {};struct mtmd_input_chunk {int id;};
struct mtmd_batch {int count=0;};
size_t mtmd_input_chunk_get_n_tokens(const mtmd_input_chunk *);
mtmd_batch *mtmd_batch_init(mtmd_context *);
void mtmd_batch_free(mtmd_batch *);
int mtmd_batch_add_chunk(mtmd_batch *,const mtmd_input_chunk *);
int mtmd_batch_encode(mtmd_batch *);
float *mtmd_batch_get_output_embd(mtmd_batch *,const mtmd_input_chunk *);
''')
    cpp=tmp_path/'pair.cpp';cpp.write_text(r'''
#include "projector_pair.h"
#include <cassert>
int allocated=0,encoded=0,decline=0;bool fail=false;
size_t mtmd_input_chunk_get_n_tokens(const mtmd_input_chunk *){return 1;}
mtmd_batch *mtmd_batch_init(mtmd_context *){allocated++;return new mtmd_batch;}
void mtmd_batch_free(mtmd_batch *p){if(p){allocated--;delete p;}}
int mtmd_batch_add_chunk(mtmd_batch *p,const mtmd_input_chunk *){if(p->count && decline)return decline;p->count++;return 0;}
int mtmd_batch_encode(mtmd_batch *){encoded++;return fail?1:0;}
float *mtmd_batch_get_output_embd(mtmd_batch *,const mtmd_input_chunk *p){static float out[2]={10,20};return out+p->id;}
int main(){
 mtmd_context ctx;mtmd_input_chunk a{0},b{1};
 {ProjectorPair pair;assert(!pair.start(&ctx,&a,nullptr));assert(allocated==0);
  decline=2;assert(!pair.start(&ctx,&a,&b));assert(allocated==0&&encoded==0);
  decline=3;assert(!pair.start(&ctx,&a,&b));assert(allocated==0&&encoded==0);
  decline=0;assert(pair.start(&ctx,&a,&b));assert(allocated==1&&encoded==1);
  assert(*pair.output(&a)==10);pair.consumed(&a);assert(pair.ready(&b)&&allocated==1);
  assert(*pair.output(&b)==20);pair.consumed(&b);assert(allocated==0&&!pair.ready(&b));
 }
 {ProjectorPair pair;fail=true;try{pair.start(&ctx,&a,&b);assert(false);}catch(const std::runtime_error &){}assert(encoded==2);}
 assert(allocated==0);
}''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(tmp_path),'-I'+str(ROOT/'apk-fix/native'),str(cpp),'-o',str(tmp_path/'pair')],check=True)
    subprocess.run([str(tmp_path/'pair')],check=True)

def test_actual_pixel_merge_keeps_batch_axis_and_padding(tmp_path):
    libs=ROOT/'.cache/strict-host/ggml/src'
    if not (libs/'libggml.a').exists():pytest.skip('Compile pinned real ggml first')
    original=subprocess.check_output(['git','-C',str(SRC),'show','HEAD:tools/mtmd/clip.cpp'],text=True)
    a=original.index('ggml_tensor * clip_graph::build_patch_merge_permute(')
    b=original.index('\nstatic ',a)
    body=original[a:b]
    anchor='    const int64_t pad_height = CLIP_ALIGN(height, scale_factor) - height;'
    changed=body.replace(anchor,anchor+'\n'+MERGE)
    def function(text,name):
        signature='ggml_tensor * clip_graph::build_patch_merge_permute(ggml_tensor * cur, int scale_factor) {'
        return text.replace(signature,f'ggml_tensor * {name}(ggml_context *ctx0, ggml_tensor *cur,int scale_factor,int n_batch,int w,int h) {{\n const int proj_type=1, patch_size=1;\n struct Image {{int w,h;int nx(){{return w;}} int ny(){{return h;}}}} img{{w,h}};')
    text='''#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "ggml-alloc.h"
#include <vector>
#include <cassert>
#include <cstring>
#define CLIP_ALIGN(x,n) (((x)+(n)-1)/(n)*(n))
#define PROJECTOR_TYPE_IDEFICS3 1
void cb(ggml_tensor *,const char *,int){}
'''+function(body,'old_merge')+function(changed,'new_merge')+r'''
std::vector<float> run(bool newer,int w,int h,int B,int scale,const std::vector<float>&data){
 auto *ctx=ggml_init({2*1024*1024,nullptr,true});assert(ctx);
 auto *in=ggml_new_tensor_3d(ctx,GGML_TYPE_F32,3,w*h,B);
 auto *out=newer?new_merge(ctx,in,scale,B,w,h):old_merge(ctx,in,scale,B,w,h);
 auto *g=ggml_new_graph(ctx);ggml_build_forward_expand(g,out);
 auto backend=ggml_backend_cpu_init();auto buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);
 ggml_backend_tensor_set(in,data.data(),0,data.size()*sizeof(float));
 assert(ggml_backend_graph_compute(backend,g)==GGML_STATUS_SUCCESS);
 std::vector<float> result(ggml_nelements(out));ggml_backend_tensor_get(out,result.data(),0,result.size()*sizeof(float));
 ggml_backend_buffer_free(buffer);ggml_backend_free(backend);ggml_free(ctx);return result;
}
void check(int w,int h,int B,int scale){
 std::vector<float> input(3*w*h*B),expected;
 for(size_t i=0;i<input.size();i++)input[i]=(int(i%3001)-1500)/32.0f;
 input[0]=-0.0f;
 for(int b=0;b<B;b++){
  auto first=input.begin()+b*3*w*h;
  auto ref=run(false,w,h,1,scale,std::vector<float>(first,first+3*w*h));expected.insert(expected.end(),ref.begin(),ref.end());
 }
 auto actual=run(true,w,h,B,scale,input);assert(actual.size()==expected.size());
 assert(!memcmp(actual.data(),expected.data(),actual.size()*sizeof(float)));
}
int main(){check(8,8,2,2);check(5,7,3,2);check(8,12,2,4);check(32,32,2,4);check(32,32,1,4);}
'''
    cpp=tmp_path/'merge.cpp';cpp.write_text(text)
    subprocess.run(['g++','-std=c++17','-O2','-I'+str(SRC/'ggml/include'),str(cpp),'-Wl,--start-group',*[str(libs/n) for n in ('libggml.a','libggml-cpu.a','libggml-base.a')],'-Wl,--end-group','-pthread','-ldl','-lm','-o',str(tmp_path/'merge')],check=True)
    subprocess.run([str(tmp_path/'merge')],check=True)

def test_patches_and_native_bounds(tmp_path):
    if not SRC.exists():pytest.skip('Pinned source required')
    for rel in ('tools/mtmd/clip.cpp','tools/mtmd/models/models.h'):
        target=tmp_path/rel;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','-C',str(SRC),'show','HEAD:'+rel]))
    patch_projector_batch(tmp_path);before=(tmp_path/'tools/mtmd/clip.cpp').read_bytes()
    patch_projector_batch(tmp_path);assert before==(tmp_path/'tools/mtmd/clip.cpp').read_bytes()
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'key_valid && key==next_key' in s # duplicate input: don't encode it twice instead of caching
    assert 'GGUF_PROJECTOR_BATCH2' in s and 'if(paired && !e->strict_device)' in s
    assert s.index('pair.consumed(chunk)')>s.index('result=mtmd_helper_decode_image_chunk')
    assert 'std::memcmp(embd,mtmd_get_output_embd' in s
    assert 'cp.n_batch=128; cp.n_ubatch=32;' in s


def test_timing_gate_excludes_instrumentation_and_requires_both_pairs(tmp_path):
    import json,copy,importlib.util
    spec=importlib.util.spec_from_file_location('pair_eval',ROOT/'ci/evaluate_projector_pairs.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    base={'diagnostic':False,'raw_history':[['user','prompt'],['assistant',' exact ']],'upload_bytes':100,'tokens':2,
          'metrics':{'promptTokens':100,'completed':True,'decodeNs':1000000000},'native_decode_tokens_s':2,
          'strict':{'status':'PASS'},'stages':{'verification':0,'cache_disabled':1,'hits':0,'encode_calls':5},
          'pairs':{'verification':0,'verified_images':0,'pair_calls':0},'send_to_first_ui_ns':1000000000}
    paired=copy.deepcopy(base);paired['send_to_first_ui_ns']=800000000;paired['stages']['encode_calls']=3;paired['pairs']['pair_calls']=2
    s={'status':'PASS_PAIRED_EXPERIMENT_ONLY','warmups':[{}]*4,
       'measurements':[{'serial':base,'paired':paired},{'paired':copy.deepcopy(paired),'serial':copy.deepcopy(base)}],
       'verification':{'diagnostic':True,'pairs':{'verification':1,'verified_images':4,'paired_images':4}}}
    p=tmp_path/'result.json';p.write_text(json.dumps(s));assert mod.evaluate(p)['status']=='OBSERVED_GAIN_IN_BOTH_PAIRS'
    s['measurements'][1]['paired']['send_to_first_ui_ns']=1100000000;p.write_text(json.dumps(s))
    assert mod.evaluate(p)['status']=='NO_CONSISTENT_GAIN_OVER_5_PERCENT'
    s['measurements'][0]['paired']['diagnostic']=True;p.write_text(json.dumps(s))
    with pytest.raises(AssertionError):mod.evaluate(p)
    s['status']='FAIL';p.write_text(json.dumps(s))
    with pytest.raises(ValueError):mod.evaluate(p)
