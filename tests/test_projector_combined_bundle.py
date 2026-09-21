import copy
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'ci'), str(ROOT / 'tests')]
from test_projector_combined import fixture
from evaluate_projector_combined import evaluate
from evaluate_projector_combined_bundle import evaluate_bundle, KINDS


def seal(report, proof):
    report['result'] = evaluate(report, proof)
    report['status'] = report['result']['status']
    return report


def bundle():
    _, proof = fixture()
    reports = {}
    for kind in KINDS:
        report, _ = fixture(kind)
        for pair in report['pairs']:
            for obs in pair.values():
                if kind == 'asleep':
                    obs['states']['asleep'] = obs['states'].pop('awake')
                elif kind == 'text':
                    for stage, row in obs['states']['awake'].items():
                        row['tokens'] = row['metrics']['tokens'] = 128
                        row['completion_reason'] = 'length'
                        row['native_decode_tokens_s'] = 128
                        row['metrics']['reusedPromptTokens'] = 0 if stage == 'warmup' else 204
                    obs['states']['asleep'] = copy.deepcopy(obs['states']['awake'])
        reports[kind] = seal(report, proof)
    return proof, reports


def test_small_gain_and_all_controls_qualify_but_never_approve_release():
    proof, reports = bundle()
    result = evaluate_bundle(proof, reports)
    assert result['passed'] and result['status'] == 'PASS_COMBINED_QUALIFICATION_NOT_RELEASE'
    assert not result['release_approved'] and len(result['remaining_release_reviews']) == 4


@pytest.mark.parametrize('missing', KINDS)
def test_missing_control_cannot_be_ignored(missing):
    proof, reports = bundle()
    del reports[missing]
    with pytest.raises(AssertionError):
        evaluate_bundle(proof, reports)


def test_positive_image_result_cannot_hide_text_regression():
    proof, reports = bundle()
    row = reports['text']['pairs'][0]['after']['states']['asleep']['sample']
    row['metrics']['decodeNs'] *= 1.1
    row['native_decode_tokens_s'] /= 1.1
    seal(reports['text'], proof)
    result = evaluate_bundle(proof, reports)
    assert result['workloads']['awake']['passed']
    assert not result['passed'] and not result['release_approved']


def test_mislabeled_or_reused_workload_is_not_a_complete_bundle():
    proof, reports = bundle()
    reports['asleep'] = reports['awake']
    with pytest.raises(AssertionError):
        evaluate_bundle(proof, reports)


def test_cannot_relabel_failed_control_as_passed():
    proof, reports = bundle()
    reports['cache']['result']['passed'] = False
    with pytest.raises(AssertionError):
        evaluate_bundle(proof, reports)


def test_optimized_python_refused():
    r = subprocess.run([sys.executable, '-O', '-c',
        "import sys;sys.path.insert(0,'ci');from evaluate_projector_combined_bundle import evaluate_bundle;evaluate_bundle({}, {})"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and 'Optimized Python' in r.stderr


def test_natural_eos_keeps_full_budget_and_identical_outputs():
    proof, reports = bundle()
    for pair in reports['text']['pairs']:
        for phase in pair.values():
            for state in phase['states'].values():
                for row in state.values():
                    row['tokens'] = row['metrics']['tokens'] = 103
                    row['native_decode_tokens_s'] = 103
                    row['completion_reason'] = 'eog'
    seal(reports['text'], proof)
    assert evaluate_bundle(proof, reports)['passed']
    row=reports['text']['pairs'][0]['after']['states']['awake']['sample']
    row['settings']['nPredict']=103
    with pytest.raises(AssertionError):
        evaluate_bundle(proof, reports)
