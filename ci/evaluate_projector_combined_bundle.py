#!/usr/bin/env python3
"""Join all five reports; a fast image result cannot hide a failed control.

This qualifies an experiment only. It does not approve a generally enabled APK,
or compare the experimental APK's stock mode to the previously delivered APK.
"""
import argparse
import json
from pathlib import Path
from evaluate_projector_combined import evaluate, canonical_sha

KINDS = ('awake', 'asleep', 'text', 'cache')


def evaluate_bundle(proof, reports):
    if not __debug__:
        raise RuntimeError('Optimized Python cannot validate evidence')
    assert set(reports) == set(KINDS), 'All four performance/control reports are required'
    reference = evaluate(proof)
    assert proof['kind'] == 'verify'
    assert proof['status'] == reference['status'] and proof['result'] == reference
    results = {}
    for kind in KINDS:
        report = reports[kind]
        assert report['kind'] == kind, 'Report substituted for another workload'
        result = evaluate(report, proof)
        assert report['result'] == result and report['status'] == result['status']
        results[kind] = result
    passed = all(r['passed'] for r in results.values())
    return dict(
        status='PASS_COMBINED_QUALIFICATION_NOT_RELEASE' if passed else 'COMBINED_QUALIFICATION_NOT_MET',
        passed=passed,
        build=proof['build'],
        byte_reference_sha256=canonical_sha(proof),
        workload_report_sha256={k: canonical_sha(reports[k]) for k in KINDS},
        workloads=results,
        release_approved=False,
        remaining_release_reviews=[
            'Safe eligibility: unsupported projectors and explicit CPU mode must retain their original working path.',
            'Memory and cold-use cost: reported PSS is not peak/total GPU memory; duplicated QKV weights are not free.',
            'Final production configuration versus the actual delivered APK: same experimental APK flags alone do not prove that comparison.',
            'Signing continuity: do not silently replace the unavailable release private key or require data loss.',
        ],
        scope='Observed consistency on the pinned software-Vulkan fixture, not physical-device or all-model certification.',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof', required=True, type=Path)
    for kind in KINDS:
        parser.add_argument('--' + kind, required=True, type=Path)
    args = parser.parse_args()
    result = evaluate_bundle(json.loads(args.proof.read_text()), {
        k: json.loads(getattr(args, k).read_text()) for k in KINDS
    })
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
