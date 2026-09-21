#!/usr/bin/env python3
"""One real APK: control CPU packing vs Vulkan packing, full-size real photo.
Diagnostics read back pixels and hash embeddings; timings are NOT speed evidence.
"""
import json,re,hashlib,shlex,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_projector_cache_android import persisted_image_prompt
from test_vulkan_profile_android import configure
from android_checks import PACKAGE,vulkan_offloaded,image_prefill_records
from vulkan_strict_checks import strict_audit
E=Path('evidence')
PROMPT='Name the main animal in the image. Reply in English.'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
 E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
 d=LatencyAndroid('emulator-5554',E)
 build=json.load(open(E/'physical-projector-build.json'))
 apk=Path('.cache/projector-candidate.apk')
 report=dict(status='FAIL',build=build,tested_apk_sha256=sha(apk),control_kind='same candidate APK, Vulkan packing flag unset',both_modes_same_apk=True,series={},speed_approval=False,release_approved=False,default_enabled=False)
 try:
  assert sha(apk)==build['after_sha256']
  assert d.shell('getprop ro.kernel.qemu')=='1'
  d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
  d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
  d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
  external=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(external)==expected
  report['gguf_sha256']=sha(external)
  d.adb('install','-g',apk,timeout=180);d.grant_test_notifications()
  model=d.import_model(external)
  assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0]==report['gguf_sha256']
  for phase in ('control','vulkan'):
   settings={'GGUF_VERIFY_IMAGE_PACK':'1','GGUF_DISABLE_IMAGE_EMBED_CACHE':'1'}
   if phase=='vulkan':settings['GGUF_VULKAN_IMAGE_PACK']='1'
   configure(d,settings);d.adb('logcat','-c')
   chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d);pid=d.alive()
   env=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
   for k,v in settings.items():assert (k+'='+v).encode() in env
   assert (b'GGUF_VULKAN_IMAGE_PACK=1' in env)==(phase=='vulkan')
   load=d.adb('logcat','-d',f'--pid={pid}')
   assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
   assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',load)
   (E/f'physical-image-upload-{phase}-load.txt').write_text(load[-100000:])
   attach(d,chat,['frame-a.jpg'])
   pending=sum(item.get('message',-1)<0 for item in item_state(d,chat)['items'])
   r=run_reply(d,chat,PROMPT,'image-upload-'+phase,False,True,persisted_prompt=persisted_image_prompt(PROMPT,pending),timeout=1200)
   log=d.adb('logcat','-d',f'--pid={pid}')
   r['strict']=strict_audit(log)
   records=image_prefill_records(log,1);assert all(b=='Vulkan' for _,b in records)
   uploads=re.findall(r'GGUF_IMAGE_UPLOAD packing=(\w+) bytes=(\d+) host_planar_copy=(\d+)',log)
   assert len(uploads)==len(records)>0
   desired='Vulkan' if phase=='vulkan' else 'CPU'
   assert all(kind==desired and int(copy)==int(phase=='control') and int(size)>0 for kind,size,copy in uploads)
   m=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+)',log);assert m and int(m[1])==0 and int(m[2])==len(records)
   digests=re.findall(r'GGUF_IMAGE_PACK_EMBEDDING sha256=([0-9a-f]{64}) bytes=(\d+)',log)
   assert len(digests)==len(records)
   equal=re.findall(r'GGUF_IMAGE_PACK_BYTES_EQUAL bytes=(\d+) backend=Vulkan\w*',log)
   if phase=='vulkan':assert list(map(int,equal))==[int(size) for _,size,_ in uploads]
   else:assert not equal
   saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
   r['raw_response']=next(m['content'] for m in reversed(saved['messages']) if m['role']=='assistant')
   r.update(uploads=uploads,embedding_digests=digests,pixel_verification_bytes=list(map(int,equal)),benchmark=False)
   report['series'][phase]=r
   latest_footer(d,r,'image-upload-'+phase)
   (E/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
  before,after=report['series']['control'],report['series']['vulkan']
  assert before['embedding_digests']==after['embedding_digests'],'Changed full projector output bytes'
  assert before['raw_response']==after['raw_response'] and before['tokens']==after['tokens'],'Changed raw model response'
  report['status']='PASS_EXPERIMENTAL_VULKAN_PACKING_BYTES_ONLY'
 except Exception as ex:
  report['error']=str(ex);(E/'physical-image-upload-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
 finally:
  try:d.shell('setprop wrap.'+PACKAGE+" ''")
  except Exception:pass
  report['scope']='Actual Android APK, actual SAF dog photo and unchanged public SmolVLM GGUF. Only RGB layout packing moves to Vulkan. Decode, resize, crops, normalization and upload orchestration remain host work. Separate control/GPU fresh-Engine runs, cache disabled, pixel readback and full embedding SHA-256 comparison. Instrumented, one observation/mode; NOT speed, physical GPU, universal architecture or release approval. Experiment is off by default.'
  (E/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
 return 0 if report['status']=='PASS_EXPERIMENTAL_VULKAN_PACKING_BYTES_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
