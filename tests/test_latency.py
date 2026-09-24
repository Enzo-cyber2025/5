from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]

def test_actual_cpp_prefix_planner(tmp_path):
    src=tmp_path/'cache.cpp'
    src.write_text('''#include "prompt_cache.h"
#include <cassert>
int main(){
 std::vector<int> c{1,2,3,4}, same{1,2,3,4}, shorter{1,2}, changed{1,7,3}, longer{1,2,3,4,5};
 assert(reusable_prefix(c,same,true,0,3)==3); // replay last token for logits
 assert(reusable_prefix(c,shorter,true,0,3)==1);
 assert(reusable_prefix(c,changed,true,0,3)==1);
 assert(reusable_prefix(c,longer,true,0,3)==4);
 assert(reusable_prefix(c,longer,false,0,3)==0); // recurrent/media
 assert(reusable_prefix(c,longer,true,1,3)==0); // evicted SWA prefix
 assert(reusable_prefix(c,longer,true,0,2)==0); // incomplete KV
 assert(reusable_prefix(c,std::vector<int>{},true,0,3)==0);
 assert(reusable_prefix(c,std::vector<int>{1},true,0,3)==0);
 assert(reusable_prefix(c,std::vector<int>{9,2},true,0,3)==0);
 assert(reusable_prefix(std::vector<int>{},longer,true,-1,-1)==0);
}''')
    exe=tmp_path/'cache'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'apk-fix/native'),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

def test_real_memory_operations_and_invalidation_are_guarded():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert '!llama_model_is_recurrent' in s and '!llama_model_is_hybrid' in s
    assert 'llama_memory_seq_pos_min' in s and 'llama_memory_seq_pos_max' in s
    assert '!llama_memory_seq_rm(memory,0,reused_tokens,-1)' in s
    assert 'if(n_images) {\n            // Image identity' in s
    assert 'e->cached_tokens.clear();llama_memory_clear(memory,true);' in s
    assert 'e->cached_tokens.clear(); // failed/partial work is never reused' in s
    assert s.index('if(llama_decode(e->ctx,llama_batch_get_one(&t,1))!=0)')<s.index('if(text_cache)e->cached_tokens.push_back(t)')
    assert 'GGUF_RESPONSE_LATENCY' in s and 'GGUF_PROMPT_CACHE' in s
    assert 'cp.n_batch=prefill_batch; cp.n_ubatch=prefill_ubatch;' in s
    # O experimento abandonado era um lote fixo gigante com nova tentativa de
    # alocação. O que existe agora é um lote de prefill proporcional ao contexto,
    # com teto declarado, e nenhuma nova tentativa.
    assert 'cp.n_batch=128; cp.n_ubatch=32;' not in s
    assert 'prefill_batch=context>=2048?512:(context>=1024?256:128)' in s
    assert 'prefill_ubatch=context>=1024?128:64' in s
    assert 'GGUF_PREFILL_ALLOCATION_RETRY' not in s

def test_incremental_stream_has_no_full_copy_or_live_truncation(tmp_path):
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from latency_patches import patch_latency_ui
    file=tmp_path/'ChatActivity.smali'
    file.write_text('.method private onToken(Ljava/lang/String;)V\n.locals 1\n return-void\n.end method\n')
    patch_latency_ui(tmp_path);s=file.read_text()
    assert 'TextView;->append(Ljava/lang/CharSequence;)V' in s
    assert 'toString' not in s and 'substring' not in s and 'replace(' not in s

def test_image_cache_is_bounded_content_keyed_and_keeps_upstream_positions():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'mtmd_gguf_image_fingerprint(chunk,key.data())' in s
    assert 'image_set_id' not in s
    cache=(ROOT/'apk-fix/native/image_embedding_cache.h').read_text()
    assert 'it->key==key && it->values.size()==count' in cache
    assert 'capacity_bytes = 16*1024*1024' in cache
    assert 'catch(const std::bad_alloc &)' in cache
    assert 'mtmd_helper_decode_image_chunk(e->projector,e->ctx,chunk,embd,past,0' in s
    assert 'GGUF_IMAGE_EMBED_CACHE hits=' in s


def test_input_bridge_is_separate_and_verifies_actual_edit_text():
    test=(ROOT/'scripts/test_latency_android.py').read_text()
    bridge=(ROOT/'tests/android-input/src/com/ggufchat/testinput/InputBridge.java').read_text()
    manifest=(ROOT/'tests/android-input/AndroidManifest.xml').read_text()
    assert 'return prompt in fields' in test and 'input text ' not in test
    assert 'commitText(text, 1)' in bridge and 'getCurrentInputConnection()' in bridge
    assert 'com.ggufchat.app' in bridge
    assert 'uses-permission' not in manifest
    assert 'testinput' not in (ROOT/'apk-fix/build_mobile.py').read_text()


def test_new_signature_never_silently_claims_in_place_update():
    s=(ROOT/'scripts/test_latency_android.py').read_text()
    assert 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in s
    assert 'signature_change_blocks_update_without_data_loss' in s
    assert 'no data migration claim' in s
    assert s.index("assert d.shell('getprop ro.kernel.qemu')=='1'",s.index('Destructive cleanup')) < s.index("d.adb('uninstall',PACKAGE)")


def test_ime_registration_is_observed_after_real_unlock():
    s=(ROOT/'scripts/test_latency_android.py').read_text()
    assert 'ime list -a -s' in s and 'ime=d.wait(registered_ime' in s
    assert s.index("d.shell('wm dismiss-keyguard')") < s.index('ime=d.wait(registered_ime')
    assert "d.shell('ime enable '+shlex.quote(ime))" in s


def test_system_edit_uses_verified_input_and_save_not_back():
    s=(ROOT/'scripts/test_latency_android.py').read_text()
    editor=s[s.index('def edit_system_prompt'):s.index('def sha(p)')]
    assert 'd.enter_text(text)' in editor and "d.tap(text='Salvar'" in editor
    assert 'keyevent' not in editor and 'input text' not in editor


def test_downloads_waits_for_visible_drawer_and_provider_title():
    sys.path.insert(0,str(ROOT/'scripts'))
    from test_android import Android
    class Fake:
        count=0
        commands=[]
        def ui(self):
            self.count+=1
            root='<node enabled="true" text="Open from" package="com.google.android.documentsui" bounds="[0,0][400,70]"/>'
            download='<node enabled="true" text="Downloads" package="com.google.android.documentsui" resource-id="com.google.android.documentsui:id/title" bounds="[20,100][220,160]"/>'
            return '<hierarchy>'+root+(download if self.count>1 else '')+'</hierarchy>'
        def wait(self,fn,*args,**kwargs):
            assert fn() is None
            result=fn();assert result is not None;return result
        def shell(self,command):self.commands.append(command)
    d=Fake();Android.select_downloads(d)
    assert d.commands==['input tap 120 130'] and d.count==2
