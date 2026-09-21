import copy,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'ci'),str(ROOT/'scripts')]
from evaluate_gpu_rate import evaluate,HASHES,MODEL,METRIC,SETTINGS,PRIME,FOLLOW
from test_gpu_rate_android import collect


def fixture():
    build=dict(release_approved=False,payloads={p:dict(original_sha256=h,test_sha256='a'*64,non_signature_payload_identical=True,native={'lib/x86_64/libaijni.so':'b'*64}) for p,h in HASHES.items()})
    s=dict(status='COMPLETE_OBSERVATIONS',state='awake',hardware='software_vulkan_emulator',release_approved=False,apk_sha256=HASHES.copy(),model_sha256=MODEL,build=build,pairs=[])
    for order in (['before','after'],['after','before'],['before','after']):
        pair={'order':order};s['pairs'].append(pair)
        for phase in order:
            r=dict(status='PASS_NATIVE_OBSERVER',model_sha256=MODEL,test_apk_sha256='a'*64,settings=SETTINGS.copy(),vulkan_environment={'GGML_VK_VISIBLE_DEVICES':'0'},vulkan_positive_offload=True,batch=128,ubatch=32);pair[phase]=r
            for stage in ('warmup','sample'):
                step=200000000 if phase=='before' else 100000000
                ticks=[1000000000+i*step for i in range(128)]
                r[stage]=dict(metric=METRIC,stage=stage,screen_asleep=False,native_success=True,done_success=True,native_tokens=128,callbacks=128,native_reason='length',callback_times_ns=ticks,interval_ns=ticks[-1]-ticks[0],chunks=['word ']*128,response='word '*128,prompt_token_ids=[1,2,3],prompt=PRIME+('word '*128+FOLLOW if stage=='sample' else ''),strict={'status':'PASS','tensor_cpu_fallback':'blocked_by_native_policy'})
    return s


def test_real_intervals_exclude_first_token_and_warmup():
    s=fixture();r=evaluate(s)
    assert r['before_median_tps']==5 and r['after_median_tps']==10
    assert r['median_paired_gain_percent']==100 and r['all_pairs_faster']
    assert not r['physical_gpu_certified'] and not r['release_approved']
    assert not r['baseline_all_tensor_gpu_policy_proven']
    for pair in s['pairs']:
        for phase in ('before','after'):
            row=pair[phase]['warmup'];row['callback_times_ns']=[x*4 for x in row['callback_times_ns']];row['interval_ns']*=4
    assert evaluate(s)==r


@pytest.mark.parametrize('field,value',[
    ('callbacks',127),('native_tokens',127),('native_reason','eog'),('interval_ns',1),
    ('callback_times_ns',[1]*128),('metric','total_response_including_prefill'),
    ('chunks',['merged']*64),('response','word '*127),('screen_asleep',True),
    ('prompt_token_ids',[1]*2000),('strict',{'status':'FAIL'}),('native_success',False),
])
def test_invalid_tokens_clocks_output_scope_or_gpu_fail_closed(field,value):
    s=fixture();s['pairs'][0]['after']['sample'][field]=value
    with pytest.raises(AssertionError):evaluate(s)


@pytest.mark.parametrize('field,value',[
    ('vulkan_positive_offload',False),('vulkan_environment',{}),('batch',512),
    ('ubatch',64),('model_sha256','wrong'),('settings',{}),('test_apk_sha256','b'*64),
])
def test_runtime_must_match(field,value):
    s=fixture();s['pairs'][0]['after'][field]=value
    with pytest.raises(AssertionError):evaluate(s)


def test_full_output_and_prompt_tokens_not_just_token_count():
    s=fixture();r=s['pairs'][0]['after']['sample'];r['chunks'][-1]='different';r['response']=''.join(r['chunks'])
    with pytest.raises(AssertionError):evaluate(s)
    s=fixture();s['pairs'][0]['before']['sample']['prompt_token_ids'][0]=100
    with pytest.raises(AssertionError):evaluate(s)


def test_regression_remains_a_valid_comparison_not_a_gain():
    s=fixture()
    for pair in s['pairs']:
        r=pair['after']['sample'];r['callback_times_ns']=[x*3 for x in r['callback_times_ns']];r['interval_ns']*=3
    r=evaluate(s);assert not r['all_pairs_faster'] and r['median_paired_gain_percent']<0


def test_pairing_and_original_identity_cannot_be_replaced():
    for mutate in (
        lambda s:s['pairs'][1].update(order=['before','after']),
        lambda s:s['apk_sha256'].update(before='409985de'),
        lambda s:s['build']['payloads']['before'].update(non_signature_payload_identical=False),
        lambda s:s.update(pairs=s['pairs'][:2]),
    ):
        s=fixture();mutate(s)
        with pytest.raises(AssertionError):evaluate(s)


def log_fixture():
    lines=['registered backend Vulkan','llama_model_loader: loaded meta data','offloaded 31/31 layers to GPU','n_batch = 128','n_ubatch = 32']
    for stage in ('warmup','sample'):
        lines += ['GPU_RATE_BEGIN stage='+stage,'GGUF_NATIVE_COMPLETE tokens=128 reason=length projector=0',
                  'GGUF_GPU_SAMPLING_RESULT backend_selected=128 emitted=128',
                  'GGUF_STRICT_VULKAN_RESULT enabled=1 submitted_graphs=128 submitted_math_nodes=10000 blocked=0 host_orchestration=CPU',
                  'GPU_RATE_END stage='+stage]
    return '\n'.join('09-18 22:00:00.000 100 101 I GpuRateObserver: '+line for line in lines)


def test_log_collector_uses_native_counter_and_each_stage_strict_proof():
    r=fixture()['pairs'][0]['after'];r=collect(r,log_fixture(),'after')
    assert r['sample']['native_tokens']==128 and r['sample']['strict']['status']=='PASS'
    with pytest.raises(AssertionError):collect(copy.deepcopy(r),log_fixture().replace('tokens=128','tokens=127'),'after')
    with pytest.raises(AssertionError):collect(copy.deepcopy(r),log_fixture().replace('offloaded 31/31','offloaded 0/31'),'after')
    with pytest.raises(AssertionError):collect(copy.deepcopy(r),log_fixture().replace('GPU_RATE_BEGIN stage=sample','no sample marker'),'after')


def test_observer_has_no_model_rebuild_or_production_signing():
    build=(ROOT/'scripts/build_gpu_rate_observer.sh').read_text()
    java=(ROOT/'tests/android-gpu-rate/src/com/ggufchat/gpurate/RateInstrumentation.java').read_text()
    assert 'entries==payload(dst)' in build and 'trap' in build
    assert '.signing/' not in build and 'build_mobile' not in build
    assert 'getTargetContext().getClassLoader()' in java and 'System.nanoTime()' in java
    assert 'count[0]==128' in java and 'power.isInteractive()!=sleeping' in java
