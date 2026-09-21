"""The host-side llvmpipe lab must stay a lab: fast iteration, zero release power."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT/'.github/workflows/llvmpipe-lab.yml'
SCRIPT = ROOT/'ci/llvmpipe_lab.sh'
PATCHER = ROOT/'ci/llvmpipe_lab_patches.py'
ACCUM = ROOT/'ci/dmmv_accum_lab_patches.py'
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'


def test_workflow_is_marked_as_lab_and_needs_the_marker():
    text = WORKFLOW.read_text()
    assert 'not acceptance' in text
    assert "contains(github.event.head_commit.message, '[lab]')" in text
    assert 'llvmpipe-lab-' in text
    # Same disposable runner rules as the emulator workflows.
    assert 'runs-on: ubuntu-latest' in text
    for tool in ('glslc', 'glslang-tools', 'libvulkan-dev', 'mesa-vulkan-drivers'):
        assert tool in text, tool


def test_patch_set_travels_in_the_commit_message_and_is_charset_checked():
    text = WORKFLOW.read_text()
    assert "s/.*\\[lab:\\([^]]*\\)\\].*/\\1/p" in text
    assert "case \"$list\" in" in text and '*[!A-Za-z0-9_,]*)' in text
    # The commit message must never be interpolated directly into the shell script.
    assert 'MSG: ${{ github.event.head_commit.message }}' in text
    assert '${{ github.event.head_commit.message }}' not in text.split('env:')[0]


def test_lab_never_touches_the_release_path_or_publishes_an_apk():
    text = SCRIPT.read_text()
    assert 'apk-fix/build_mobile.py' not in text
    assert 'apksigner' not in text and 'entrega/' not in text
    assert 'delivery' not in text
    # Bounded evidence, inside the publisher allow-list and the 2 MB cap.
    assert 'evidence/physical-llvmpipe-lab.txt' in text
    assert 'evidence/physical-llvmpipe-lab-profile.txt' in text
    # The lab is a comparison: patched build against a pristine checkout of the same pin.
    assert 'llama-host-ctrl' in text
    assert 'generate_fixture' in text
    assert 'greedy text identical' in text


def test_patcher_only_uses_allow_listed_modules_and_records_the_pin():
    text = PATCHER.read_text()
    assert "for directory in ('ci', 'apk-fix')" in text
    assert 'worktree_diff_sha256' in text
    assert PIN in text
    assert 'rev-parse' in text


def test_accum_patch_cannot_reach_a_release_build():
    for name in ('apk-fix/build_mobile.py', 'ci/mobile-models.sh'):
        assert 'dmmv_accum' not in (ROOT/name).read_text(), name
    for workflow in (ROOT/'.github/workflows').glob('*.yml'):
        if workflow.name in ('llvmpipe-lab.yml',):
            continue
        assert 'dmmv_accum' not in workflow.read_text(), workflow.name


def test_accum_patch_matches_the_pinned_shader_and_stays_in_the_lab_tree():
    source = ROOT/'.cache/llama-mobile'
    if not source.exists():
        pytest.skip('Pinned upstream absent')
    sys.path.insert(0, str(ROOT/'ci'))
    import dmmv_accum_lab_patches as accum
    original = (source/accum.TARGET).read_text()
    patched = accum.patch_shader(original)
    assert patched != original
    assert patched.count('gguf_acc0') == original.count('gguf_acc0') + 5
    # The horizontal dot() of the hot loop is gone; the k-4 path is untouched.
    assert 'rowtmp += dot(bv1, v2);' in original and 'rowtmp += dot(bv1, v2);' not in patched
    assert patched.count('temp[j][n] += dot(v, b);') == original.count('temp[j][n] += dot(v, b);')
    # Same scale policy: the per-block scale is applied exactly where it was.
    assert '(v * dm.x) * bv0' in patched
    # Reduction mode and workgroup constants are not touched by this patch.
    for key in ('reduce_result(temp, d_offset, first_row, num_rows, tid)',
                'layout(local_size_x_id = 0, local_size_y = 1, local_size_z = 1) in;'):
        assert patched.count(key) == original.count(key) == 1
    for guard in ('int ', 'uint ', 'float ', 'mediump', 'relaxed'):
        assert f'precision {guard}' not in patched


def test_accum_patch_refuses_to_apply_twice(tmp_path):
    source = ROOT/'.cache/llama-mobile'
    if not source.exists():
        pytest.skip('Pinned upstream absent')
    sys.path.insert(0, str(ROOT/'ci'))
    import dmmv_accum_lab_patches as accum
    target = tmp_path/accum.TARGET
    target.parent.mkdir(parents=True)
    target.write_text((source/accum.TARGET).read_text())
    accum.apply(tmp_path)
    assert 'gguf_acc0' in target.read_text()
    with pytest.raises(AssertionError, match='already applied'):
        accum.apply(tmp_path)


def test_device_probe_reports_the_subgroup_shape_that_decides_reduction_cost():
    text = (ROOT/'ci/vulkan_features.cpp').read_text()
    for field in ('subgroupSize', 'subgroupSupportedOperations', 'subgroupArithmetic',
                  'computeFullSubgroups', 'minSubgroupSize', 'maxSubgroupSize',
                  'shaderFloat16', 'shaderIntegerDotProduct',
                  'maxComputeWorkGroupInvocations', 'timestampPeriod'):
        assert field in text, field
    # The mandatory compute prerequisite and the exit contract of prepare_vulkan.sh stay.
    assert 'storageBuffer16BitAccess = %s' in text
    assert 'return storage.storageBuffer16BitAccess?0:1;' in text
    lab = (ROOT/'ci/llvmpipe_lab.sh').read_text()
    assert 'evidence/physical-llvmpipe-features.txt' in lab


def test_ceiling_probe_covers_the_patterns_that_separate_the_hypotheses():
    text = (ROOT/'ci/lab_compute/ceiling.comp').read_text()
    for pattern in range(18):
        assert f'#elif PATTERN == {pattern}' in text or f'#if PATTERN == {pattern}' in text, pattern
    # 7/9 carry four independent accumulators, 8 is the load-only shape.
    assert 'float a0 = 0.0, a1 = 0.0, a2 = 0.0, a3 = 0.0;' in text
    assert '(a0 + a1) + (a2 + a3)' in text
    # Barrier and shared-memory cost must be measurable, not assumed.
    assert text.count('barrier();') >= 3
    assert 'shared float smem[BLOCK_SIZE];' in text
    runner = (ROOT/'ci/lab_compute/ceiling.cpp').read_text()
    assert '--macs' in runner and 'gpairs_per_s' in runner
    assert 'vkCmdDispatch' in runner and 'pSpecializationInfo' in runner
