import importlib.util,json,subprocess,sys
from pathlib import Path
import pytest
from test_perceptible_text_gate import fixture
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from stable_text_gate import evaluate,POLICY,USER_REQUEST
from perceptible_text_gate import evaluate as original_gate
from perceptible_image_gate import CANDIDATE

def authorization():
    return dict(policy=POLICY,user_request=USER_REQUEST,payload_source_sha256=CANDIDATE,preserve_original_gate_result=True)

def small():
    s=fixture();s['status']='TEXT_GAIN_GATE_NOT_MET'
    for pair in s['pairs']:
        r=pair['after']['awake']['sample'];r['native_decode_tokens_s']=4.04;r['metrics']['decodeNs']=128e9/4.04
    return s

def test_small_consistent_gain_requires_explicit_new_policy_and_keeps_old_failure():
    s=small();assert not original_gate(s)['text_gain_passed']
    r=evaluate(s,authorization());assert r['text_gain_passed'] and not r['original_gate_passed']
    assert r['original_gate_status']=='TEXT_GAIN_GATE_NOT_MET'

@pytest.mark.parametrize('mutation',[
    lambda a:a.__setitem__('policy','silently-weakened'),
    lambda a:a.__setitem__('user_request','not authorized'),
    lambda a:a.__setitem__('payload_source_sha256','different'),
    lambda a:a.__setitem__('preserve_original_gate_result',False),
])
def test_missing_or_wrong_authorization_rejected(mutation):
    a=authorization();mutation(a)
    with pytest.raises(AssertionError):evaluate(small(),a)

def test_one_unchanged_pair_or_slower_first_text_blocks():
    s=small();r=s['pairs'][0]['after']['awake']['sample'];r['native_decode_tokens_s']=4;r['metrics']['decodeNs']=128e9/4
    assert not evaluate(s,authorization())['text_gain_passed']
    s=small();s['pairs'][0]['after']['awake']['sample']['send_to_first_ui_ns']=1000000001
    assert not evaluate(s,authorization())['text_gain_passed']

def test_sleep_cannot_be_slowed_to_hide_awake_gap():
    s=small()
    for p in s['pairs']:
        r=p['after']['asleep']['sample'];r['native_decode_tokens_s']=3.99;r['metrics']['decodeNs']=128e9/3.99
    assert not evaluate(s,authorization())['text_gain_passed']

def test_signer_validates_authorization_before_private_material(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('stable_signer',ROOT/'scripts/sign_gain_release.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'evaluate',lambda r:{'gain_gate_passed':True})
    image=tmp_path/'images';text=tmp_path/'text';image.mkdir();text.mkdir()
    (image/'summary.json').write_text(json.dumps(dict(status='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY')))
    (text/'summary.json').write_text(json.dumps(small()))
    with pytest.raises(AssertionError,match='Text gain'):mod.main(image,text)
    auth=tmp_path/'auth.json';a=authorization();a['payload_source_sha256']='wrong';auth.write_text(json.dumps(a))
    with pytest.raises(AssertionError):mod.main(image,text,stable_authorization=auth)
    assert not (tmp_path/'.signing').exists() and not (tmp_path/'entrega').exists()

def test_optimized_python_rejected_before_checks():
    p=subprocess.run([sys.executable,'-O','-c',"import sys;sys.path.insert(0,'ci');from stable_text_gate import evaluate;evaluate({},{})"],cwd=ROOT,capture_output=True,text=True)
    assert p.returncode!=0 and 'Optimized Python' in p.stderr


def test_signer_does_not_consume_the_password_file_twice():
    source=(ROOT/'scripts/sign_gain_release.py').read_text()
    signing=source[source.index("    subprocess.run([str(java),'-jar',str(signer),'sign'"):source.index('    verified=')]
    assert "'--ks-pass','file:'+str(password)" in signing
    assert "'--key-pass'" not in signing


def test_both_signatures_verified_without_changing_manifest_min_sdk():
    source=(ROOT/'scripts/sign_gain_release.py').read_text()
    assert "'--min-sdk-version','24','--max-sdk-version','27',str(candidate)" in source
    assert "Scheme v2): true' in verified_v2" in source
    assert "Scheme v3): true' in verified" in source
    assert "certificate SHA-256 digest: '+cert[1] in verified_v2" in source
