"""Synthetic arithmetic ONLY. These are not observations of app performance."""
import importlib.util,copy
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('extreme',Path(__file__).resolve().parents[1]/'ci/evaluate_extreme_vulkan.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def fixture():
    return {screen:{'before':{'decode_tokens_s':1,'send_to_first_ui_ns':26,'send_to_first_token_ns':26},
                    'after':{'decode_tokens_s':21,'send_to_first_ui_ns':1,'send_to_first_token_ns':1}} for screen in ('awake','asleep')}

def test_exact_synthetic_boundary():
    r=module.assess(fixture());assert all(r['checks'].values())
    assert not r['physical_gpu_certified'] and not r['release_approved']

def test_20x_is_not_plus_2000_percent():
    m=fixture();m['awake']['after']['decode_tokens_s']=20
    assert not module.assess(m)['checks']['throughput_21x_both_states']

def test_25x_does_not_meet_26x_wait_interpretation():
    m=fixture();m['awake']['before']['send_to_first_ui_ns']=25
    assert not module.assess(m)['checks']['first_token_wait_26x_both_states']

def test_native_timer_cannot_replace_missing_send_timer():
    m=fixture()
    for phase in ('before','after'):
        del m['asleep'][phase]['send_to_first_token_ns']
        m['asleep'][phase]['native_first_token_ns']=1
    r=module.assess(m)
    assert r['end_to_end_first_token_speedups']['asleep'] is None
    assert not r['checks']['first_token_wait_26x_both_states']

def test_cannot_equalize_by_slowing_sleep():
    m=fixture();m['asleep']['before']['decode_tokens_s']=42
    r=module.assess(m)
    assert r['checks']['awake_at_least_as_fast_as_asleep']
    assert not r['checks']['asleep_not_slowed']
    assert not r['checks']['throughput_21x_both_states']

def test_speeding_both_does_not_automatically_mean_parity():
    m=fixture();m['asleep']['after']['decode_tokens_s']=22
    r=module.assess(m)
    assert r['checks']['throughput_21x_both_states']
    assert not r['checks']['awake_at_least_as_fast_as_asleep']

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),0,-1,True])
def test_invalid_rate_fails_closed(bad):
    m=fixture();m['awake']['after']['decode_tokens_s']=bad
    with pytest.raises(AssertionError):module.assess(m)
