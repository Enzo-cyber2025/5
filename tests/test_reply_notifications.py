from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
def text():return (ROOT/'apk-fix/java/com/ggufchat/app/ReplyNotifications.java').read_text()
def test_completion_is_private_saved_success_and_screen_gated():
 s=text()
 assert 'if(!success || !s.persisted || s.chatId==null)' in s
 assert 'pm.isInteractive()' in s and 'keyguard.isKeyguardLocked()' in s
 assert 'if(!off&&!locked)' in s
 assert 'VISIBILITY_PRIVATE' in s and 'setPublicVersion(publicNotice)' in s
 assert 'POST_NOTIFICATIONS' in s and 'IMPORTANCE_NONE' in s and 'areNotificationsEnabled' in s
 assert 'IMPORTANCE_DEFAULT' in s
 assert s.index('if(!success || !s.persisted') < s.index('nm.notify(tag(s.chatId)')
def test_no_per_token_power_ipc_or_updates_with_screen_off():
 s=text();p=s[s.index('boolean progressNow'):s.index('void finished')]
 assert 'if(s.registered&&!s.interactive)' in p and 'return false' in p
 assert 'getSystemService' not in p and 'isInteractive()' not in p
 assert 'progress_updates=' in s and 'skipped_screen_off=' in s
 assert 'ACTION_SCREEN_OFF' in s and 'RECEIVER_NOT_EXPORTED' in s
 assert 'remove(service)' in s and 'unregisterReceiver' in s
 assert 'Notification$' not in p

def test_pending_intent_is_immutable_and_per_chat_without_private_content():
 s=text();p=s[s.index('Intent intent='):s.index('nm.notify(tag')]
 assert 'FLAG_IMMUTABLE' in p and 'appendPath(s.chatId)' in p
 assert '.putExtra("chatId",s.chatId)' in p and '.ChatActivity' in p
 assert 'FLAG_ACTIVITY_CLEAR_TOP' in p and 'FLAG_ACTIVITY_SINGLE_TOP' not in p
 assert 'reply.toString' not in p and 'getTitle' not in p
 assert 'READY_ID=2101' in s and 'setAutoCancel(true)' in p

def test_cleanup_is_on_main_and_does_not_stop_a_new_worker():
 s=text();p=s[s.index('void workerFinished'):s.index('void destroy')]
 assert 'MAIN.post' in p and 'field.get(service)==owner' in p
 assert 'WorkWakeLocks.release(service)' in p and 'service.stopForeground(true)' in p
 assert p.index('field.get(service)==owner') < p.index('service.stopSelf()')

def test_patch_runs_on_exact_previous_dex_when_available(tmp_path):
 import shutil,pytest
 original=ROOT/'.cache/notify-base/smali/com/ggufchat/app'
 if not original.exists():pytest.skip('Exact baseline APK decoded in build job')
 sys.path.insert(0,str(ROOT/'apk-fix'));from reply_notifications import patch_reply_notifications
 for name in ['GenerationService.smali','GenerationService$1.smali','GenerationService$2.smali']:
  shutil.copyfile(original/name,tmp_path/name)
 patch_reply_notifications(tmp_path)
 s=(tmp_path/'GenerationService.smali').read_text()
 assert s.index('ChatStore;->upsert') < s.index('ReplyNotifications;->persisted')
 assert 'move-object v4, v8' in s
 assert 'abortRequested:Z' in s and 'ReplyNotifications;->finished' in s
 run=s[s.index('.method private runGeneration('):s.index('.method private updateNotification(')]
 assert '->releaseWakeLock()V' not in run and '->stopForeground(Z)V' not in run
 worker=(tmp_path/'GenerationService$1.smali').read_text()
 assert '.catchall' in worker and worker.count('ReplyNotifications;->workerFinished')==2
