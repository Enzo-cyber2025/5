"""App-specific patch against pinned llama.cpp, not a generic API behaviour change.
Our sampler chains terminate in greedy/dist and consume only the selected token.
Keep full auxiliary outputs whenever the backend has NOT selected a token.
"""
MARKER = '// GGUF_TOKEN_ONLY_SAMPLING: no unused vocabulary-sized host readback.'


def patch_token_readback(source):
    if MARKER in source:
        return source
    anchor = '            sampler->iface->backend_apply(sampler, ctx0, gf, &data);'
    assert source.count(anchor) == 1, 'Pinned sampling graph layout changed'
    return source.replace(anchor, anchor + '''

#ifdef GGUF_TOKEN_ONLY_SAMPLING
            // GGUF_TOKEN_ONLY_SAMPLING: no unused vocabulary-sized host readback.
            // The selected-token graph still depends on ALL logits/probabilities.
            // Remove only exported descriptors, never tensors or sampler stages.
            // CPU/partial-backend sampling still needs these arrays: keep them.
            if (data.sampled != nullptr) {
                data.logits = nullptr;
                data.probs = nullptr;
                data.candidates = nullptr;
            }
#endif''')
