import copy
import os
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ci'), str(ROOT/'scripts'), str(ROOT/'apk-fix')]
from row_tile_patches import patch, apply, BLOCK, DISPATCH_BLOCK
from evaluate_row_tile import (evaluate, parse_native, tile, dispatch, environment, ENV,
                               PREDECLARED_FACTORS, ACCEPTED_FACTORS, COMPLETE)
from test_row_tile_android import candidate_metadata
from test_expanded_weights import fixture as expansion_fixture

LOG_CONFIG = ('GGUF_VK_ROW_TILE factor={f} stdq={f} kq={kq} stdq_int={f} kq_int={f} '
              'q5_rows={q5} q8_rows={f} kq_rows={kq} fp16=0 int_dot=0 subgroup=8')
LOG_DISPATCH = ('GGUF_VK_ROW_TILE_DISPATCH type={t} rows={rows} activation=f32 quantize_y=0 columns=1')


def native_log(factor):
    lines = ['llvmpipe fp16: 0 int dot: 0', LOG_CONFIG.format(f=factor, kq=2*factor, q5=2*factor)]
    lines += [LOG_DISPATCH.format(t=t, rows=entry['rows']) for t, entry in dispatch(factor).items()]
    lines += ['GGUF_ROW_TILE_CALLBACKS per_token=1 emitted=128 callbacks=128'] * 2
    return '\n'.join(lines) + '\n'


def fixture(factor=4):
    s = expansion_fixture(); s['status'] = COMPLETE; s['factor'] = factor
    e = s['build']['experiment']; e.pop('experimental_expanded_weights_build')
    e.update(experimental_row_tile_build=True, target_multiplier=3, predeclared_factors=list(PREDECLARED_FACTORS),
             per_token_callbacks=True)
    s.pop('proof')
    for pair in s['pairs']:
        r = pair['candidate']; r.pop('expansion'); r.update(tile=tile(factor), tile_dispatch=dispatch(factor),
                                                            vulkan_environment=environment(factor))
        for stage in ('warmup', 'sample'):
            row = pair['before'][stage]
            row['callback_times_ns'] = [1000000000+i*300000000 for i in range(128)]
            row['interval_ns'] = row['callback_times_ns'][-1] - row['callback_times_ns'][0]
    s['correctness'] = {mode: copy.deepcopy(s['pairs'][0]['candidate']) for mode in ('off', 'on')}
    s['correctness']['off'].update(tile=tile(1), tile_dispatch=dispatch(1), vulkan_environment=ENV.copy())
    for mode in ('off', 'on'):
        s['correctness'][mode]['native_per_token_callbacks'] = True
    for pair in s['pairs']:
        pair['candidate']['native_per_token_callbacks'] = True
    return s


def test_200_percent_means_three_times_in_every_historical_pair():
    r = evaluate(fixture())
    assert r['target_multiplier'] == 3 and r['target_gain_percent'] == 200 and r['tested_factor'] == 4
    assert r['target_3x_passed'] and not r['release_approved'] and not r['physical_gpu_certified']
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 200
    assert r['comparisons']['delivered']['median_paired_gain_percent'] == 0
    s = fixture()
    for p in s['pairs']:
        r = p['before']['sample']; r['callback_times_ns'] = [1000000000+i*200000000 for i in range(128)]; r['interval_ns'] = 127*200000000
    r = evaluate(s)
    assert not r['target_3x_passed'] and r['status'] == 'THREE_TIMES_TARGET_NOT_MET'
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 100


def test_both_predeclared_factors_are_measurable_and_declared():
    for factor in PREDECLARED_FACTORS:
        r = evaluate(fixture(factor))
        assert r['tested_factor'] == factor and r['target_3x_passed']
        assert [p['after_tps']/p['before_tps'] for p in r['comparisons']['historical']['pairs']] == [3.0]*3
    with pytest.raises(AssertionError):
        evaluate(fixture(2))


def test_one_slow_pair_fails_even_when_median_meets_target():
    s = fixture(); r = s['pairs'][1]['candidate']['sample']
    r['callback_times_ns'] = [1000000000+i*101000000 for i in range(128)]; r['interval_ns'] = 127*101000000
    r = evaluate(s)
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 200
    assert not r['target_3x_passed']


