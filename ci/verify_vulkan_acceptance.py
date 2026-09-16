"""Exact signed Vulkan acceptance. Functional PASS is not a 5-second phone claim."""
import hashlib
import json
import statistics
from pathlib import Path
from verify_performance_candidate import verify as candidate
from verify_performance_acceptance import api


def verify():
    candidate()
    c=json.load(open('ci/vulkan-candidate.json'))
    p=json.load(open('ci/performance-candidate.json'))
    for key in ('apk_sha256','source_commit','signer_sha256','baseline_sha256','baseline_signer_sha256','build_run','build_job'):
        assert c[key]==p[key],key
    v=json.load(open('.delivery/vulkan-acceptance.json'))
    assert v['status']=='SIGNED_VULKAN_AWAKE_ASLEEP_FUNCTIONAL_PASS'
    assert v['apk_sha256']==c['apk_sha256']
    run=api('actions/runs/'+str(v['run']))
    assert run['status']=='completed' and run['conclusion']=='success'
    assert run['head_branch']=='arena/01a09b42-5' and run['head_sha']==v['commit']
    assert run['run_attempt']==v['attempt'] and run['path']=='.github/workflows/vulkan-speed.yml'
    jobs=api('actions/runs/'+str(v['run'])+'/jobs')['jobs']
    assert next(j for j in jobs if j['id']==v['job'])['conclusion']=='success'
    build=api('actions/runs/'+str(c['build_run']))
    assert build['head_sha']==c['source_commit']
    bj=next(j for j in api('actions/runs/'+str(c['build_run'])+'/jobs')['jobs'] if j['id']==c['build_job'])
    for name in ('Compile real native stack and compact UI','Existing regressions','Real APK serialization and GGUF reader through DEX to JVM','Relay unsigned build for private local signing'):
        assert next(x for x in bj['steps'] if x['name']==name)['conclusion']=='success',name
    root=Path(f"ci-results/{v['run']}-{v['attempt']}")
    s=json.load(open(root/'summary.json'))
    assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256'] and s['baseline_sha256']==c['baseline_sha256']
    for key in ('same_key_update_preserves_data','plain_original_view','android_image_decoder','identical_greedy_outputs_both_screen_states','actual_vulkan_sleep_notice_and_cleanup'):
        assert s['checks'][key]=='PASS',key
    assert c['signer_sha256']==c['baseline_signer_sha256']
    assert s['checks']['code_clipboard']==dict(stream='PASS',history='PASS')
    assert s['checks']['actual_visual_inference']['status']=='PASS'
    assert 'dog' in s['checks']['actual_visual_inference']['response'].lower()
    for screen in ('awake','asleep'):
        a,b=s['series']['before'][screen],s['series']['after'][screen]
        assert len(a)==len(b)==3
        for old,new in list(zip(a,b))+[(s['series']['before'][screen+'_follow'],s['series']['after'][screen+'_follow'])]:
            assert old['response']==new['response'] and old['tokens']==new['tokens']>0
            for x in (old,new):
                m=x['metrics']
                assert m['completed'] and m['version']==3 and m['timingScope']=='prefill_synchronized_before_decode'
                assert m['tokens']==x['tokens'] and m['decodeNs']>0 and m['firstTokenNs']>0
                if screen=='awake': assert x['send_to_first_ui_ns']>0
            assert new['backend_selected']>0 and 0<new['overlap_submissions']<new['tokens']
    if c.get('strict_tensor_routing'):
        assert s['checks']['strict_tensor_routing_both_screen_states_and_non_greedy']=='PASS'
        assert s['checks']['visual_strict_tensor_routing']['status']=='PASS'
        rows=[]
        for screen in ('awake','asleep'):
            rows.extend(s['series']['after'][screen])
            rows.append(s['series']['after'][screen+'_follow'])
        rows.append(s['series']['after']['non_greedy'])
        for row in rows:
            audit=row['strict_tensor_routing']
            assert audit['status']=='PASS' and audit['submitted_math_nodes']>0 and audit['submitted_graphs']>0
            assert audit['host_orchestration']=='CPU' and audit['physical_gpu_certified'] is False
    # Functional acceptance must not silently become a speed-improvement claim.
    computed = {screen: {phase: {
        'total_s': statistics.median(x['prefill_and_generation_seconds'] for x in s['series'][phase][screen]),
        'first_native_text_s': statistics.median(x['metrics']['firstTokenNs']/1e9 for x in s['series'][phase][screen]),
        'decode_tokens_s': statistics.median(x['native_decode_tokens_s'] for x in s['series'][phase][screen]),
    } for phase in ('before', 'after')} for screen in ('awake', 'asleep')}
    assert v['medians'] == s['medians'] == computed
    improved = all(computed[screen]['after']['total_s'] < computed[screen]['before']['total_s'] for screen in computed)
    assert v['both_screen_states_total_speed_improved'] is improved
    assert v['awake_send_to_first_ui_median_s'] == {
        phase: statistics.median(x['send_to_first_ui_ns']/1e9 for x in s['series'][phase]['awake'])
        for phase in ('before', 'after')}
    # UI seed is runtime-random; these are smoke checks, NEVER equal-seed proof.
    for phase in ('before','after'):
        x=s['series'][phase]['non_greedy']
        assert x['metrics']['completed'] and x['tokens']>0 and x['response'].strip()
    # The broad build found an incorrect vehicle answer. Do not ignore it:
    # require an independent SAME-byte before/after run for that exact case.
    vision=v['vision_comparison']
    vr=api('actions/runs/'+str(vision['run']))
    assert vr['status']=='completed' and vr['conclusion']=='success'
    assert vr['head_sha']==vision['commit'] and vr['run_attempt']==vision['attempt']
    assert vr['head_branch']=='arena/01a09b42-5' and vr['path']=='.github/workflows/vulkan-vision-compare.yml'
    vs=json.load(open(f"ci-results/{vision['run']}-{vision['attempt']}/summary.json"))
    assert vs['apk_sha256']==c['apk_sha256'] and vs['baseline_sha256']==c['baseline_sha256']
    assert vs['status']=='PASS_EQUALITY_ONLY' and vs['responses']['before']==vs['responses']['after']
    assert vs['semantic_vehicle']['before']==vs['semantic_vehicle']['after']
    if c.get('strict_tensor_routing'):
        assert vs['checks']['strict_visual_tensor_routing']['status']=='PASS'
        assert v['all_application_on_gpu'] is False
    assert v['physical_gpu_speed_certified'] is False and v['five_second_goal_certified'] is False
    assert len(v['ui_review'])>=3
    for image in v['ui_review']:
        q=Path(image['path'])
        assert q.parent==root and hashlib.sha256(q.read_bytes()).hexdigest()==image['sha256']
    print('SIGNED_VULKAN_AWAKE_ASLEEP_ACCEPTANCE_PASS')

if __name__=='__main__': verify()
