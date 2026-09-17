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
