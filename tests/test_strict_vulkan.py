"""Routing/rejection tests, NOT a physical-GPU performance certificate."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apk-fix'))
from strict_vulkan_patches import STATE, DIRECT_GUARD, SCHED_GUARD, PREFER, patch_backend, patch_header, patch_sampler_binding


def test_compiled_dispatch_preflight_thread_isolation_and_views(tmp_path):
    # Compile the EXACT inserted dispatch/preflight code against a tiny backend
    # fixture. Execution counters prove rejection precedes all submission.
    code = r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <thread>
#include <vector>
enum ggml_op { GGML_OP_NONE, GGML_OP_VIEW, GGML_OP_RESHAPE, GGML_OP_PERMUTE, GGML_OP_TRANSPOSE, GGML_OP_MUL_MAT, GGML_OP_ADD, GGML_OP_CPY };
enum ggml_status { GGML_STATUS_SUCCESS, GGML_STATUS_FAILED=-1 };
struct Device {};
using ggml_backend_dev_t=Device*;
struct Backend { Device *device; const char *name; int submitted=0; };
using ggml_backend_t=Backend*;
struct ggml_tensor { ggml_op op; const char *name; };
struct ggml_cgraph { int n_nodes; ggml_tensor **nodes; };
const char *ggml_op_name(ggml_op) { return "TEST_OP"; }
Device *ggml_backend_get_device(Backend *b) { return b->device; }
const char *ggml_backend_name(Backend *b) { return b->name; }
#define GGML_LOG_ERROR(...) ((void)0)
''' + STATE + r'''
ggml_status dispatch(ggml_backend_t backend, ggml_cgraph *cgraph) {
''' + DIRECT_GUARD + r'''
 ++backend->submitted; return GGML_STATUS_SUCCESS;
}
struct Split { int backend_id; ggml_cgraph graph; };
struct Scheduler { int n_splits; Split *splits; Backend **backends; };
ggml_status compute(Scheduler *sched) {
''' + SCHED_GUARD + r'''
 for(int i=0;i<sched->n_splits;i++) {
  auto &s=sched->splits[i];auto result=dispatch(sched->backends[s.backend_id],&s.graph);
  if(result!=GGML_STATUS_SUCCESS)return result;
 }
 return GGML_STATUS_SUCCESS;
}
int main() {
 Device gpuDevice,cpuDevice; Backend gpu{&gpuDevice,"Vulkan0"},cpu{&cpuDevice,"CPU"};
 ggml_tensor mul{GGML_OP_MUL_MAT,"weight"};ggml_tensor *nodes[]={&mul};ggml_cgraph graph{1,nodes};
 assert(ggml_backend_gguf_set_strict_device(&gpuDevice)==nullptr);
 assert(dispatch(&cpu,&graph)==GGML_STATUS_FAILED && cpu.submitted==0);
 assert(strstr(ggml_backend_gguf_strict_error(),"CPU"));
 assert(dispatch(&gpu,&graph)==GGML_STATUS_SUCCESS && gpu.submitted==1);
 assert(ggml_backend_gguf_strict_nodes()==1);
 // Even a later CPU split must block BEFORE the first GPU split runs.
 Backend *backends[]={&gpu,&cpu};Split splits[]={{0,graph},{1,graph}};Scheduler sched{2,splits,backends};
 assert(compute(&sched)==GGML_STATUS_FAILED && gpu.submitted==1 && cpu.submitted==0);
 for(auto op:{GGML_OP_NONE,GGML_OP_VIEW,GGML_OP_RESHAPE,GGML_OP_PERMUTE,GGML_OP_TRANSPOSE}) {
  mul.op=op;assert(dispatch(&cpu,&graph)==GGML_STATUS_SUCCESS);
 }
 for(auto op:{GGML_OP_MUL_MAT,GGML_OP_ADD,GGML_OP_CPY}) {
  mul.op=op;assert(dispatch(&cpu,&graph)==GGML_STATUS_FAILED);
 }
 // Independent calling thread is explicit CPU, not accidentally made strict.
 std::thread other([&]{assert(ggml_backend_gguf_strict_device()==nullptr);
  assert(ggml_backend_gguf_strict_error()[0]==0);assert(dispatch(&cpu,&graph)==GGML_STATUS_SUCCESS);});other.join();
 assert(ggml_backend_gguf_strict_device()==&gpuDevice);
 ggml_backend_gguf_set_strict_device(nullptr);ggml_backend_gguf_strict_reset();
 assert(!*ggml_backend_gguf_strict_error() && ggml_backend_gguf_strict_graphs()==0);
 assert(dispatch(&cpu,&graph)==GGML_STATUS_SUCCESS);
}
'''
    p=tmp_path/'strict.cpp';p.write_text(code)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-pthread',str(p),'-o',str(tmp_path/'strict')],check=True)
    subprocess.run([str(tmp_path/'strict')],check=True)


def test_idempotent_pinned_source_and_order():
    source=ROOT/'.cache/llama-mobile'
    if not source.exists():
        import pytest
        pytest.skip('Pinned source supplied in native build')
    for rel,patch in [('ggml/include/ggml-backend.h',patch_header),('ggml/src/ggml-backend.cpp',patch_backend),('src/llama-context.cpp',patch_sampler_binding)]:
        s=patch((source/rel).read_text());assert patch(s)==s
    s=patch_backend((source/'ggml/src/ggml-backend.cpp').read_text())
    assert s.index('GGUF_STRICT_VULKAN_PREFLIGHT') < s.index('return ggml_backend_sched_compute_splits(sched);')
    assert s.index('GGUF_STRICT_VULKAN_PREFER') < s.index('    // graph input\n')
    assert 'ggml_backend_get_device(sched->backends[b]) == gguf_strict_device' in PREFER


def test_native_all_weights_full_sampling_and_preserved_parameters():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'if(layers!=0) layers=INT_MAX;' in s
    assert 'gpu_weights[2]={{".*",nullptr},{nullptr,nullptr}}' in s
    assert 'mp.tensor_buft_overrides=e->gpu_weights;' in s
    assert s.index('StrictVulkanScope strict(e->strict_device);') < s.index('e->model=llama_model_load_from_file')
    assert s.count('StrictVulkanScope strict(e->strict_device);')==2
    assert 'if(!binding.attached)throw std::runtime_error' in s
    assert s.index('else if(e->strict_device)') < s.index('else t=llama_sampler_sample')
    assert 'llama_sampler_init_dist(seed)' in s and 'llama_sampler_init_penalties' in s
    assert 'cp.n_batch=128; cp.n_ubatch=32;' in s
    assert '!llama_model_has_encoder(e->model) && !llama_model_is_diffusion(e->model))cp.n_outputs_max=1;' in s
    assert 'output_mask.back()=1' in s and 'batch.logits=output_mask.data()' in s
    assert 'GGUF_STRICT_VULKAN_RESULT' in s
    scope=(ROOT/'apk-fix/native/strict_vulkan.h').read_text()
    assert '~StrictVulkanScope() { ggml_backend_gguf_set_strict_device(previous); }' in scope


def test_android_audit_requires_completed_math_and_no_block():
    sys.path.insert(0, str(ROOT/'scripts'))
    from vulkan_strict_checks import strict_audit
    import pytest
    log='GGUF_STRICT_VULKAN_RESULT enabled=1 submitted_graphs=129 submitted_math_nodes=1000 blocked=0 host_orchestration=CPU\nGGUF_GPU_SAMPLING_RESULT backend_selected=129 emitted=128\nGGUF_NATIVE_COMPLETE'
    assert strict_audit(log)['submitted_math_nodes']==1000
    for bad in [log.replace('enabled=1','enabled=0'),log.replace('math_nodes=1000','math_nodes=0'),log.replace('blocked=0','blocked=1'),log.replace('selected=129','selected=0'),log.replace('GGUF_NATIVE_COMPLETE',''),log+'\nGGUF_STRICT_VULKAN_BLOCKED',log+'\n'+log]:
        with pytest.raises(AssertionError):strict_audit(bad)
