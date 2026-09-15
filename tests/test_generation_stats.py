from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]

def test_native_rate_uses_actual_sampler_count_and_monotonic_decode_interval():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'std::chrono::steady_clock' in s and 'decode_started=Clock::now();decoding=true' in s
    assert s.index('if(llama_vocab_is_eog(vocab,t))') < s.index('emitted++;pending+=piece(vocab,t)')
    assert 'finished-decode_started' in s and 'GGUF_GENERATION_STATS' in s
    assert 'if(i+1<limit && llama_decode' in s
    assert 'std::chrono::milliseconds(50)' in s and 'pending.size()>=4096' in s
    assert 'if(emitted==1' in s and '\n        flush();' in s

def test_metric_is_per_message_and_footer_outside_bubble():
    p=(ROOT/'apk-fix/generation_stats.py').read_text()
    assert 'Message.smali' in p and 'generationMetrics' in p and '->attach' in p
    assert 'renderedMessage' in p and '->caption' in p
    assert 'const/4 v0, 0x0' in p
    s=(ROOT/'apk-fix/java/com/ggufchat/app/GenerationStats.java').read_text()
    assert 'ThreadLocal<String>' in s and 'RESULT.remove();NOTICE.remove()' in s
    assert 'tokens*1e9/(double)ns' in s and 'sem medição' in s
    assert '1000000000L' in s and 'Math.min(80,text.length())' in s
    assert 'column.addView(view)' in s and 'tokens/s' in s
