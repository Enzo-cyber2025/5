#!/usr/bin/env python3
"""Exact signed update, real inference, sleeping completion and actual notification taps.
No injected responses, notification posting commands, model database or metrics.
"""
import hashlib,json,re,shlex,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_generation_stats_android import measured_reply,TEXT
from test_mobile import APK,MODEL,PROJ,select_pair
from test_inference_android import fixtures,attach,reply
from android_checks import PACKAGE,position,active_wake_locks,completed_after_actual_sleep,generation_completed
E=Path('evidence');PROMPT='List ten useful tips for learning a new language. Explain each tip in two sentences.'


def keys(d):
    # This command lists ACTIVE keys, unlike historical dumpsys log entries.
    return [x.strip() for x in d.shell('cmd notification list').splitlines() if '|'+PACKAGE+'|' in x]

def ready_key(d,chat):
    return next((x for x in keys(d) if '|2101|reply-ready:'+chat['id']+'|' in x),None)

def record(d,key):return d.shell('cmd notification get '+shlex.quote(key))

def wake(d):d.shell('input keyevent 224');d.shell('wm dismiss-keyguard')

def sleep_after_start(d,original,prompt,clear_log=True):
    original(prompt,clear_log=clear_log)
    def active():
        log=d.adb('logcat','-d',f'--pid={d.alive()}')
        assert not generation_completed(log),'Reply completed before actual screen-off'
        power=d.shell('dumpsys power')
        return power if 'GGUFChat:LocalCompute' in active_wake_locks(power) else None
    d.wait(active,'real CPU lease before screen off',timeout=60)
    d.shell('input keyevent 223')
    d.wait(lambda:'mWakefulness=Asleep' in d.shell('dumpsys power'),'actual asleep state',timeout=30)

def asleep_reply(d,chat,prompt,stage):
    original=d.send
    d.send=lambda text,clear_log=True:sleep_after_start(d,original,text,clear_log)
    try:r=measured_reply(d,chat,prompt,'reply-notice-'+stage,True)
    finally:d.send=original
    power=d.shell('dumpsys power');log=d.adb('logcat','-d')
    assert 'mWakefulness=Asleep' in power and completed_after_actual_sleep(log)
    (E/f'physical-reply-{stage}-asleep-power.txt').write_text(power)
    (E/f'physical-reply-{stage}-sleep-log.txt').write_text('\n'.join(x for x in log.splitlines() if 'GGUF_' in x or 'PowerManagerService' in x))
    return r

def stopped(d):
    def done():
        text=d.shell('dumpsys activity services '+PACKAGE)
        return text if 'ServiceRecord{' not in text else None
    services=d.wait(done,'generation service actually stopped',timeout=30)
    assert 'GGUFChat:LocalCompute' not in active_wake_locks(d.shell('dumpsys power'))
    return services

def check_notice(d,chat,stage):
    key=d.wait(lambda:ready_key(d,chat),'actual saved-reply notification in NotificationManager',timeout=30)
    detail=record(d,key)
    assert 'reply-ready-v1' in detail and 'Resposta pronta' in detail,detail
    assert 'A resposta foi salva.' in detail,detail
    assert 'mImportance=3' in detail or 'importance=3' in detail,detail
    (E/f'physical-reply-{stage}-notification.txt').write_text(detail)
    (E/f'physical-reply-{stage}-services.txt').write_text(stopped(d))
    assert key in keys(d),'Completion notification removed with its service'
    assert not any('|1001|' in x for x in keys(d)),'Obsolete generating notification remains'
    return key