def test_no_regression_against_delivered_is_separate_from_historical_target():
    s = fixture()
    for p in s['pairs']:
        r = p['after']['sample']; r['callback_times_ns'] = [1000000000+i*90000000 for i in range(128)]; r['interval_ns'] = 127*90000000
    r = evaluate(s)
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 200
    assert not r['target_3x_passed']


@pytest.mark.parametrize('mutate', [
    lambda s: s['build']['experiment'].update(target_multiplier=2),
    lambda s: s['build']['experiment'].update(predeclared_factors=[4]),
    lambda s: s['build']['experiment'].update(default_enabled=True),
    lambda s: s['build']['experiment'].update(experimental_repacked_weights_build=True),
    lambda s: s['build']['experiment'].update(source_commit='x'*40),
    lambda s: s['build']['payloads']['candidate'].update(original_sha256='e'*64),
    lambda s: s.update(factor=16),
    lambda s: s['correctness']['off']['tile'].update(factor=4),
    lambda s: s['correctness']['on']['tile'].update(kq=2),
    lambda s: s['correctness']['on'].update(vulkan_environment=ENV.copy()),
    lambda s: s['correctness']['off']['sample'].update(native_tokens=127),
    lambda s: s['correctness']['on']['warmup'].update(response='different'),
    lambda s: s['correctness']['on'].update(native_per_token_callbacks=False),
    lambda s: s['pairs'][0]['candidate']['sample'].update(response='different'),
    lambda s: s['pairs'][0]['candidate']['settings'].update(context=1024),
    lambda s: s['pairs'][0]['candidate'].update(expansion={}),
    lambda s: s['pairs'][0]['candidate']['tile'].update(int_dot=1),
    lambda s: s['pairs'][0]['candidate']['tile_dispatch'].pop('q6_K'),
    lambda s: s['pairs'][0]['candidate']['tile_dispatch']['q4_K'].update(rows=2),
    lambda s: s['pairs'][0]['candidate']['tile_dispatch']['q8_0'].update(quantize_y=1),
    lambda s: s['pairs'][0]['candidate'].update(vulkan_positive_offload=False),
    lambda s: s['pairs'][0]['candidate']['sample'].update(strict={'status':'FAIL'}),
    lambda s: s['pairs'][0].update(order=['candidate','before','after']),
    lambda s: s.update(hardware='physical_phone'),
])
def test_invalid_identity_quality_scope_or_precision_cannot_pass(mutate):
    s = fixture(); mutate(s)
    with pytest.raises(AssertionError): evaluate(s)


def test_correctness_and_warmup_rates_are_not_speed_samples():
    s = fixture(); expected = evaluate(s)
    for r in [*s['correctness'].values(), *[p[k] for p in s['pairs'] for k in ('before','after','candidate')]]:
        stages = ('warmup','sample') if r in s['correctness'].values() else ('warmup',)
        for stage in stages:
            row = r[stage]; row['callback_times_ns'] = [v*3 for v in row['callback_times_ns']]; row['interval_ns'] *= 3
    assert evaluate(s) == expected


def test_native_telemetry_not_just_an_environment_variable():
    assert parse_native(native_log(4))[0] == [tile(4)]
    assert parse_native(native_log(8))[0] == [tile(8)]
    assert candidate_metadata(native_log(4))['tile'] == tile(4)
    assert candidate_metadata(native_log(4))['tile_dispatch'] == dispatch(4)
    # Repeated identical lines (dynamic pipeline compiles) are one configuration.
    assert parse_native(native_log(4)*5)[0] == [tile(4)]
    for invalid in ['llvmpipe fp16: 0 int dot: 0',
                    native_log(4).replace('kq_rows=8', 'kq_rows=2'),
                    native_log(4).replace('int_dot=0', 'int_dot=1'),
                    native_log(4) + native_log(8),
                    native_log(4) + 'GGUF_REPACKED_WEIGHTS enabled=1\n',
                    native_log(4).replace('emitted=128 callbacks=128', 'emitted=128 callbacks=64')]:
        with pytest.raises(AssertionError): candidate_metadata(invalid)


