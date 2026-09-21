"""Synthetic negative/positive verifier tests, never Android acceptance evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'ci'))
    spec = importlib.util.spec_from_file_location('performance_gate', ROOT / 'ci/verify_performance_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, 'candidate', lambda: None)  # payload verifier tested independently
    c = dict(apk_sha256='synthetic-apk', source_commit='synthetic-source',
             signer_sha256='new', baseline_signer_sha256='old', build_run=1, build_job=10)
    v = dict(status='SIGNED_PERFORMANCE_CODE_IMAGES_ANDROID_PASS', apk_sha256=c['apk_sha256'],
             run=2, commit='synthetic-test', attempt=1, job=20,
             phone_15_20_tokens_s_certified=False, ui_review=[])
    evidence = tmp_path / 'ci-results/2-1'
    evidence.mkdir(parents=True)
    for n in range(3):
        p = evidence / f'synthetic-{n}.png'
        p.write_bytes(b'Synthetic verifier fixture, not a screenshot')
        v['ui_review'].append(dict(path=str(p.relative_to(tmp_path)), sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    m = dict(completed=True, tokens=128, version=3, timingScope='prefill_synchronized_before_decode')
    response = dict(response='Synthetic equal output', metrics=m)
    phase = dict(gpu=response, manual=response)
    for screen in ('awake', 'asleep'):
        phase[screen] = [copy.deepcopy(dict(cold=response, follow=response)) for _ in range(3)]
    checks = dict.fromkeys(('identical_model_outputs_auto_manual_cpu_and_vulkan',
                           'actual_sleep_saved_notifications_and_service_cleanup',
                           'automatic_threads_and_manual_override', 'real_send_to_first_ui_timing',
                           'actual_android_image_decoder', 'different_key_refused_without_deleting_data'), 'PASS')
    checks.update(code_boxes_exact_android_clipboard=dict(stream='PASS', history='PASS'),
                  real_image_missing_metadata=dict(status='PASS', response='Synthetic dog response'))
    s = dict(status='PASS', apk_sha256=c['apk_sha256'], checks=checks,
             series=dict(before=copy.deepcopy(phase), after=copy.deepcopy(phase)))
    routes = {
        'actions/runs/2': dict(status='completed', conclusion='success', head_sha=v['commit'],
                              head_branch='arena/01a09b42-5', path='.github/workflows/performance-code.yml', run_attempt=1),
        'actions/runs/2/jobs': dict(jobs=[dict(id=20, conclusion='success')]),
        'actions/runs/1': dict(head_sha=c['source_commit']),
        'actions/runs/1/jobs': dict(jobs=[dict(id=10, steps=[dict(name=name, conclusion='success') for name in (
            'Compile real native stack and compact UI', 'Existing regressions',
            'Real APK serialization and GGUF reader through DEX to JVM',
            'Relay unsigned build for private local signing')])]),
    }
    monkeypatch.setattr(module, 'api', lambda path: routes[path])
    def run():
        for path, value in (('ci/performance-candidate.json', c), ('.delivery/performance-acceptance.json', v),
                            ('ci-results/2-1/summary.json', s)):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(value))
        module.verify()
    return run, s, v, routes


def test_synthetic_complete_schema(gate):
    gate[0]()


@pytest.mark.parametrize('fault', ['failed-run', 'wrong-apk', 'failed-compile', 'changed-output',
                                  'old-counter', 'changed-manual', 'gpu-counter', 'phone-claim',
                                  'clipboard', 'image', 'screenshot', 'short-series'])
def test_reject_incomplete_or_mismatched_evidence(gate, fault):
    run, s, v, routes = gate
    if fault == 'failed-run': routes['actions/runs/2']['conclusion'] = 'failure'
    if fault == 'wrong-apk': s['apk_sha256'] = 'wrong'
    if fault == 'failed-compile': routes['actions/runs/1/jobs']['jobs'][0]['steps'][0]['conclusion'] = 'failure'
    if fault == 'changed-output': s['series']['after']['awake'][0]['cold']['response'] = 'Different'
    if fault == 'old-counter': s['series']['after']['asleep'][0]['follow']['metrics']['version'] = 2
    if fault == 'changed-manual': s['series']['after']['manual']['response'] = 'Different'
    if fault == 'gpu-counter': s['series']['after']['gpu']['metrics']['version'] = 2
    if fault == 'phone-claim': v['phone_15_20_tokens_s_certified'] = True
    if fault == 'clipboard': s['checks']['code_boxes_exact_android_clipboard']['stream'] = 'FAIL'
    if fault == 'image': s['checks']['real_image_missing_metadata']['status'] = 'FAIL'
    if fault == 'screenshot': v['ui_review'][0]['sha256'] = 'tampered'
    if fault == 'short-series': s['series']['after']['awake'].pop()
    with pytest.raises(AssertionError): run()
