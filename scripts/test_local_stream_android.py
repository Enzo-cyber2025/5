#!/usr/bin/env python3
"""Three-mode experiment: delivered323, identical new APK OFF and ON. Not delivery."""
import json,sys,traceback
from pathlib import Path
from test_perceptible_text_android import run,sha,E,TEXT,LatencyAndroid,init_ime,PACKAGE
sys.path.insert(0,str(Path('ci').resolve()))
from perceptible_text_gate import evaluate
from perceptible_image_gate import BASELINE,CANDIDATE
from test_code_android import run as code_ui

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',build=json.load(open(E/'physical-local-stream-build.json')),blocks=[])
    try:
        build=s['build'];assert build['baseline_original_sha256']==BASELINE and build['image_candidate_base_sha256']==CANDIDATE
        assert build['changed_payload_entries']==['classes.dex'] and build['default_enabled'] is False
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        model=None
        for block,order in enumerate((('original','off','on'),('on','original','off'),('off','original','on'))):
            rows={}
            for mode in order:
                original=mode=='original';apk=Path('.cache/local-stream')/('before.apk' if original else 'candidate.apk')
                assert sha(apk)==build['before_sha256' if original else 'after_sha256']
                d.adb('install','-r','-g',apk,timeout=180);d.grant_test_notifications()
                if model is None:
                    model=d.import_model(TEXT);assert d.shell('sha256sum '+model['path']).split()[0]==sha(TEXT)
                settings={} if original else {'GGUF_LOCAL_STREAM':'1' if mode=='on' else '0'}
                states={}
                for state in (('awake','asleep') if block%2==0 else ('asleep','awake')):
                    states[state]=run(d,model,f'local-{block}-{mode}',state,settings)
                rows[mode]=states
            s['blocks'].append(rows)
            (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        def comparison(control):
            pairs=[]
            for block in s['blocks']:
                pairs.append({('before' if mode==control else 'after'):states for mode,states in block.items() if mode in (control,'on')})
            expected=BASELINE if control=='original' else build['after_sha256']
            adjusted=dict(build,baseline_original_sha256=expected)
            return evaluate(dict(status='RUNNING',build=adjusted,pairs=pairs),baseline_sha=expected,candidate_sha=build['after_sha256'])
        s['original_vs_local']=comparison('original');s['same_apk_off_vs_on']=comparison('off')
        same=s['same_apk_off_vs_on']['observations'];on=same['awake'];off=same['asleep']
        additional=(min(on['decode_speedup_ratios'])>=1.03 and on['median_decode_speedup']>=1.05
                    and min(off['decode_speedup_ratios'])>=0.97 and min(on['first_ui_speedup_ratios'])>=0.95)
        s['additional_gain_passed']=additional
        s['code_and_copy']=code_ui(d)
        s['status']='PASS_LOCAL_STREAM_EXPERIMENT' if additional and s['original_vs_local']['text_gain_passed'] else 'NO_MATERIAL_ADDITIONAL_GAIN'
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-local-stream-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Opt-in DEX-only experiment, not a release. Same native/image/cache payload as 2b44. Three AB/BA/AB paired comparisons against delivered323 and against the SAME compiled APK with routing OFF; warmed ON/OFF, raw histories and strict GPU. Original-vs-ON release text criterion plus each ON-vs-OFF awake >=3%/median>=5%, no >3% sleep or >5.3% first-text regression. No changes to model math, token budget, or timing delays. Not physical-device certification.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 1 if s['status']=='FAIL' else 0
if __name__=='__main__':raise SystemExit(main())
