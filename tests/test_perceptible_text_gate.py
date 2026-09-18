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
                'metrics':{'tokens':128,'version':3,'timingScope':'prefill_synchronized_before_decode','promptTokens':500,'reusedPromptTokens':300,'completed':True,'decodeNs':ns},
                'strict':{'status':'PASS'},'native_decode_tokens_s':rate,'send_to_first_ui_ns':latency}
    def phase(after):
        states={}
        for state in ('awake','asleep'):
            rows={}
            for kind in ('warmup','sample'):
                r=sample(4.8 if after else 4,1000000000)
                if kind=='warmup':r['metrics']['reusedPromptTokens']=0
                else:r['raw_history']*=2
                rows[kind]=r
            states[state]=rows
        return states
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

@pytest.mark.parametrize('mutation',[
    lambda s:s['pairs'].pop(),
    lambda s:s['pairs'].__setitem__(1,dict(reversed(list(s['pairs'][1].items())))),
    lambda s:s['build'].__setitem__('candidate_original_sha256','wrong'),
    lambda s:s['build'].__setitem__('resigning_payload_exact','yes'),
    lambda s:s.__setitem__('status','FAIL'),
    lambda s:s['pairs'][0]['before']['awake']['warmup'].__setitem__('raw_history',[]),
    lambda s:s['pairs'][0]['after']['awake']['sample']['strict'].__setitem__('status','FAIL'),
    lambda s:s['pairs'][0]['after']['awake']['sample']['metrics'].__setitem__('tokens',64),
    lambda s:s['pairs'][0]['after']['awake']['sample']['metrics'].__setitem__('reusedPromptTokens',0),
    lambda s:s['pairs'][0]['after']['awake']['sample']['metrics'].__setitem__('completed','false'),
    lambda s:s['pairs'][0]['after']['awake']['sample']['metrics'].__setitem__('timingScope','other'),
    lambda s:s['pairs'][0]['after']['awake']['sample'].__setitem__('send_to_first_ui_ns',float('inf')),
    lambda s:s['pairs'][0]['after']['awake']['sample'].__setitem__('native_decode_tokens_s',float('nan')),
    lambda s:s['pairs'][0]['after']['awake']['sample']['metrics'].__setitem__('decodeNs',float('inf')),
])
def test_fail_closed_on_missing_or_invalid_evidence(mutation):
    s=fixture();mutation(s)
    with pytest.raises(AssertionError):evaluate(s)

def test_slow_first_text_is_not_hidden_by_high_token_rate():
    s=fixture();s['pairs'][0]['after']['awake']['sample']['send_to_first_ui_ns']=2000000000
    assert not evaluate(s)['text_gain_passed']


def test_signer_rejects_missing_text_gate_before_any_private_key_access(tmp_path,monkeypatch):
    import importlib.util,json
    spec=importlib.util.spec_from_file_location('combined_signer',ROOT/'scripts/sign_gain_release.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'evaluate',lambda r:{'gain_gate_passed':True})
    image=tmp_path/'image';text=tmp_path/'text';image.mkdir();text.mkdir()
    (image/'summary.json').write_text(json.dumps({'status':'PASS_GAIN_GATE_RETAINED_IMAGES_ONLY'}))
    with pytest.raises(FileNotFoundError):mod.main(image,text)
    (text/'summary.json').write_text(json.dumps({'status':'TEXT_GAIN_GATE_NOT_MET'}))
    with pytest.raises(AssertionError,match='Text gain'):mod.main(image,text)
    s=fixture();s['status']='PASS_TEXT_GAIN_GATE'
    s['pairs'][0]['after']['awake']['sample']['send_to_first_ui_ns']=2000000000
    (text/'summary.json').write_text(json.dumps(s))
    with pytest.raises(AssertionError):mod.main(image,text)
    assert not (tmp_path/'.signing').exists() and not (tmp_path/'entrega').exists()


def test_optimized_python_cannot_disable_release_checks():
    import subprocess
    for module,call in (('sign_gain_release',"main('missing','missing')"),('perceptible_text_gate','evaluate({})'),('perceptible_image_gate','evaluate({})')):
        code="import sys;sys.path[:0]=['scripts','ci'];import "+module+" as m;m."+call
        result=subprocess.run([sys.executable,'-O','-c',code],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode!=0 and 'Optimized Python' in result.stderr
