"""Separate requested +150% speed gate from functional Vulkan acceptance.
Exit 1 means the performance request has NOT been satisfied. Never relabel it PASS.
This checks software-Vulkan observations only, not physical-GPU certification.
"""
import json
from pathlib import Path


def result(acceptance):
    root=Path(f"ci-results/{acceptance['run']}-{acceptance['attempt']}")
    s=json.loads((root/'summary.json').read_text())
    assert s['status']=='PASS' and s['apk_sha256']==acceptance['apk_sha256']
    assert acceptance['target_throughput_multiplier']==2.5
    ratios={screen:s['medians'][screen]['after']['decode_tokens_s']/s['medians'][screen]['before']['decode_tokens_s'] for screen in ('awake','asleep')}
    return all(x>=2.5 for x in ratios.values()),ratios


if __name__=='__main__':
    from verify_vulkan_acceptance import verify
    verify()
    a=json.loads(Path('.delivery/vulkan-acceptance.json').read_text())
    passed,ratios=result(a)
    print(json.dumps(dict(status='TARGET_OBSERVED_SOFTWARE_ONLY' if passed else 'TARGET_150_PERCENT_NOT_MET',required_multiplier=2.5,observed_multipliers=ratios,physical_gpu_certified=False),indent=2))
    raise SystemExit(0 if passed else 1)