def test_every_type_the_fixture_uses_is_covered_not_only_standard_quants():
    source = (ROOT/'apk-fix/row_tile_patches.py').read_text()
    for type_name in ('GGML_TYPE_Q5_0', 'GGML_TYPE_Q8_0', 'GGML_TYPE_Q4_K', 'GGML_TYPE_Q6_K'):
        assert type_name in source
    assert 'rm_stdq *= gguf_row_factor' in source and 'rm_kq *= gguf_row_factor' in source
    assert 'rm_stdq_int *= gguf_row_factor' in source and 'rm_kq_int *= gguf_row_factor' in source
    upstream = (ROOT/'.cache/llama-mobile/ggml/src/ggml-vulkan/ggml-vulkan.cpp').read_text()
    assert 'uint32_t rm_iq = 2 * rm_kq;' in upstream
    # The scaling block must be inserted after rm_iq is derived so i-quant grouping is untouched.
    assert upstream.index('uint32_t rm_iq = 2 * rm_kq;') < upstream.index('const bool use_subgroups = device->subgroup_arithmetic;')
    assert DISPATCH_BLOCK.index('GGML_TYPE_Q4_K') < DISPATCH_BLOCK.index('std::once_flag')


def test_patch_preserves_all_existing_shader_and_dispatch_code(tmp_path):
    src = ROOT/'.cache/llama-mobile'
    if not src.exists(): pytest.skip('Pinned upstream absent')
    assert subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD'],text=True).strip() == 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
    rel = 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    original = subprocess.check_output(['git','-C',str(src),'show','HEAD:'+rel],text=True)
    result = patch(original); assert patch(result) == result
    assert result.replace(BLOCK,'',1).replace(DISPATCH_BLOCK,'',1) == original
    assert '{2*rm_stdq, 1, 1}, {wg_size_subgroup, 2*rm_stdq, i+1}' in result
    assert '{rm_kq, 1, 1}, {wg_size_subgroup16, rm_kq, i+1}' in result
    p = tmp_path/rel; p.parent.mkdir(parents=True); p.write_text(original)
    sentinel = p.parent/'untouched.comp'; sentinel.write_text('unchanged shader')
    apply(tmp_path); assert p.read_text() == result and sentinel.read_text() == 'unchanged shader'


def test_native_guard_compiles_and_defaults_off(tmp_path):
    # Compiles the actual injected block, not a reimplementation. NOT GPU proof.
    source = tmp_path/'guard.cpp'; exe = tmp_path/'guard'
    source.write_text('''#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <cstdio>
#define GGML_LOG_INFO(...) std::printf(__VA_ARGS__)
struct Limits {unsigned maxComputeWorkGroupInvocations;};
struct Properties {std::string deviceName; Limits limits;};
struct Device {Properties properties; bool fp16=false,integer_dot_product=false; unsigned subgroup_size=8;};
int main(int argc,char** argv){Device d; auto device=&d;
volatile unsigned wg_limit = 256;
if(argc>1)d.properties.deviceName=argv[1]; else d.properties.deviceName="llvmpipe (LLVM 21.0.0, 256 bits)";
if(argc>2)d.fp16=true; if(argc>3)wg_limit=(unsigned)atoi(argv[3]);
d.properties.limits.maxComputeWorkGroupInvocations=wg_limit;
uint32_t rm_stdq=1, rm_kq=2, rm_stdq_int=1, rm_kq_int=1;
try {
'''+BLOCK+'''
return (int)(rm_stdq + 2*rm_kq + 4*rm_stdq_int + 8*rm_kq_int);
} catch(const std::runtime_error&) {return -1;}}
''')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('GGML_','GGUF_'))}
    subprocess.run(['g++','-std=c++17','-DGGUF_EXPERIMENT_ROW_TILE=1',str(source),'-o',str(exe)],check=True,capture_output=True)
    assert subprocess.run([str(exe)],env=env,capture_output=True).returncode == 17
    for factor in ACCEPTED_FACTORS:
        assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':str(factor)},capture_output=True).returncode == (17*factor) % 256
    for value in ('0','32','garbage',''):
        assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':value},capture_output=True).returncode == 255
    for args in (['Adreno'], ['llvmpipe','fp16']):
        assert subprocess.run([str(exe),*args],env={**env,'GGUF_VK_ROW_TILE':'4'},capture_output=True).returncode == 255
    for factor in (4, 8):
        assert subprocess.run([str(exe),'llvmpipe (LLVM)','','64'],env={**env,'GGUF_VK_ROW_TILE':str(factor)},capture_output=True).returncode == 255
    assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':'4','GGML_VK_FORCE_MMVQ':'1'},capture_output=True).returncode == 255
    subprocess.run(['g++','-std=c++17',str(source),'-o',str(exe)],check=True,capture_output=True)
    assert subprocess.run([str(exe),'Adreno'],env={**env,'GGUF_VK_ROW_TILE':'4'},capture_output=True).returncode == 17

    # Production default: compiled-in factor applies with no environment variable,
    # only on the measured device, and the environment can still disable it.
    subprocess.run(['g++','-std=c++17','-DGGUF_EXPERIMENT_ROW_TILE=1','-DGGUF_ROW_TILE_DEFAULT=8',str(source),'-o',str(exe)],check=True,capture_output=True)
    assert subprocess.run([str(exe)],env=env,capture_output=True).returncode == (17*8) % 256
    assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':'1'},capture_output=True).returncode == 17
    assert subprocess.run([str(exe),'Adreno'],env=env,capture_output=True).returncode == 17


