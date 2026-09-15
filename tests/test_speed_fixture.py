"""Observer-only tests; these are NOT Android or inference acceptance."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_generation_stats_android import footer,stamp

class FooterSnapshot:
    def __init__(self,rate='12.5',top=240):
        self.xml=f'''<hierarchy><node text="Actual answer" bounds="[10,100][600,240]"/>
        <node text="{rate} tokens/s · 25 tokens" content-desc="Velocidade da resposta" bounds="[10,{top}][600,270]"/></hierarchy>'''
        self.captured=[]
    def ui(self):return self.xml
    def wait(self,fn,description):return fn()
    def capture(self,name):self.captured.append(name)

def test_footer_reads_real_xml_attribute_and_accepts_decimal_comma():
    d=FooterSnapshot('12,5')
    footer(d,dict(response='Actual answer',native_decode_tokens_s=12.5),'observer')
    assert d.captured==['physical-speed-observer.png']

@pytest.mark.parametrize('rate,top',[('25.0',240),('12.5',230)])
def test_footer_rejects_wrong_rate_or_inside_bubble(rate,top):
    with pytest.raises(AssertionError):
        footer(FooterSnapshot(rate,top),dict(response='Actual answer',native_decode_tokens_s=12.5),'observer')

def test_timestamp_requires_actual_native_marker():
    log='09-15 16:55:12.345  111  112 I GGUF: GGUF_NATIVE_COMPLETE tokens=128'
    assert stamp(log,'GGUF_NATIVE_COMPLETE')==16*3600+55*60+12.345
    with pytest.raises(AssertionError):stamp(log,'GGUF_CONTENT_PREPARED')