def init_ime(d):
    wake(d);d.adb('install','-r',Path('.cache/test-input/input.apk'))
    def listed():return next((x.strip() for x in d.shell('ime list -a -s').splitlines() if x.strip().startswith('com.ggufchat.testinput/')),None)
    ime=d.wait(listed,'test IME registered after unlock',timeout=60)
    d.shell('ime enable '+shlex.quote(ime));d.shell('ime set '+shlex.quote(ime))

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    c=json.load(open('ci/reply-notification-candidate.json'))
    s=dict(status='FAIL',apk_sha256=hashlib.sha256(APK.read_bytes()).hexdigest(),checks={});checks=s['checks']
    try:
        assert s['apk_sha256']==c['apk_sha256'] and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False);d.adb('logcat','-G','16M');init_ime(d)
        baseline=Path('.cache/reply-base.apk');assert hashlib.sha256(baseline.read_bytes()).hexdigest()==c['baseline_sha256']
        d.adb('install','-r','-g',baseline,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success';d.grant_test_notifications()
        model=d.import_model(TEXT);old_chat=d.new_chat(model,0,context_size=2048)
        before=asleep_reply(d,old_chat,PROMPT,'before')
        wake(d);models=d.read_json('models.json');chats=d.read_json('chats.json')
        d.write_private('files/notification-update-probe','preserve')
        d.adb('install','-r','-g',APK,timeout=180)
        assert d.read_json('models.json')==models and d.read_json('chats.json')==chats
        assert d.shell('cat /data/user/0/'+PACKAGE+'/files/notification-update-probe')=='preserve'
        checks['same_signature_update_preserves_models_and_chats']='PASS'
        chat=d.new_chat(model,0,context_size=2048);pid=d.alive()
        after=asleep_reply(d,chat,PROMPT,'after');assert before['response']==after['response'],'Delivery change altered model output'
        key=check_notice(d,chat,'after')
        assert after['response'][:80] not in record(d,key),'Response text exposed in completion notice'
        log=d.adb('logcat','-d',f'--pid={pid}')
        assert 'GGUF_REPLY_NOTICE posted=1 saved=1 screen_off=1' in log
        stats=re.search(r'GGUF_NOTICE_STATS progress_updates=(\d+) skipped_screen_off=(\d+)',log);assert stats
        assert int(stats[2])>0 and int(stats[1])<=1,stats.groups()
        checks['same_output_screen_off_saved_reply_alert_survives_service_stop']='PASS'
        checks['screen_off_progress_notifications_suppressed_without_changing_tokens']='PASS'
        s['observations']=dict(before=before,after=after,progress_updates=int(stats[1]),screen_off_updates_skipped=int(stats[2]),scope='One genuine same-prompt comparison, NOT a statistical speed benchmark. Native bytes unchanged. Counts concern progress notifications, not token generation.')
        # Open a DIFFERENT conversation without force-stop (which cancels alerts),
        # then tap the real shade notification and verify its destination.
        wake(d);d.shell('input keyevent 4')
        d.open_existing_chat(old_chat['title']);assert key in keys(d)
        d.shell('cmd statusbar expand-notifications')
        d.wait(lambda:position(d.ui(),text='Resposta pronta',package={'com.android.systemui'}),'real notification shade entry')
        d.capture('physical-reply-notification-shade.png')
        d.tap(text='Resposta pronta',package={'com.android.systemui'})
        d.wait(lambda:position(d.ui(),text=chat['title'],package={PACKAGE}),'notification opened correct conversation')
        d.wait(lambda:not ready_key(d,chat),'notification auto-cancelled on tap')
        latest_footer(d,after,'notification-opened-chat')
        assert d.alive()==pid
        checks['notification_tap_opens_correct_chat_and_auto_cancels']='PASS'
        # Service destruction must not discard the existing native prefix cache.
        wait_ready(d);follow=measured_reply(d,chat,'Give one more practical recommendation.','reply-notice-awake-follow',True)
        stopped(d);assert d.alive()==pid and follow['metrics']['reusedPromptTokens']>0
        assert not ready_key(d,chat)
        assert 'GGUF_REPLY_NOTICE suppressed=screen_active' in d.adb('logcat','-d',f'--pid={pid}')
        latest_footer(d,follow,'notification-awake-follow')
        checks['foreground_no_unnecessary_alert_and_native_cache_preserved']='PASS'
        # Real UI cancellation must never be labelled a completed reply.
        wait_ready(d);d.send('Write a long detailed list of fifty study tips. Explain each tip fully.')
        d.wait(lambda:'GGUF_PROMPT_CACHE' in d.adb('logcat','-d',f'--pid={pid}'),'native work before cancellation',timeout=180)
        d.tap(text='Parar',package={PACKAGE})
        d.wait(lambda:'GGUF_REPLY_NOTICE suppressed=not_saved_success' in d.adb('logcat','-d',f'--pid={pid}'),'cancelled reply has no success alert')
        stopped(d);assert not ready_key(d,chat)
        log=d.adb('logcat','-d',f'--pid={pid}');assert re.search(r'GGUF_GENERATION_STATS .*success=0',log)
        (E/'physical-reply-cancellation-log.txt').write_text(log[-150000:])
        checks['cancel_does_not_notify_success']='PASS'
        # Same notification path after real pixel inference, not a text-only mock.
        d.launch();d.shell('mkdir -p /sdcard/Download')
        for f in (MODEL,PROJ):d.adb('push',f,'/sdcard/Download/'+f.name,timeout=300)
        select_pair(d)
        vision=d.wait(lambda:next((m for m in d.read_json('models.json') if m.get('capability')=='VISION_SINGLE_GGUF'),None),'real physical vision import',timeout=600)
        fixtures();vchat=d.new_chat(vision,0,context_size=4096);attach(d,vchat,['frame-a.jpg'])
        original=d.send;d.send=lambda text,clear_log=True:sleep_after_start(d,original,text,clear_log)
        try:answer=reply(d,vchat,'Name the main animal in the image. Reply in English.','reply-notice-vision',images=1)
        finally:d.send=original
        assert 'dog' in answer.lower();assert 'mWakefulness=Asleep' in d.shell('dumpsys power')
        assert completed_after_actual_sleep(d.adb('logcat','-d'))
        check_notice(d,vchat,'vision')
        (E/'physical-reply-vision-sleep-log.txt').write_text('\n'.join(x for x in d.adb('logcat','-d').splitlines() if 'GGUF_' in x or 'PowerManagerService' in x))
        checks['real_image_reply_notifies_while_asleep']='PASS'
        # Real denied runtime permission, not a fake notifier. Revocation can
        # kill the process. Mark a permanent user denial so reopening the app
        # cannot accidentally grant it or race an unrelated permission dialog.
        wake(d);d.shell('pm revoke '+PACKAGE+' android.permission.POST_NOTIFICATIONS')
        d.shell('pm set-permission-flags '+PACKAGE+' android.permission.POST_NOTIFICATIONS user-set user-fixed')
        d.launch()
        d.open_existing_chat(chat['title']);wait_ready(d)
        denied_reply=asleep_reply(d,chat,'Reply in English with a short greeting.','permission-denied')
        d.wait(lambda:'GGUF_REPLY_NOTICE blocked=permission' in d.adb('logcat','-d',f'--pid={d.alive()}'),'honest notification permission block')
        stopped(d);assert not ready_key(d,chat) and denied_reply['metrics']['completed']
        (E/'physical-reply-permission-log.txt').write_text(d.adb('logcat','-d',f'--pid={d.alive()}')[-150000:])
        checks['denied_permission_does_not_break_saved_generation']='PASS'
        s['status']='PASS'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-reply-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:
            (E/'physical-reply-final-log.txt').write_text(d.adb('logcat','-d')[-150000:])
            wake(d);(E/'physical-reply-final-ui.txt').write_text(d.ui());d.capture('physical-reply-final.png')
        except Exception:pass
        print(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
