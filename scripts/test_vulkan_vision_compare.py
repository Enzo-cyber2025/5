#!/usr/bin/env python3
"""Compare the actual failed external-GGUF bus case against the delivered baseline.
Equality and semantic correctness are separate assertions/results. No fake replies.
"""
import hashlib,json,shlex,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready
from test_reply_notifications_android import init_ime
from test_inference_android import fixtures,attach,reply
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from android_checks import PACKAGE,vulkan_offloaded
E=Path('evidence')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
 E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
 d=LatencyAndroid('emulator-5554',E)
 c=json.load(open('ci/vulkan-candidate.json'))
 s=dict(status='FAIL',apk_sha256=sha('.delivery/GGUF-Chat-mobile.apk'),baseline_sha256=sha('.cache/vulkan-baseline.apk'),responses={},semantic_vehicle={},checks={})
 try:
  assert s['apk_sha256']==c['apk_sha256'] and s['baseline_sha256']==c['baseline_sha256']
  assert d.shell('getprop ro.kernel.qemu')=='1'
  d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','16M')
  d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
  d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
  external=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(external)==expected
  s['external_gguf_sha256']=sha(external);fixtures()
  d.adb('install','-g','.cache/vulkan-baseline.apk',timeout=180);d.grant_test_notifications()
  foreign=d.import_model(external)
  assert foreign['path']==foreign.get('mmprojPath') and foreign['capability']=='VISION_SINGLE_GGUF'
  assert d.shell('sha256sum '+shlex.quote(foreign['path'])).split()[0]==s['external_gguf_sha256']
  for phase in ('before','after'):
   if phase=='after':
    models,chats=d.read_json('models.json'),d.read_json('chats.json')
    assert c['signer_sha256']==c['baseline_signer_sha256']
    d.adb('install','-r','-g','.delivery/GGUF-Chat-mobile.apk',timeout=180)
    assert models==d.read_json('models.json') and chats==d.read_json('chats.json')
   d.adb('logcat','-c');chat=d.new_chat(foreign,99,context_size=4096,threads=2);wait_ready(d)
   load=d.adb('logcat','-d',f'--pid={d.alive()}')
   assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
   (E/f'physical-vision-{phase}-load.txt').write_text(load[-100000:])
   attach(d,chat,['frame-b.jpg'])
   answer=reply(d,chat,'Name the main vehicle in the image. Reply in English.','vision-compare-'+phase,images=1)
   s['responses'][phase]=answer;s['semantic_vehicle'][phase]='PASS' if 'bus' in answer.lower() else 'FAIL'
  assert s['responses']['before']==s['responses']['after'],'Visual output differs from baseline'
  s['checks']['same_external_bytes_real_vulkan_and_equal_response']='PASS'
  s['status']='PASS_EQUALITY_ONLY'
 except Exception as ex:
  s['error']=str(ex);(E/'physical-vision-compare-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
 finally:
  s['scope']='One real external-format GGUF/bus observation per exact signed APK, same software Vulkan and image/settings. Equality is NOT semantic success; inspect semantic_vehicle separately.'
  (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
 return 0 if s['status']=='PASS_EQUALITY_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