def test_per_token_delivery_is_experimental_real_work_and_not_synthetic_timing(tmp_path):
    source = (ROOT/'apk-fix/native/mobile.cpp').read_text()
    start = source.index('#if defined(GGUF_EXPERIMENT_ROW_TILE)', source.index('decode_and_deliver(e->layers>0'))
    end = source.index('#endif', start) + len('#endif')
    block = source[start:end]
    assert 'flush();' in block and 'std::chrono::milliseconds(50)' in block
    assert 'emitted++' not in block and 'on_token' not in block and 'sleep' not in block
    assert 'GGUF_ROW_TILE_CALLBACKS per_token=1 emitted=%d callbacks=%d' in source
    code = tmp_path/'callbacks.cpp'; exe = tmp_path/'callbacks'
    code.write_text('''#include <chrono>
#include <string>
struct FixedClock {static std::chrono::steady_clock::time_point now(){return {};}};
int main(){using Clock=FixedClock;auto last_flush=Clock::now();
std::string pending;int emitted=0,callbacks=0;auto flush=[&](){callbacks++;};
for(emitted=1;emitted<=4;++emitted){
'''+block+'''
}return callbacks;}
''')
    for defines, expected in [([],1), (['-DGGUF_EXPERIMENT_ROW_TILE=1'],4)]:
        subprocess.run(['g++','-std=c++17',*defines,str(code),'-o',str(exe)],check=True,capture_output=True)
        assert subprocess.run([str(exe)],capture_output=True).returncode == expected


def test_workflow_measures_both_predeclared_factors_in_both_states():
    workflow = (ROOT/'.github/workflows/row-tile.yml').read_text()
    assert 'state: [awake, asleep]' in workflow and 'factor: [4, 8]' in workflow and 'fail-fast: false' in workflow
    assert 'target_multiplier=3,predeclared_factors=[4,8]' in workflow and 'experimental_row_tile_build=True' in workflow
    assert 'GGUF_EXPERIMENT_ROW_TILE:' in workflow and 'evaluate_row_tile.py' in workflow
    assert 'test_row_tile_android.py ${{ matrix.state }} ${{ matrix.factor }}' in workflow
    assert 'NOT release' in workflow and 'default_enabled=False' in workflow
    assert "'[row tile]'" in (ROOT/'.github/workflows/mobile.yml').read_text()
    assert 'GGUF_ROW_TILE_TEST_IMPORT' in (ROOT/'scripts/build_gpu_rate_observer.sh').read_text()
    assert 'GGUF_EXPERIMENT_ROW_TILE "Build opt-in unchanged-precision Vulkan row grouping" OFF' in (ROOT/'apk-fix/native/CMakeLists.txt').read_text()
