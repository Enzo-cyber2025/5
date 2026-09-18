#!/usr/bin/env python3
"""Byte proof first; then original/delivered/candidate triples on ONE emulator."""
import json,re,sys,traceback,shlex
from pathlib import Path
from test_gpu_rate_android import Android,PACKAGE,TEXT,BUILD,E,sha,collect,process_log
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_expanded_weights import evaluate,ENV,ON,VERIFY,MODEL
MARKER="GGUF_EXPANDED_WEIGHTS";PRECISION="F32";NAME="expanded"
COMPLETE_STATUS="COMPLETE_EXPANDED_OBSERVATIONS"


def observation(d,s,phase,state,label,env):
    apk=BUILD/(phase+'.apk');assert sha(apk)==s['build']['payloads'][phase]['test_sha256']
    assert d.shell('getprop ro.kernel.qemu')=='1'
    d.shell('input keyevent 224; wm dismiss-keyguard');d.shell('setprop wrap.'+PACKAGE+" ''")
    d.adb('uninstall',PACKAGE,check=False);d.adb('install','-g','-t',apk,timeout=180)
    installed=d.shell('pm path '+PACKAGE);assert installed.startswith('package:') and '\n' not in installed
    assert d.shell('sha256sum '+installed[8:]).split()[0]==sha(apk)
    script='#!/system/bin/sh\n'+''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in env.items())+'exec "$@"\n'
    d.write_private('files/vulkan-wrap.sh',script)
    root='/data/user/0/'+PACKAGE;uid=d.shell('stat -c %u '+root);assert uid.isdigit()
    d.shell(f'cp /data/local/tmp/gpu-rate.gguf {root}/files/gpu-rate.gguf && chown {uid}:{uid} {root}/files/gpu-rate.gguf && chmod 600 {root}/files/gpu-rate.gguf && restorecon -R {root}/files')
    d.shell('setprop wrap.'+PACKAGE+f" '/system/bin/sh {root}/files/vulkan-wrap.sh'")
    d.adb('logcat','-c')
    try:
        stdout=d.shell(f'am instrument -w -r -e state {state} -e emulator_confirmed 1 com.ggufchat.gpurate/com.ggufchat.gpurate.RateInstrumentation',timeout=1200)
        (E/f'physical-{NAME}-{label}-instrument.txt').write_text(stdout)
    finally:
        log=d.adb('logcat','-d','-v','threadtime')
        (E/f'physical-{NAME}-{label}-system-tail.txt').write_text(log[-1000000:])
    r=d.read_json('gpu-rate.json')
    (E/f'physical-{NAME}-{label}-raw.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
    r['test_apk_sha256']=sha(apk);r=collect(r,log,'before' if phase=='before' else 'after')
    native=process_log(log);assert len(native.encode())<1900000
    (E/f'physical-{NAME}-{label}-native.txt').write_text(native)
    assert r['vulkan_environment']==env
    # This experiment qualifies only the selected full-FP32 software device;
    # it cannot certify a mobile driver's different FP16 matmul policy.
    assert 'fp16: 0' in native and 'llvmpipe' in native
    if PRECISION=='Q8_LOSSLESS':assert 'int dot: 0' in native,'No activation requantization policy changes permitted'
    if phase=='candidate':
        m=re.findall(re.escape(MARKER)+r' enabled=1 tensors=(\d+) extra_device_bytes=(\d+) verification=(\d+) verified_bytes=(\d+) prepare_ns=(\d+) precision='+re.escape(PRECISION)+r' conversion=Vulkan',native)
        assert len(m)==1,'Missing real expansion proof'
        r['expansion']=dict(zip(('tensors','extra_device_bytes','verification','verified_bytes','prepare_ns'),map(int,m[0])))
        r['expansion'].update(precision=PRECISION,conversion='Vulkan')
    return r


def main(state):
    assert state in ('awake','asleep');d=Android('emulator-5554',E)
    s=dict(status='FAIL',state=state,hardware='software_vulkan_emulator',release_approved=False,
           model_sha256=sha(TEXT),pairs=[],build=json.loads((BUILD/'build.json').read_text()))
    try:
        assert s['model_sha256']==MODEL and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.adb('logcat','-G','32M')
        d.shell('settings put system screen_off_timeout 1800000');d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install','-r','-t',BUILD/'observer.apk',timeout=180)
        d.adb('push',TEXT,'/data/local/tmp/gpu-rate.gguf',timeout=180)
        assert d.shell('sha256sum /data/local/tmp/gpu-rate.gguf').split()[0]==MODEL
        # Full GPU vs independent CPU value check, then destroy this process.
        # NONE of these timings are used in a speed ratio.
        s['proof']=observation(d,s,'candidate',state,'proof-'+state,VERIFY)
        assert s['proof']['expansion']['verified_bytes']>0
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        for i in range(3):
            order=['before','after','candidate'] if i%2==0 else ['candidate','after','before']
            pair={'order':order};s['pairs'].append(pair)
            for phase in order:
                pair[phase]=observation(d,s,phase,state,f'{i+1}-{phase}-{state}',ON if phase=='candidate' else ENV)
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['status']=COMPLETE_STATUS;s['evaluation']=evaluate(s)
        print(json.dumps(s['evaluation'],indent=2),flush=True)
    except Exception:
        s['status']='FAIL';(E/f'physical-{NAME}-failure.txt').write_text(traceback.format_exc());raise
    finally:
        d.shell('setprop wrap.'+PACKAGE+" ''",check=False);d.shell('input keyevent 224',check=False)
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    main(sys.argv[1])
