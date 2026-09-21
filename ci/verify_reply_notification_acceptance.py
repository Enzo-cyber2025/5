"""Require real Android notification, same-key update, saved output and reviewed UI."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
from verify_reply_notification_candidate import verify as candidate

def api(path):return json.loads(subprocess.check_output(['gh','api','repos/Enzo-cyber2025/5/'+path],text=True))
def verify():
    candidate()
    c=json.load(open('ci/reply-notification-candidate.json'));v=json.load(open('.delivery/reply-notification-acceptance.json'))
    assert v['status']=='SIGNED_REPLY_NOTIFICATION_ANDROID_PASS' and v['apk_sha256']==c['apk_sha256']
    r=api('actions/runs/'+str(v['run']))
    assert r['status']=='completed' and r['conclusion']=='success' and r['head_sha']==v['commit']
    assert r['run_attempt']==v['attempt'] and r['head_branch']=='arena/01a09b42-5' and r['path']=='.github/workflows/reply-notifications.yml'
    jobs=api('actions/runs/'+str(v['run'])+'/jobs')['jobs']
    assert next(x for x in jobs if x['id']==v['job'])['conclusion']=='success'
    build=api('actions/runs/'+str(c['build_run']))
    assert build['conclusion']=='success' and build['head_sha']==c['source_commit']
    root=Path(f"ci-results/{v['run']}-{v['attempt']}");s=json.load(open(root/'summary.json'))
    assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
    checks=('same_signature_update_preserves_models_and_chats','same_output_screen_off_saved_reply_alert_survives_service_stop','screen_off_progress_notifications_suppressed_without_changing_tokens','notification_tap_opens_correct_chat_and_auto_cancels','foreground_no_unnecessary_alert_and_native_cache_preserved','cancel_does_not_notify_success','real_image_reply_notifies_while_asleep','denied_permission_does_not_break_saved_generation')
    for name in checks:assert s['checks'][name]=='PASS',name
    obs=s['observations'];assert obs['before']['response']==obs['after']['response']
    assert obs['screen_off_updates_skipped']>0 and obs['progress_updates']<=1
    assert obs['after']['metrics']['completed'] and obs['after']['metrics']['tokens']>0
    sys.path.insert(0,'scripts')
    from android_checks import completed_after_actual_sleep
    assert 'mWakefulness=Asleep' in (root/'physical-reply-after-asleep-power.txt').read_text()
    assert completed_after_actual_sleep((root/'physical-reply-after-sleep-log.txt').read_text())
    assert completed_after_actual_sleep((root/'physical-reply-vision-sleep-log.txt').read_text())
    for stage in ('after','vision'):
        notice=(root/f'physical-reply-{stage}-notification.txt').read_text()
        assert 'reply-ready-v1' in notice and 'Resposta pronta' in notice and 'A resposta foi salva.' in notice
        assert 'ServiceRecord{' not in (root/f'physical-reply-{stage}-services.txt').read_text()
    cancel=(root/'physical-reply-cancellation-log.txt').read_text()
    assert re.search(r'GGUF_GENERATION_STATS .*success=0',cancel) and 'suppressed=not_saved_success' in cancel
    denied=(root/'physical-reply-permission-log.txt').read_text()
    assert re.search(r'GGUF_GENERATION_STATS .*success=1',denied) and 'blocked=permission' in denied
    review=v['ui_review'];assert review['status']=='PASS' and review['apk_sha256']==c['apk_sha256'] and len(review['images'])>=2
    for img in review['images']:
        p=Path(img['path']);assert p.parent==root and hashlib.sha256(p.read_bytes()).hexdigest()==img['sha256']
    print('SIGNED_REPLY_NOTIFICATION_ACCEPTANCE_PASS')
if __name__=='__main__':verify()
