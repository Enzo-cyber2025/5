from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_zero_selects_model_context_and_remaining_context_output_not_infinity():
    build = (ROOT / "apk-fix/build_mobile.py").read_text()
    native = (ROOT / "apk-fix/native/mobile.cpp").read_text()
    assert "const/4 v2, 0x0" in build[build.index(".method public static contextSize("):build.index(".method public static nPredict(")]
    assert "const/4 v2, 0x0" in build[build.index(".method public static nPredict("):build.index("p.write_text(s)", build.index(".method public static nPredict("))]
    assert "if(context<0 || (context!=0 && context<256) || context>8192)" in native
    assert "cp.n_ctx=context" in native
    assert "if(!callback || predict<0)" in native
    assert "predict<=0?available" in native
    assert "GGUF_OUTPUT_BUDGET requested=%d effective=%zu available_context=%zu" in native
    assert "not an infinite KV cache" in native
    assert "not infinite generation" in native
    integration = (ROOT / "scripts/test_tool_integrations_android.py").read_text()
    assert "GGUF_PROMPT_CACHE input_tokens=" in integration
    assert "model_context = int(prompt.group(1)) + int(budget.group(2))" in integration
    assert "available_context" in integration
