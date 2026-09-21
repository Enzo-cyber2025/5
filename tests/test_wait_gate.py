import copy,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from evaluate_vulkan_wait import evaluate
from test_perceptible_text_gate import fixture as text_fixture

def fixture(kind='text'):
    s=text_fixture();s['kind']=kind;s['build'].update(apk_sha256='a'*64,experimental_wait_build=True,default_blocking_wait=True)
    s['code_and_copy']={'stream':'PASS','history':'PASS'}
    if kind=='images':s['pairs']=s['pairs'][:2]
    for pair in s['pairs']:
        for phase,states in pair.items():
            for state,stages in states.items():
                for name,r in stages.items():
                    r.update(worker_cpu_ns=10000 if phase=='before' else 1000,blocking_wait=phase=='after')
                    r['strict'].update(tensor_cpu_fallback='blocked_by_native_policy',submitted_graphs=129,submitted_math_nodes=70000)
                    if kind=='images':
                        r['image_records']=[['64','Vulkan']]*5;r['prepared_dimensions']=[['1024','803','ImageDecoder']]
                        r['send_to_first_ui_ns']=2000000000 if phase=='before' else 1000000000
                        r['stages']=dict(cache_disabled=1,hits=0,verified_hits=0,verification=0,encode_calls=5,encode_call_ns=2000000000 if phase=='before' else 1000000000)
    return s

@pytest.mark.parametrize('kind',['text','images'])
def test_requires_wall_time_gain_not_only_lower_cpu(kind):
    s=fixture(kind);assert evaluate(s)['gain_passed']
    for pair in s['pairs']:
        for state in pair['after']:
            r=pair['after'][state]['sample'];a=pair['before'][state]['sample']
            r['native_decode_tokens_s']=a['native_decode_tokens_s'];r['metrics']['decodeNs']=a['metrics']['decodeNs']
            if kind=='images':r['send_to_first_ui_ns']=a['send_to_first_ui_ns']
    assert not evaluate(s)['gain_passed']

@pytest.mark.parametrize('mutate',[
    lambda s:s['pairs'][0]['after']['awake']['sample'].__setitem__('blocking_wait',False),
    lambda s:s['pairs'][0]['after']['awake']['sample']['strict'].__setitem__('submitted_math_nodes',1),
    lambda s:s['pairs'][0]['after']['awake']['sample']['raw_history'][-1].__setitem__(1,'changed'),
    lambda s:s['pairs'][0]['after']['awake']['sample'].__setitem__('worker_cpu_ns',float('nan')),
    lambda s:s['code_and_copy'].__setitem__('history','FAIL'),
    lambda s:s['build'].__setitem__('experimental_wait_build',False),
])
def test_invalid_evidence_fails_closed(mutate):
    s=fixture();mutate(s)
    with pytest.raises(AssertionError):evaluate(s)

def test_cache_or_smaller_photo_cannot_count_as_faster_encoder():
    s=fixture('images');s['pairs'][0]['after']['awake']['sample']['stages']['hits']=5
    with pytest.raises(AssertionError):evaluate(s)
    s=fixture('images');s['pairs'][0]['after']['awake']['sample']['prepared_dimensions']=[['100','80','ImageDecoder']]
    with pytest.raises(AssertionError):evaluate(s)

def test_greater_host_cpu_cost_blocks_wait_approval():
    s=fixture();s['pairs'][0]['after']['awake']['sample']['worker_cpu_ns']=20000
    assert not evaluate(s)['gain_passed']
