"""Real Android UI/clipboard tests of the renderer loaded from installed APK.
Fixture data is never presented as a model-generated response.
"""
import json,xml.etree.ElementTree as ET
from pathlib import Path
from android_checks import position
PKG='com.ggufchat.codetest'
def run(d):
    d.adb('install','-r','.cache/code-test/test.apk')
    results={}
    for mode in ('stream','history'):
        d.shell('am force-stop '+PKG)
        started=d.shell('am start -W -n '+PKG+'/.CodeActivity --es mode '+mode)
        Path('evidence/physical-code-'+mode+'-start.txt').write_text(started)
        assert 'Status: ok' in started,started
        d.wait(lambda:position(d.ui(),text='Streaming pronto' if mode=='stream' else 'Histórico pronto',package={PKG}),'production renderer '+mode)
        for index,label in enumerate(('Python','JSON')):
            def copies():
                nodes=[n for n in ET.fromstring(d.ui()).iter('node') if n.get('content-desc')=='Copiar código']
                return nodes if len(nodes)==2 else None
            nodes=d.wait(copies,'two real copy buttons')
            import re
            x1,y1,x2,y2=map(int,re.findall(r'\d+',nodes[index].get('bounds')))
            d.shell(f'input tap {(x1+x2)//2} {(y1+y2)//2}')
            d.tap(text='Conferir '+label,package={PKG})
            d.wait(lambda:position(d.ui(),text='Cópia '+label+' OK',package={PKG}),'exact clipboard whitespace/unicode/'+label)
        d.capture('physical-code-'+mode+'.png');results[mode]='PASS'
    Path('evidence/physical-code-ui.json').write_text(json.dumps(dict(status='PASS',checks=results,scope='Actual Android production DEX renderer with explicit synthetic UI fixtures; not a model inference test.'),indent=2))
    d.shell('am force-stop '+PKG)
    return results
