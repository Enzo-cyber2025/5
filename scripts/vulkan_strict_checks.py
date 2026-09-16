"""Audit exact native strict-routing reports. Does not certify physical hardware."""
import re


def strict_audit(log):
    assert 'GGUF_STRICT_VULKAN_BLOCKED' not in log, 'Native dispatcher blocked a non-Vulkan tensor operation'
    matches = re.findall(r'GGUF_STRICT_VULKAN_RESULT enabled=1 submitted_graphs=(\d+) submitted_math_nodes=(\d+) blocked=0 host_orchestration=CPU', log)
    assert len(matches) == 1, 'Expected exactly one successful strict native routing report'
    graphs, nodes = map(int, matches[0])
    assert graphs > 0 and nodes > 0
    sampled = re.search(r'GGUF_GPU_SAMPLING_RESULT backend_selected=(\d+) emitted=(\d+)', log)
    assert sampled and int(sampled[1]) >= int(sampled[2]) > 0
    assert 'GGUF_NATIVE_COMPLETE' in log
    return dict(status='PASS', submitted_graphs=graphs, submitted_math_nodes=nodes,
                tensor_cpu_fallback='blocked_by_native_policy', host_orchestration='CPU',
                physical_gpu_certified=False)
