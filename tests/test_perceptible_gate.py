import copy,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from perceptible_image_gate import evaluate,BASELINE,CANDIDATE

def fixture():
    r={'raw_history':[['user','same photo input'],['assistant',' exact ']],'tokens':2,
       'metrics':{'tokens':2,'promptTokens':513,'decodeNs':1000000000,'completed':True},'native_decode_tokens_s':2,
       'image_records':[['64','Vulkan']]*10,'prepared_dimensions':[['1024','803','ImageDecoder'],['768','1024','ImageDecoder']],
       'strict':{'status':'PASS'},'diagnostic':False,'send_to_first_ui_ns':100000000000,
       'cache':{'hits':0,'misses':10},'stages':{'verification':0,'verified_hits':0,'cache_disabled':0,'encode_calls':10}}
    def version(after):
        rows={s:copy.deepcopy(r) for s in ('prime','exclude','restore')}
        rows['exclude']['prepared_dimensions']=rows['exclude']['prepared_dimensions'][1:]
        rows['exclude']['image_records']=rows['exclude']['image_records'][:5]
        if after:
            rows['restore']['send_to_first_ui_ns']=20000000000
            rows['restore']['cache']={'hits':10,'misses':0}
            rows['restore']['stages']['encode_calls']=0
        return rows
    return {'status':'RUNNING','build':{'baseline_original_sha256':BASELINE,'candidate_original_sha256':CANDIDATE,'resigning_payload_exact':True},
            'pairs':[{'before':version(False),'after':version(True)},{'after':version(True),'before':version(False)}],
            'checks':{k:'PASS' for k in ('code_and_copy','android_decoder','screen_off_completion','same_signer_test_update_preserved_data')}}

def test_requires_perceptible_gain_in_both_pairs():
    s=fixture();assert evaluate(s)['gain_gate_passed']
    s['pairs'][1]['after']['restore']['send_to_first_ui_ns']=60000000000
    assert not evaluate(s)['gain_gate_passed']

def test_rejects_output_changes_diagnostics_hidden_input_reduction_and_wrong_apk():
    mutations=[lambda s:s['pairs'][0]['after']['restore']['raw_history'][-1].__setitem__(1,'exact'),
               lambda s:s['pairs'][0]['after']['restore'].__setitem__('diagnostic',True),
               lambda s:s['pairs'][0]['after']['restore'].__setitem__('image_records',[]),
               lambda s:s['pairs'][0]['after']['restore']['stages'].__setitem__('cache_disabled',1),
               lambda s:s['build'].__setitem__('candidate_original_sha256','different'),
               lambda s:s['checks'].__setitem__('screen_off_completion','FAIL'),
               lambda s:s.__setitem__('status','FAIL')]
    for mutate in mutations:
        s=fixture();mutate(s)
        with pytest.raises(AssertionError):evaluate(s)

def test_publication_is_downstream_of_both_real_test_and_independent_gate():
    s=(ROOT/'.github/workflows/perceptible-release.yml').read_text()
    assert s.index('script: .venv/bin/python scripts/test_perceptible_image_android.py')<s.index('python3 ci/perceptible_image_gate.py evidence/summary.json')<s.index('Relay approved payload')
    relay=s[s.index('      - name: Relay approved payload'):s.index('      - name: Publish bounded')]
    assert 'if: always()' not in relay and "assert r['status']=='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY'" in relay
    assert 'GGUF-Chat-mobile.apk\')' not in relay


def test_release_signer_preserves_non_signature_metadata(tmp_path):
    import importlib.util,zipfile
    spec=importlib.util.spec_from_file_location('gain_signer',ROOT/'scripts/sign_gain_release.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    a=tmp_path/'a.apk';b=tmp_path/'b.apk'
    def write(path,cert,service):
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('classes.dex',b'exact-dex');z.writestr('lib/arm64-v8a/libaijni.so',b'exact-native')
            z.writestr('META-INF/CERT.RSA',cert);z.writestr('META-INF/services/example',service)
    write(a,b'old',b'keep');write(b,b'new',b'keep');assert mod.payload(a)==mod.payload(b)
    write(b,b'new',b'changed');assert mod.payload(a)!=mod.payload(b)
    s=(ROOT/'scripts/sign_gain_release.py').read_text()
    assert s.index("gate=evaluate(report);assert gate['gain_gate_passed']")<s.index("private=ROOT/'.signing'")
    assert 'install' not in s[s.index('def main('):].replace('in-place update','').replace('uninstall','')


def test_public_archive_fetch_refuses_unapproved_report_before_network(tmp_path,monkeypatch):
    import importlib.util,json
    spec=importlib.util.spec_from_file_location('gain_fetcher',ROOT/'scripts/fetch_gain_approved_apk.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.urllib.request,'urlopen',lambda *a,**k:pytest.fail('Network must not run before gain approval'))
    (tmp_path/'summary.json').write_text(json.dumps({'status':'FAIL'}))
    with pytest.raises(AssertionError):mod.main(tmp_path,'0'*40)
    with pytest.raises(AssertionError):mod.main(tmp_path,'not-a-commit')
