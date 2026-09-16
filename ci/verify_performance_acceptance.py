"""Approve only exact signed real-Android CPU/GPU/code/image evidence, never phone T/S."""
import hashlib,json,subprocess
from pathlib import Path
from verify_performance_candidate import verify as candidate

def api(path):return json.loads(subprocess.check_output(['gh','api','repos/Enzo-cyber2025/5/'+path],text=True))
def verify():
 candidate();c=json.load(open('ci/performance-candidate.json'));v=json.load(open('.delivery/performance-acceptance.json'))
 assert v['status']=='SIGNED_PERFORMANCE_CODE_IMAGES_ANDROID_PASS' and v['apk_sha256']==c['apk_sha256']
 run=api('actions/runs/'+str(v['run']))
 assert run['status']=='completed' and run['conclusion']=='success' and run['head_sha']==v['commit']
 assert run['head_branch']=='arena/01a09b42-5' and run['path']=='.github/workflows/performance-code.yml' and run['run_attempt']==v['attempt']
 jobs=api('actions/runs/'+str(v['run'])+'/jobs')['jobs']
 assert next(j for j in jobs if j['id']==v['job'])['conclusion']=='success'
 build=api('actions/runs/'+str(c['build_run']));assert build['head_sha']==c['source_commit']
 job=next(j for j in api('actions/runs/'+str(c['build_run'])+'/jobs')['jobs'] if j['id']==c['build_job'])
 # The build workflow also ran an older SAF test which failed before inference.
 # Do not pretend that whole run was green; require its actual compile gates and
 # the new exact-signed Android acceptance, including real SAF/vision inference.
 for name in ('Compile real native stack and compact UI','Existing regressions','Real APK serialization and GGUF reader through DEX to JVM','Relay unsigned build for private local signing'):
  assert next(s for s in job['steps'] if s['name']==name)['conclusion']=='success',name
 root=Path(f"ci-results/{v['run']}-{v['attempt']}");s=json.load(open(root/'summary.json'))
 assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
 for key in ('identical_model_outputs_auto_manual_cpu_and_vulkan','actual_sleep_saved_notifications_and_service_cleanup','automatic_threads_and_manual_override','real_send_to_first_ui_timing','actual_android_image_decoder'):
  assert s['checks'][key]=='PASS',key
 assert s['checks']['code_boxes_exact_android_clipboard']=={'stream':'PASS','history':'PASS'}
 assert s['checks']['real_image_missing_metadata']['status']=='PASS'
 assert 'dog' in s['checks']['real_image_missing_metadata']['response'].lower()
 if c['signer_sha256']!=c['baseline_signer_sha256']:
  assert s['checks']['different_key_refused_without_deleting_data']=='PASS'
 for screen in ('awake','asleep'):
  a,b=s['series']['before'][screen],s['series']['after'][screen];assert len(a)==len(b)==3
  for old,new in zip(a,b):
   for kind in ('cold','follow'):
    assert old[kind]['response']==new[kind]['response']
    m=new[kind]['metrics'];assert m['completed'] and m['tokens']>0 and m['version']==3
    assert m['timingScope']=='prefill_synchronized_before_decode'
 for backend in ('manual','gpu'):
  assert s['series']['before'][backend]['response']==s['series']['after'][backend]['response']
  for phase in ('before','after'):assert s['series'][phase][backend]['metrics']['completed']
  m=s['series']['after'][backend]['metrics']
  assert m['tokens']>0 and m['version']==3 and m['timingScope']=='prefill_synchronized_before_decode'
 assert v['phone_15_20_tokens_s_certified'] is False
 assert len(v['ui_review'])>=3
 for img in v['ui_review']:
  p=Path(img['path']);assert p.parent==root and hashlib.sha256(p.read_bytes()).hexdigest()==img['sha256']
 print('SIGNED_PERFORMANCE_CODE_IMAGES_ACCEPTANCE_PASS')
if __name__=='__main__':verify()
