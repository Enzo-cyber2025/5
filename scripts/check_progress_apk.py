#!/usr/bin/env python3
"""Run measured counters from the actual APK translated to JVM, not javac substitutes.
Run scripts/test_host.sh on the candidate first. This is not Android/native inference.
"""
import hashlib,json,sys
from pathlib import Path
import jpype,jdk4py
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_physical_gguf import fixture,read_tensors
candidate=json.loads((ROOT/'ci/progress-candidate.json').read_text())
apk=ROOT/'.delivery/GGUF-Chat-mobile.apk'
assert hashlib.sha256(apk.read_bytes()).hexdigest()==candidate['apk_sha256']
jpype.startJVM(str(jdk4py.JAVA_HOME/'lib/server/libjvm.so'),classpath=[str(ROOT/'.cache/host-tests/application.jar')],convertStrings=True)
Meter=jpype.JClass('com.ggufchat.app.ProgressMeter');G=jpype.JClass('com.ggufchat.app.GgufFile');File=jpype.JClass('java.io.File')
for done,total,complete,wanted in [(50,100,False,50),(100,100,False,99),(123,-1,False,-1),(0,0,False,-1),(200,100,False,-1),(2**63-1,2**63-1,False,99),(123,123,True,100)]:
    assert Meter.percent(done,total,complete)==wanted
work=ROOT/'.cache/progress-apk-checks';work.mkdir(exist_ok=True)
a,b,out=[work/n for n in ('language.gguf','vision.gguf','unified.gguf')]
expected=fixture(a);expected.update(fixture(b,'projector',64));out.unlink(missing_ok=True)
originals=[a.read_bytes(),b.read_bytes()];events=[]
def update(stage,done,total,complete):events.append(dict(stage=str(stage),done=int(done),total=int(total),complete=bool(complete),percent=int(Meter.percent(done,total,complete))))
callback=jpype.JProxy('com.ggufchat.app.GgufFile$Progress',dict(update=update))
G.read(File(str(a)),callback)
assert events[-1]['stage']=='identify' and events[-1]['complete'] and events[-1]['percent']==100
assert any(0<e['percent']<99 for e in events)
identification=events[:];events.clear()
g=G.merge(File(str(a)),File(str(b)),File(str(out)),callback)
assert str(g.capability())=='VISION_SINGLE_GGUF' and read_tensors(out)==expected
assert [a.read_bytes(),b.read_bytes()]==originals
for stage in ('merge','verify'):
    rows=[e for e in events if e['stage']==stage]
    assert rows[-1]['complete'] and rows[-1]['done']==rows[-1]['total']==sum(map(len,expected.values()))
    assert [e['done'] for e in rows]==sorted(e['done'] for e in rows)
    assert all(e['percent']<100 for e in rows if not e['complete'])
merged_events=events[:];events.clear()
with out.open('r+b') as f:f.seek(int(g.dataOffset));f.write(b'\xff')
try:G.verifyPayload(G.read(File(str(a))),G.read(File(str(b))),g,callback)
except jpype.JException as error:assert 'bytes alterados' in str(error)
else:raise AssertionError('Corrupted payload accepted')
assert not any(e['complete'] or e['percent']==100 for e in events)
proof=dict(status='PASS',apk_sha256=candidate['apk_sha256'],source_commit=candidate['source_commit'],scope='actual APK classes via Enjarify/JVM; not Android or native inference',checks=['unknown and overflow-safe percentage arithmetic','active capped at 99; explicit completion 100','measured identification units','measured merge and byte-comparison totals','source and tensor byte preservation','corruption rejected without completed verification'],identification=identification,merge_and_verify=merged_events,corruption_events=events)
(ROOT/'.delivery/progress-local-validation.json').write_text(json.dumps(proof,indent=2))
print('ACTUAL_APK_PROGRESS_COUNTERS_AND_CORRUPTION_PASS')
