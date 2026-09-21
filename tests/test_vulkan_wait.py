from pathlib import Path
import os,subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from vulkan_wait_patches import patch,ADDITION,ANCHOR
UPSTREAM=ROOT/'.cache/llama-mobile/ggml/src/ggml-vulkan/ggml-vulkan.cpp'

def source():
    if not UPSTREAM.exists():pytest.skip('Pinned Vulkan source required')
    return UPSTREAM.read_text().replace(ADDITION,'',1)

def test_only_wait_branch_changes_and_production_recipe_is_opt_in():
    s=source();out=patch(s)
    assert out.replace(ADDITION,'',1)==s
    assert patch(out)==out
    assert 'value == nullptr || strcmp(value, "1") == 0' in ADDITION
    recipe=(ROOT/'apk-fix/build_mobile.py').read_text()
    assert 'os.environ.get("GGUF_EXPERIMENT_BLOCKING_WAIT")=="1"' in recipe
    assert 'patch_vulkan_wait(s) if experimental_wait else s' in recipe
    assert 'waitForFences({ ctx->fence }, true, UINT64_MAX)' in ADDITION
    assert ADDITION.index('waitForFences')<ADDITION.index('resetFences')<ADDITION.index('return;')
    assert all(x not in ADDITION for x in ('sleep(', 'submit(', 'llama_', 'setPriority'))
    with pytest.raises(AssertionError):patch(s.replace(ANCHOR,'implementation changed'))

def test_actual_patched_function_waits_and_resets_the_same_fence(tmp_path):
    s=patch(source());a=s.index('static void ggml_vk_wait_for_fence(');b=s.index('\nstatic constexpr',a)
    function=s[a:b]
    prefix=r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>
#include <initializer_list>
namespace vk {
 enum class Result {eSuccess,eNotReady,eError};
 struct DeviceLostError:std::runtime_error {DeviceLostError():std::runtime_error("lost") {}};
 struct SystemError:std::runtime_error {SystemError(int,const char*s):std::runtime_error(s){}};
 int make_error_code(Result){return 1;}
 std::string to_string(Result){return "error";}
}
struct Driver {
 std::vector<int> calls;int polls=0;bool fail=false;
 vk::Result waitForFences(std::initializer_list<int> fs,bool all,uint64_t timeout){
   assert(all&&timeout==UINT64_MAX&&fs.size()==1);int f=*fs.begin();calls.push_back(10+f);
   if(f==1&&fail)return vk::Result::eError;
   return vk::Result::eSuccess;
 }
 void resetFences(std::initializer_list<int> fs){assert(fs.size()==1);calls.push_back(20+*fs.begin());}
 vk::Result getFenceStatus(int f){assert(f==1);calls.push_back(30+f);polls++;return polls<3?vk::Result::eNotReady:vk::Result::eSuccess;}
};
struct Device {Driver device;};
struct ggml_backend_vk_context {Device*device;int fence=1,almost_ready_fence=2;bool almost_ready_fence_pending=false;};
void ggml_vk_print_device_lost_info(Device*){}
#define GGML_LOG_INFO(...) ((void)0)
#define GGML_LOG_ERROR(...) ((void)0)
#define YIELD() ((void)0)
#define VK_CHECK(expr,label,dev) do{if((expr)!=vk::Result::eSuccess)throw std::runtime_error(label);}while(0)
'''
    suffix=r'''
int main(){
 bool blocking=!getenv("GGUF_VULKAN_BLOCKING_WAIT")||strcmp(getenv("GGUF_VULKAN_BLOCKING_WAIT"),"1")==0;
 Device d;ggml_backend_vk_context c{&d};
 c.almost_ready_fence_pending=true;ggml_vk_wait_for_fence(&c);
 assert(!c.almost_ready_fence_pending);
 if(blocking){assert(d.device.calls==std::vector<int>({12,22,11,21}));assert(d.device.polls==0);}
 else{assert(d.device.calls==std::vector<int>({12,22,31,31,31,21}));}
 d.device.calls.clear();d.device.polls=0;ggml_vk_wait_for_fence(&c);
 if(blocking)assert(d.device.calls==std::vector<int>({11,21}));
 else assert(d.device.calls==std::vector<int>({31,31,31,21}));
 if(blocking){d.device.calls.clear();d.device.fail=true;try{ggml_vk_wait_for_fence(&c);assert(false);}catch(const std::runtime_error&){}assert(d.device.calls==std::vector<int>({11}));}
}
'''
    p=tmp_path/'wait.cpp';p.write_text(prefix+function+suffix);exe=tmp_path/'wait'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra',str(p),'-o',str(exe)],check=True)
    for mode in ('0','1','true','',None):
        env=dict(os.environ);env.pop('GGUF_VULKAN_BLOCKING_WAIT',None)
        if mode is not None:env['GGUF_VULKAN_BLOCKING_WAIT']=mode
        subprocess.run([str(exe)],env=env,check=True)
