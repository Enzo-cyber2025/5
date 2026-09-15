"""Observe actual counters and UI during real SAF imports. No injected progress."""
import json,re
from pathlib import Path
import xml.etree.ElementTree as ET

PATTERN=re.compile(r'GGUF_IMPORT_PROGRESS stage=(\w+) percent=(-?\d+) done=(\d+) total=(-?\d+) complete=(true|false)')

class ProgressObserver:
    def __init__(self,d,label):
        self.d=d;self.label=label;self.events=[];self.captured=set();self.finished=False
        self.d.adb('logcat','-c')

    def poll(self):
        log=self.d.adb('logcat','-d','-s','GGUFProgress:I','*:S')
        self.events=[dict(stage=s,percent=int(p),done=int(n),total=int(t),complete=c=='true') for s,p,n,t,c in PATTERN.findall(log)]
        self.finished='GGUF_IMPORT_PROGRESS_FINISHED success=true' in log
        (self.d.evidence/f'physical-progress-{self.label}-log.txt').write_text(log)
        if self.events and not self.finished:
            stage=self.events[-1]['stage']
            if stage not in self.captured:
                xml=self.d.ui();text='\n'.join(n.get('text','') for n in ET.fromstring(xml).iter('node'))
                if 'Importação 1' in text and '%' in text:
                    self.d.capture(f'physical-progress-{self.label}-{stage}.png')
                    (self.d.evidence/f'physical-progress-{self.label}-{stage}.json').write_text(json.dumps({'latest_logged_stage':stage,'visible_text':text},ensure_ascii=False,indent=2))
                    self.captured.add(stage)
        return self.finished

    def finish(self,source_sizes,vision=False,pair=False):
        self.d.wait(self.poll,'progresso concluído após persistência: '+self.label,timeout=30)
        required=['copy0','identify0','save']
        if pair:required+=['copy1','identify1','merge','verify']
        if pair or vision:required+=['native']
        for stage in required:
            rows=[e for e in self.events if e['stage']==stage]
            assert rows and rows[-1]['complete'] and rows[-1]['percent']==100,(stage,rows)
            known=[e for e in rows if e['percent']>=0]
            for e in known:
                assert e['percent']==100 if e['complete'] else e['percent']<=99,e
                if not e['complete']:
                    assert e['total']>0 and e['percent']==min(99,int(100.0*(e['done']/e['total']))),e
            percents=[e['percent'] for e in known]
            assert percents==sorted(percents),(stage,percents)
        for i,size in enumerate(source_sizes):
            rows=[e for e in self.events if e['stage']=='copy'+str(i)]
            assert rows[-1]['done']==rows[-1]['total']==size
            assert any(0<e['percent']<99 for e in rows),'No measured intermediate copy progress'
        if pair:
            for stage in ('merge','verify','identify0','identify1'):
                assert any(0<e['percent']<99 for e in self.events if e['stage']==stage),stage
            assert self.captured,'No real progress UI screenshot captured'
        if pair or vision:assert any(e['stage']=='native' and e['percent']==-1 and not e['complete'] for e in self.events)
        proof={'status':'PASS','label':self.label,'source_sizes':source_sizes,'stages':required,'captured_stages':sorted(self.captured),'events':self.events,'scope':'actual APK counters plus genuine Android UI; no timed or injected percentages'}
        (self.d.evidence/f'physical-progress-{self.label}-proof.json').write_text(json.dumps(proof,indent=2))
        return 'PASS'
