import copy,json,sys,subprocess,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'ci'),str(ROOT/'scripts')]
from evaluate_expanded_weights import evaluate,ENV,ON,VERIFY
from test_gpu_rate import fixture as rate_fixture


def fixture():
    s=rate_fixture();s['status']='COMPLETE_EXPANDED_OBSERVATIONS'
    s['build']['experiment']=dict(apk_sha256='c'*64,source_commit='d'*40,experimental_expanded_weights_build=True,default_enabled=False,release_approved=False)
    s['build']['payloads']['candidate']=copy.deepcopy(s['build']['payloads']['after'])
    s['build']['payloads']['candidate']['original_sha256']='c'*64
    for i,p in enumerate(s['pairs']):
        p['order']=['before','after','candidate'] if i%2==0 else ['candidate','after','before']
        p['candidate']=copy.deepcopy(p['after']);p['candidate']['vulkan_environment']=ON.copy()
        p['candidate']['expansion']=dict(tensors=180,extra_device_bytes=550000000,verified_bytes=0,verification=0,prepare_ns=100000,precision='F32',conversion='Vulkan')
    s['proof']=copy.deepcopy(s['pairs'][0]['candidate']);s['proof']['vulkan_environment']=VERIFY.copy()
    s['proof']['expansion'].update(verification=1,verified_bytes=540000000)
    return s


def test_two_times_means_double_historical_in_every_pair_not_ten_percent():
    r=evaluate(fixture());assert r['target_2x_passed'] and not r['release_approved']
    assert r['comparisons']['historical']['median_paired_gain_percent']==100
    assert r['comparisons']['delivered']['median_paired_gain_percent']==0


def test_target_not_reached_is_reported_honestly():
    s=fixture();r=s['pairs'][1]['candidate']['sample']
    r['callback_times_ns']=[x*2 for x in r['callback_times_ns']];r['interval_ns']*=2
    r=evaluate(s);assert not r['target_2x_passed'] and r['status']=='TWO_TIMES_TARGET_NOT_MET'


@pytest.mark.parametrize('mutate',[
    lambda s:s['proof']['expansion'].update(verified_bytes=0),
    lambda s:s['proof']['expansion'].update(conversion='CPU'),
    lambda s:s['proof'].update(vulkan_environment=ON.copy()),
    lambda s:s['pairs'][0]['candidate']['expansion'].update(verification=1),
    lambda s:s['pairs'][0]['candidate']['expansion'].update(precision='F16'),
    lambda s:s['pairs'][0]['candidate'].update(vulkan_environment=VERIFY.copy()),
    lambda s:s['build']['experiment'].update(default_enabled=True),
    lambda s:s['pairs'][0]['candidate']['sample'].update(response='different'),
    lambda s:s['pairs'][0]['after']['sample'].update(strict={'status':'FAIL'}),
    lambda s:s['pairs'][0].update(order=['before','candidate','after']),
    lambda s:s['build']['payloads']['candidate'].update(original_sha256='e'*64),
])
def test_bad_proof_quality_provenance_or_timing_is_not_a_speedup(mutate):
    s=fixture();mutate(s)
    with pytest.raises(AssertionError):evaluate(s)


def test_compile_and_runtime_flags_default_off_and_transactional_gpu_conversion():
    header=(ROOT/'apk-fix/native/expanded_weights.h').read_text()
    cmake=(ROOT/'apk-fix/native/CMakeLists.txt').read_text();recipe=(ROOT/'apk-fix/build_mobile.py').read_text()
    assert 'GGUF_EXPERIMENT_EXPANDED_WEIGHTS "Build opt-in full-precision Vulkan weight expansion experiment" OFF' in cmake
    assert "os.environ.get('GGUF_EXPERIMENT_EXPANDED_WEIGHTS')=='1'" in recipe
    assert 'std::strcmp(s,"1")==0' in header
    assert 'ggml_get_rows(owner->context,src,ids)' in header and 'ggml_backend_graph_compute' in header
    assert 'ggml_backend_buft_get_device' in header and 'GGML_BACKEND_BUFFER_USAGE_WEIGHTS' in header
    assert header.index('std::memcmp(reference.data()')<header.index('p->original->type=GGML_TYPE_F32')
    assert 'if(verify)' in header and 'experimental_limit' in header
    assert 'throw std::runtime_error' in header and 'CPU inference/dequant fallback' in header


def test_header_compiles_against_actual_pinned_upstream_types(tmp_path):
    roots=[ROOT/'.cache/llama-mobile',ROOT/'.cache/llama-prefix-audit']
    src=next((p for p in roots if (p/'src/llama-model.h').exists()),None)
    if src is None or not shutil.which('g++'):pytest.skip('Pinned upstream/compiler not installed')
    code=tmp_path/'check.cpp';code.write_text('#include "expanded_weights.h"\nint main(){}\n')
    includes=[ROOT/'apk-fix/native',src/'src',src/'include',src/'ggml/include',src/'ggml/src']
    subprocess.run(['g++','-std=c++17','-fsyntax-only',str(code),*[f'-I{p}' for p in includes]],check=True,capture_output=True)
