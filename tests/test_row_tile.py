import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ci'), str(ROOT/'scripts'), str(ROOT/'apk-fix')]
from row_tile_patches import patch, apply, BLOCK, DISPATCH_BLOCK
from evaluate_row_tile import evaluate, tile, ON, ENV, COMPLETE
from test_row_tile_android import candidate_metadata
from test_expanded_weights import fixture as expansion_fixture


def fixture():
    s = expansion_fixture(); s['status'] = COMPLETE
    e = s['build']['experiment']; e.pop('experimental_expanded_weights_build')
    e.update(experimental_row_tile_build=True, target_multiplier=3, row_factor=4)
    s.pop('proof')
    for pair in s['pairs']:
        r = pair['candidate']; r.pop('expansion'); r['tile'] = tile(4); r['vulkan_environment'] = ON.copy()
        for stage in ('warmup', 'sample'):
            row = pair['before'][stage]
            row['callback_times_ns'] = [1000000000+i*300000000 for i in range(128)]
            row['interval_ns'] = row['callback_times_ns'][-1] - row['callback_times_ns'][0]
    s['correctness'] = {mode: copy.deepcopy(s['pairs'][0]['candidate']) for mode in ('off', 'on')}
    s['correctness']['off'].update(tile=tile(1), vulkan_environment=ENV.copy())
    for r in [*s['correctness'].values(), *[p['candidate'] for p in s['pairs']]]:
        f = r['tile']['factor']; r['tile_dispatch'] = {t: dict(rows=n,activation='f32',quantize_y=0,columns=1) for t,n in [('q5_0',2*f),('q8_0',f)]}
    return s


def test_200_percent_means_three_times_in_every_historical_pair():
    r = evaluate(fixture())
    assert r['target_multiplier'] == 3 and r['target_gain_percent'] == 200
    assert r['target_3x_passed'] and not r['release_approved'] and not r['physical_gpu_certified']
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 200
    assert r['comparisons']['delivered']['median_paired_gain_percent'] == 0
    s = fixture()
    for p in s['pairs']:
        r = p['before']['sample']; r['callback_times_ns'] = [1000000000+i*200000000 for i in range(128)]; r['interval_ns'] = 127*200000000
    r = evaluate(s)
    assert not r['target_3x_passed'] and r['status'] == 'THREE_TIMES_TARGET_NOT_MET'
    assert r['comparisons']['historical']['median_paired_gain_percent'] == 100


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
    lambda s: s['build']['experiment'].update(row_factor=8),
    lambda s: s['build']['experiment'].update(default_enabled=True),
    lambda s: s['build']['experiment'].update(experimental_repacked_weights_build=True),
    lambda s: s['build']['experiment'].update(source_commit='x'*40),
    lambda s: s['build']['payloads']['candidate'].update(original_sha256='e'*64),
    lambda s: s['correctness']['off']['tile'].update(factor=4),
    lambda s: s['correctness']['on']['tile'].update(fp16=1),
    lambda s: s['correctness']['on'].update(vulkan_environment=ENV.copy()),
    lambda s: s['correctness']['off']['sample'].update(native_tokens=127),
    lambda s: s['correctness']['on']['warmup'].update(response='different'),
    lambda s: s['pairs'][0]['candidate']['sample'].update(response='different'),
    lambda s: s['pairs'][0]['candidate']['settings'].update(context=1024),
    lambda s: s['pairs'][0]['candidate'].update(expansion={}),
    lambda s: s['pairs'][0]['candidate']['tile'].update(int_dot=1),
    lambda s: s['pairs'][0]['candidate']['tile_dispatch']['q5_0'].update(rows=2),
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
    line = 'llvmpipe fp16: 0 int dot: 0\nGGUF_VK_ROW_TILE factor=4 stdq=4 q5_rows=8 q8_rows=4 fp16=0 int_dot=0 subgroup=8\n'
    line += 'GGUF_VK_ROW_TILE_DISPATCH type=q5_0 rows=8 activation=f32 quantize_y=0 columns=1\nGGUF_VK_ROW_TILE_DISPATCH type=q8_0 rows=4 activation=f32 quantize_y=0 columns=1\n'
    assert candidate_metadata(line)['tile'] == tile(4)
    for invalid in [line+line, line.replace('q5_rows=8','q5_rows=2'), line.replace('int dot: 0','int dot: 1'), line+'GGUF_REPACKED_WEIGHTS enabled=1', 'llvmpipe fp16: 0 int dot: 0']:
        with pytest.raises(AssertionError): candidate_metadata(invalid)


