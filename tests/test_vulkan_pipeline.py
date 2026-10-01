from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apk-fix'))
from vulkan_patches import patch_token_readback


def test_terminal_token_exports_and_partial_fallback(tmp_path):
    # Compile the exact inserted C++ body; exported descriptors only are changed.
    anchor = '            sampler->iface->backend_apply(sampler, ctx0, gf, &data);'
    patched = patch_token_readback(anchor)
    assert patch_token_readback(patched) == patched
    body = patched.split('#ifdef GGUF_TOKEN_ONLY_SAMPLING\n')[1].split('#endif')[0]
    p = tmp_path / 'exports.cpp'
    p.write_text('''#include <cassert>
struct Data { void *sampled, *logits, *probs, *candidates; };
void prune(Data &data) {''' + body + '''}
int main() {
 int token, logits, probs, candidates;
 Data partial{nullptr,&logits,&probs,&candidates};prune(partial);
 assert(partial.logits==&logits && partial.probs==&probs && partial.candidates==&candidates);
 Data selected{&token,&logits,&probs,&candidates};prune(selected);
 assert(selected.sampled==&token && !selected.logits && !selected.probs && !selected.candidates);
}''')
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(p), '-o', str(tmp_path / 'exports')], check=True)
    subprocess.run([str(tmp_path / 'exports')], check=True)


def test_order_first_delivery_last_token_and_failure(tmp_path):
    p = tmp_path / 'order.cpp'
    p.write_text('''#include "decode_delivery.h"
#include <cassert>
#include <string>
#include <stdexcept>
int main() {
 for (bool gpu: {false,true}) for (bool first: {false,true}) for (bool next: {false,true}) {
  std::string calls;
  decode_and_deliver(gpu,first,next,[&]{calls+='D';},[&]{calls+='T';});
  assert(calls==(!next ? "T" : gpu&&!first ? "DT" : "TD"));
 }
 std::string calls;
 try {decode_and_deliver(true,false,true,[&]{calls+='D';throw std::runtime_error("cancelled");},[&]{calls+='T';});assert(false);}
 catch(const std::runtime_error&) {assert(calls=="D");}
 calls.clear();
 try {decode_and_deliver(true,true,true,[&]{calls+='D';},[&]{calls+='T';throw std::runtime_error("callback");});assert(false);}
 catch(const std::runtime_error&) {assert(calls=="T");}
}''')
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Iapk-fix/native', str(p), '-o', str(tmp_path / 'order')], check=True)
    subprocess.run([str(tmp_path / 'order')], check=True)


def test_patch_applies_to_pinned_graph_if_available():
    p = ROOT / '.cache/llama-mobile/src/llama-graph.cpp'
    if not p.exists():
        import pytest
        pytest.skip('Pinned upstream checkout required; hosted build supplies it')
    s = patch_token_readback(p.read_text())
    assert s.count('if (data.sampled != nullptr) {') >= 2
    assert s.index('data.logits = nullptr;') < s.index('res->t_sampled[rows[i]] = data.sampled;')
    assert 'GGUF_TOKEN_ONLY_SAMPLING=1' in (ROOT / 'apk-fix/native/CMakeLists.txt').read_text()


def test_native_fallback_sampler_and_measurement_contract_preserved():
    s = (ROOT / 'apk-fix/native/mobile.cpp').read_text()
    assert 'llama_sampler_accept(sampler.get(),t);backend_sampled++;' in s
    assert 'else t=llama_sampler_sample(sampler.get(),e->ctx,-1)' in s
    assert 'llama_sampler_init_dist(seed)' in s
    assert 'cp.n_batch=prefill_batch; cp.n_ubatch=prefill_ubatch;' in s
    assert s.index('emitted++;pending+=piece(vocab,t);') < s.index('decode_and_deliver(e->layers>0,emitted==1,has_next')
    # O dreno do prefill continua antes da contagem de decodificação; a checagem
    # de logits da última posição (CPU) entra entre os dois e por isso a ordem é
    # conferida por posição, não por texto colado.
    assert s.index('llama_synchronize(e->ctx);') < s.index('decode_started=Clock::now();decoding=true;')
