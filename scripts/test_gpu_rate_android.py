#!/usr/bin/env python3
"""Direct observer for historical/current native APKs. Disposable emulator ONLY.
No UI importer, no native recompilation, no CPU replacement, no elapsed-response rate.
"""
import hashlib,json,re,sys,traceback
from pathlib import Path
from test_android import Android
from android_checks import PACKAGE,vulkan_offloaded
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_gpu_rate import HASHES,MODEL,evaluate
E=Path('evidence');BUILD=Path('.cache/gpu-rate')
TEXT=Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def process_log(log):
    starts=[line.split()[2] for line in log.splitlines() if 'GPU_RATE_BEGIN stage=' in line]
    assert len(starts)==2 and len(set(starts))==1,'Missing markers or process restart'
    pid=starts[0]
    return '\n'.join(line for line in log.splitlines() if len(line.split())>2 and line.split()[2]==pid)

def collect(report,log,phase):
    assert report['status']=='PASS_NATIVE_OBSERVER',report
    log=process_log(log)
    assert vulkan_offloaded(log),'No actual positive native Vulkan offload; no GPU comparison'
    assert 'GGUF_STRICT_VULKAN_BLOCKED' not in log
    report['vulkan_positive_offload']=True
    for field,pattern in [('batch',r'\bn_batch\s*=\s*(\d+)'),('ubatch',r'\bn_ubatch\s*=\s*(\d+)')]:
        matches=re.findall(pattern,log);assert len(matches)==1,(field,matches)
        report[field]=int(matches[0])
    for stage in ('warmup','sample'):
        begin='GPU_RATE_BEGIN stage='+stage;end='GPU_RATE_END stage='+stage
        assert log.count(begin)==log.count(end)==1
        segment=log.split(begin,1)[1].split(end,1)[0]
        done=re.findall(r'GGUF_NATIVE_COMPLETE tokens=(\d+) reason=(length|eog) projector=0',segment)
        assert len(done)==1 and done[0]==('128','length'),done
        report[stage]['native_tokens']=int(done[0][0]);report[stage]['native_reason']=done[0][1]
        if phase=='after':report[stage]['strict']=strict_audit(segment)
    return report

def main(state):
    assert state in ('awake','asleep');d=Android('emulator-5554',E)
    s=dict(status='FAIL',state=state,hardware='software_vulkan_emulator',release_approved=False,
           apk_sha256=HASHES.copy(),model_sha256=sha(TEXT),pairs=[],build=json.loads((BUILD/'build.json').read_text()))
    try:
        assert s['model_sha256']==MODEL
        assert d.shell('getprop ro.kernel.qemu')=='1','NEVER uninstall anything on a user device'
        d.adb('root',check=False);d.adb('wait-for-device');d.adb('logcat','-G','32M')
        d.shell('settings put system screen_off_timeout 1800000')
        d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install','-r','-t',BUILD/'observer.apk',timeout=180)
        d.adb('push',TEXT,'/data/local/tmp/gpu-rate.gguf',timeout=180)
        assert d.shell('sha256sum /data/local/tmp/gpu-rate.gguf').split()[0]==MODEL
        for i in range(3):
            order=['before','after'] if i%2==0 else ['after','before'];pair={'order':order};s['pairs'].append(pair)
            for phase in order:
                label=f'{i+1}-{phase}-{state}';apk=BUILD/(phase+'.apk')
                assert sha(apk)==s['build']['payloads'][phase]['test_sha256']
                assert d.shell('getprop ro.kernel.qemu')=='1'
                d.shell('input keyevent 224; wm dismiss-keyguard')
                d.shell('setprop wrap.'+PACKAGE+" ''")
                d.adb('uninstall',PACKAGE,check=False)
                d.adb('install','-g','-t',apk,timeout=180)
                path=d.shell('pm path '+PACKAGE);assert path.startswith('package:') and '\n' not in path
                assert d.shell('sha256sum '+path[len('package:'):]).split()[0]==sha(apk)
                d.write_private('files/vulkan-wrap.sh','#!/system/bin/sh\nexport GGML_VK_VISIBLE_DEVICES=0\nexec "$@"\n')
                root='/data/user/0/'+PACKAGE;uid=d.shell('stat -c %u '+root);assert uid.isdigit()
                d.shell(f'cp /data/local/tmp/gpu-rate.gguf {root}/files/gpu-rate.gguf && chown {uid}:{uid} {root}/files/gpu-rate.gguf && chmod 600 {root}/files/gpu-rate.gguf && restorecon -R {root}/files')
                d.shell('setprop wrap.'+PACKAGE+f" '/system/bin/sh {root}/files/vulkan-wrap.sh'")
                d.adb('logcat','-c')
                try:
                    stdout=d.shell(f'am instrument -w -r -e state {state} -e emulator_confirmed 1 com.ggufchat.gpurate/com.ggufchat.gpurate.RateInstrumentation',timeout=1200)
                    (E/f'physical-gpu-rate-{label}-instrument.txt').write_text(stdout)
                finally:
                    log=d.adb('logcat','-d','-v','threadtime')
                    (E/f'physical-gpu-rate-{label}-log.txt').write_text(log[-1500000:])
                report=d.read_json('gpu-rate.json')
                (E/f'physical-gpu-rate-{label}-raw.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
                report['test_apk_sha256']=sha(apk)
                pair[phase]=collect(report,log,phase)
                # Keep the COMPLETE inference process log separately. Busy first
                # boot system logs can otherwise displace load/warmup markers
                # from the bounded diagnostic tail, even after runtime checks pass.
                native_log=process_log(log)
                assert len(native_log.encode())<1900000,'Native proof exceeds publication bound; do not silently truncate'
                (E/f'physical-gpu-rate-{label}-native.txt').write_text(native_log)
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['status']='COMPLETE_OBSERVATIONS';s['evaluation']=evaluate(s)
        print(json.dumps(s['evaluation'],indent=2),flush=True)
    except Exception:
        s['status']='FAIL';(E/'physical-gpu-rate-failure.txt').write_text(traceback.format_exc());raise
    finally:
        d.shell('setprop wrap.'+PACKAGE+" ''",check=False)
        d.shell('input keyevent 224',check=False)
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    main(sys.argv[1])
