"""Regression for exact persisted attachment notices, NOT relaxed substring matching."""
import ast,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from android_checks import assistant_reply

def test_real_attachment_prefix_matches_exact_persisted_user_not_an_old_answer():
    s=(ROOT/'scripts/test_projector_cache_android.py').read_text()
    module=ast.parse(s)
    fn=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='persisted_image_prompt')
    scope={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual helper>','exec'),scope)
    prompt='Name the main animal.'
    expected=scope['persisted_image_prompt'](prompt,1)
    assert expected=='Arquivo anexado: 1 arquivo(s)\n\nAnexos vinculados a esta mensagem para leitura.\n\n'+prompt
    assert scope['persisted_image_prompt'](prompt,0)==prompt
    rows=[dict(id='chat',modelPath='real.gguf',messages=[
        dict(role='user',content=expected),dict(role='assistant',content='old'),
        dict(role='user',content=expected),dict(role='assistant',content='new')])]
    assert assistant_reply(rows,'chat',expected)=='new'
    import pytest
    with pytest.raises(AssertionError):assistant_reply(rows,'chat',prompt)
    assert 'persisted_prompt=expected' in s

def test_timeout_always_preserves_diagnostics_and_clock_budget_is_explicit():
    s=(ROOT/'scripts/test_generation_stats_android.py').read_text()
    assert 'finally:' in s and '-last-log.txt' in s and '-last-chats.json' in s
    assert '0<elapsed<timeout' in s
    assert "prompt if persisted_prompt is None else persisted_prompt" in s


def test_postcheck_rejects_whitespace_changes_and_missing_results(tmp_path):
    import json,importlib.util,pytest
    spec=importlib.util.spec_from_file_location('postcheck',ROOT/'ci/evaluate_projector_app.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    (tmp_path/'summary.json').write_text(json.dumps({'status':'FAIL'}))
    with pytest.raises(ValueError):mod.evaluate(tmp_path)
    (tmp_path/'summary.json').write_text(json.dumps({'status':'PASS_PROJECTOR_CACHE_EXPERIMENT_ONLY'}))
    with pytest.raises(FileNotFoundError):mod.evaluate(tmp_path)
    for phase in ('before','after'):
        for screen in ('awake','asleep'):
            labels=[f'projector-{phase}-{screen}-0-'+s for s in ('cold_A','append_B','exclude_A','restore_A')]+[f'whole-app-{phase}-{screen}']
            for label in labels:
                row={'tokens':2,'metrics':{'tokens':2,'decodeNs':1000000000,'firstTokenNs':500000000,'completed':True},'native_decode_tokens_s':2,
                     'chat':{'messages':[{'role':'user','content':'prompt'},{'role':'assistant','content':' exact\r\n'}]}}
                (tmp_path/f'physical-speed-perf-{label}.json').write_text(json.dumps(row))
    assert len(mod.evaluate(tmp_path)['observations'])==10
    p=tmp_path/'physical-speed-perf-whole-app-after-awake.json';r=json.loads(p.read_text())
    r['chat']['messages'][-1]['content']='exact';p.write_text(json.dumps(r))
    with pytest.raises(AssertionError,match='Raw persisted history changed'):mod.evaluate(tmp_path)
