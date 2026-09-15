"""Fail closed: a benchmark, native provenance and reviewed UI precede approval."""
import hashlib,json,math,re,statistics,subprocess,sys,zipfile
from pathlib import Path

def api(path):
    return json.loads(subprocess.check_output(['gh','api','repos/Enzo-cyber2025/5/'+path],text=True))

def verify():
    c=json.load(open('ci/latency-candidate.json'));v=json.load(open('.delivery/latency-acceptance.json'))
    m=json.load(open('.delivery/mobile-signed.json'));u=json.load(open('.delivery/mobile-build.json'))
    assert v['status']=='SIGNED_LATENCY_ANDROID_PASS'
    assert c['apk_sha256']==v['apk_sha256']==m['apk_sha256']==hashlib.sha256(Path('.delivery/GGUF-Chat-mobile.apk').read_bytes()).hexdigest()
    assert c['source_commit']==m['source_commit']==u['source_commit']==u['native_source_commit']
    assert c['signer_sha256']==m['signer_sha256']=='3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da'
    assert m['unsigned_sha256']==u['sha256']==hashlib.sha256(Path('.delivery/GGUF-Chat-mobile-unsigned.apk').read_bytes()).hexdigest()
    with zipfile.ZipFile('.delivery/GGUF-Chat-mobile.apk') as a,zipfile.ZipFile('.delivery/GGUF-Chat-mobile-unsigned.apk') as b:
        assert a.namelist()==b.namelist()
        for name in a.namelist():assert a.read(name)==b.read(name)
        for name,digest in u['native'].items():assert hashlib.sha256(a.read(name)).hexdigest()==digest
    run=api('actions/runs/'+str(v['run']))
    assert run['status']=='completed' and run['conclusion']=='success' and run['run_attempt']==v['attempt']
    assert run['head_sha']==v['commit'] and run['head_branch']=='arena/01a09b42-5' and run['path']=='.github/workflows/latency-android.yml'
    jobs=api('actions/runs/'+str(v['run'])+'/jobs')['jobs']
    assert next(j for j in jobs if j['id']==v['job'])['conclusion']=='success'
    root=Path(f"ci-results/{v['run']}-{v['attempt']}");s=json.load(open(root/'summary.json'))
    assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
    for check in ('same_key_update_preserves_data','prefix_reuse_system_edit_restart_and_footer','identical_outputs_with_real_prefix_reuse','cancel_invalidates_partial_cache','real_image_no_text_cache_screen_off_and_lease_release','same_image_embeddings_reused_and_changed_images_reencoded'):
        assert s['checks'][check]=='PASS',check
    b=s['benchmark'];assert b['repetitions']==3 and b['warmup_pairs_excluded']==1
    for phase in ('before','after'):
        assert len(b['series'][phase])==3
        for kind in ('cold','follow'):
            values=[r[kind]['metrics']['prefillNs']/1e6 for r in b['series'][phase]]
            assert math.isclose(statistics.median(values),b[kind][phase]['prefill_ms'])
    for x,y in zip(b['series']['before'],b['series']['after']):
        for kind in ('cold','follow'):assert x[kind]['response']==y[kind]['response']
        assert y['cold']['metrics']['reusedPromptTokens']==0
        assert y['follow']['metrics']['reusedPromptTokens']>=y['cold']['metrics']['promptTokens']-8
    assert b['follow']['after']['prefill_ms']<b['follow']['before']['prefill_ms'],'Do not approve increased follow-up latency as an improvement'
    sys.path.insert(0,'scripts')
    from android_checks import active_wake_locks,completed_after_actual_sleep
    power=(root/'physical-latency-asleep-power.txt').read_text()
    assert 'Wake Locks: size=' in power and 'mWakefulness=Asleep' in power and 'GGUFChat:LocalCompute' not in active_wake_locks(power)
    assert completed_after_actual_sleep((root/'physical-latency-sleep-log.txt').read_text())
    for name,expected_hit in [('fill',False),('hit',True),('changed',False)]:
        log=(root/f'physical-latency-image-cache-{name}-log.txt').read_text()
        hit=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',log);assert hit
        h,miss,size=map(int,hit.groups());assert 0<size<=16*1024*1024
        assert (h>0 and miss==0) if expected_hit else (h==0 and miss>0)
    build=api('actions/runs/'+str(c['build_run']))
    assert build['conclusion']=='success' and build['head_sha']==c['source_commit']
    review=v['ui_review'];assert review['status']=='PASS' and review['apk_sha256']==c['apk_sha256'] and len(review['images'])>=3
    for item in review['images']:
        p=Path(item['path']);assert p.parent==root and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
    print('SIGNED_LATENCY_ACCEPTANCE_GATES_PASS')

if __name__=='__main__':verify()