def test_patch_preserves_all_existing_shader_and_dispatch_code(tmp_path):
    src = ROOT/'.cache/llama-mobile'
    if not src.exists(): pytest.skip('Pinned upstream absent')
    assert subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD'],text=True).strip() == 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
    rel = 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
    original = subprocess.check_output(['git','-C',str(src),'show','HEAD:'+rel],text=True)
    result = patch(original); assert patch(result) == result and result.replace(BLOCK,'',1).replace(DISPATCH_BLOCK,'',1) == original
    assert 'device->mmvq_mode' not in BLOCK  # initialized AFTER ggml_vk_load_shaders
    assert '{2*rm_stdq, 1, 1}, {wg_size_subgroup, 2*rm_stdq, i+1}' in result
    assert '{1*rm_stdq, 1, 1}, {wg_size_subgroup, 1*rm_stdq, i+1}' in result
    p = tmp_path/rel; p.parent.mkdir(parents=True); p.write_text(original)
    sentinel = p.parent/'untouched.comp'; sentinel.write_text('unchanged shader')
    apply(tmp_path); assert p.read_text() == result and sentinel.read_text() == 'unchanged shader'


def test_native_guard_compiles_and_defaults_off(tmp_path):
    # Compiles the actual injected block, not a reimplementation. NOT GPU proof.
    source = tmp_path/'guard.cpp'; exe = tmp_path/'guard'
    source.write_text('''#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <cstdio>
#define GGML_LOG_INFO(...) std::printf(__VA_ARGS__)
struct Device {std::string name="llvmpipe"; bool fp16=false,integer_dot_product=false; unsigned subgroup_size=8;};
int main(int argc,char** argv){Device d; auto device=&d; uint32_t rm_stdq=1;
if(argc>1)d.name=argv[1]; if(argc>2)d.fp16=true;
try {
'''+BLOCK+'''
return rm_stdq==4 ? 4 : 0;
} catch(const std::runtime_error&) {return 10;}}
''')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('GGML_','GGUF_'))}
    subprocess.run(['g++','-std=c++17','-DGGUF_EXPERIMENT_ROW_TILE=1',str(source),'-o',str(exe)],check=True,capture_output=True)
    assert subprocess.run([str(exe)],env=env,capture_output=True).returncode == 0
    assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':'4'},capture_output=True).returncode == 4
    for value in ('0','1','8','garbage',''):
        assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':value},capture_output=True).returncode == 10
    for args in (['Adreno'], ['llvmpipe','fp16']):
        assert subprocess.run([str(exe),*args],env={**env,'GGUF_VK_ROW_TILE':'4'},capture_output=True).returncode == 10
    assert subprocess.run([str(exe)],env={**env,'GGUF_VK_ROW_TILE':'4','GGML_VK_FORCE_MMVQ':'1'},capture_output=True).returncode == 10
    subprocess.run(['g++','-std=c++17',str(source),'-o',str(exe)],check=True,capture_output=True)
    assert subprocess.run([str(exe),'Adreno'],env={**env,'GGUF_VK_ROW_TILE':'4'},capture_output=True).returncode == 0


def test_workflow_keeps_delivery_separate_and_requires_both_states():
    workflow = (ROOT/'.github/workflows/row-tile.yml').read_text()
    assert 'state: [awake, asleep]' in workflow and 'fail-fast: false' in workflow
    assert 'target_multiplier=3,row_factor=4' in workflow and 'experimental_row_tile_build=True' in workflow
    assert 'GGUF_EXPERIMENT_ROW_TILE:' in workflow and 'evaluate_row_tile.py' in workflow
    assert 'GGUF_REUSE_TESTED_NATIVE:' in workflow and 'test_row_tile_android.py' in workflow
    assert 'NOT release' in workflow and 'default_enabled=False' in workflow
    assert "'[row tile]'" in (ROOT/'.github/workflows/mobile.yml').read_text()
    assert 'GGUF_ROW_TILE_TEST_IMPORT' in (ROOT/'scripts/build_gpu_rate_observer.sh').read_text()
    assert 'GGUF_EXPERIMENT_ROW_TILE "Build opt-in unchanged-precision Vulkan row grouping" OFF' in (ROOT/'apk-fix/native/CMakeLists.txt').read_text()
