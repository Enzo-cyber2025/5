"""Synthetic tests of target arithmetic, never Android performance evidence."""
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ci'))
from verify_vulkan_target import result


@pytest.mark.parametrize('ratios,expected',[( (1.5,1.5),False),((2.49,2.5),False),((2.5,1.0),False),((2.5,2.5),True),((3.0,2.6),True)])
def test_150_percent_means_2_5_times_in_both_states(tmp_path,monkeypatch,ratios,expected):
    monkeypatch.chdir(tmp_path)
    p=Path('ci-results/1-1');p.mkdir(parents=True)
    s=dict(status='PASS',apk_sha256='synthetic-fixture',medians={screen:dict(before=dict(decode_tokens_s=2),after=dict(decode_tokens_s=2*ratio)) for screen,ratio in zip(('awake','asleep'),ratios)})
    (p/'summary.json').write_text(json.dumps(s))
    a=dict(run=1,attempt=1,apk_sha256='synthetic-fixture',target_throughput_multiplier=2.5)
    assert result(a)[0] is expected
