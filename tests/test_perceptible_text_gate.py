from pathlib import Path
import sys,copy
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from perceptible_text_gate import evaluate
from perceptible_image_gate import BASELINE,CANDIDATE

def fixture():
    def sample(rate,latency):
        ns=128e9/rate
        return {'raw_history':[['user','prompt'],['assistant',' exact ']],'tokens':128,
                'metrics':{'promptTokens':500,'reusedPromptTokens':300,'completed':True,'decodeNs':ns},
                'strict':{'status':'PASS'},'native_decode_tokens_s':rate,'send_to_first_ui_ns':latency}
    def phase(after):
        return {state:{kind:sample(4.8 if after else 4,1000000000) for kind in ('warmup','sample')} for state in ('awake','asleep')}
    return {'status':'RUNNING','build':{'baseline_original_sha256':BASELINE,'candidate_original_sha256':CANDIDATE,'resigning_payload_exact':True},
            'pairs':[{'before':phase(False),'after':phase(True)},{'after':phase(True),'before':phase(False)},{'before':phase(False),'after':phase(True)}]}

def test_three_warmed_pairs_needed_and_one_slow_pair_blocks():
    s=fixture();assert evaluate(s)['text_gain_passed']
    r=s['pairs'][0]['after']['awake']['sample'];r['native_decode_tokens_s']=4.1;r['metrics']['decodeNs']=128e9/4.1
    assert not evaluate(s)['text_gain_passed']

def test_sleep_slowdown_or_raw_output_changes_are_not_hidden():
    s=fixture();r=s['pairs'][1]['after']['asleep']['sample'];r['native_decode_tokens_s']=3;r['metrics']['decodeNs']=128e9/3
    assert not evaluate(s)['text_gain_passed']
    s=fixture();s['pairs'][0]['after']['awake']['sample']['raw_history'][-1][1]='exact'
    with pytest.raises(AssertionError):evaluate(s)
