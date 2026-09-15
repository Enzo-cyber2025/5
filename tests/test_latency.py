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
    assert 'cp.n_batch=512; cp.n_ubatch=128;' in s and 'GGUF_PREFILL_ALLOCATION_RETRY' in s

def test_incremental_stream_has_no_full_copy_or_live_truncation(tmp_path):
    sys.path.insert(0,str(ROOT/'apk-fix'))
    from latency_patches import patch_latency_ui
    file=tmp_path/'ChatActivity.smali'
    file.write_text('.method private onToken(Ljava/lang/String;)V\n.locals 1\n return-void\n.end method\n')
    patch_latency_ui(tmp_path);s=file.read_text()
    assert 'TextView;->append(Ljava/lang/CharSequence;)V' in s
    assert 'toString' not in s and 'substring' not in s and 'replace(' not in s
