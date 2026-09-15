"""Source/manifest contracts; actual screen-off progress requires Android tests."""
from pathlib import Path
import sys,zipfile
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))

def test_memory_telemetry_is_not_a_size_heuristic_gate():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'estimate>available' not in s and 'size+size/2' not in s
    assert 'policy=actual_allocator' in s and 'mp.load_mode=mmap?LLAMA_LOAD_MODE_MMAP:LLAMA_LOAD_MODE_NONE' in s
    assert 'if(!e->model) throw' in s and 'if(!e->ctx) throw' in s

def test_foreground_is_service_owned_non_exported_and_not_sticky():
    s=(ROOT/'apk-fix/java/com/ggufchat/app/ComputeService.java').read_text()
    assert 'startForegroundService' in s and 'FOREGROUND_SERVICE_TYPE_SPECIAL_USE' in s
    assert 'START_NOT_STICKY' in s and 'task.run()' in s and 'finally' in s
    assert 'WorkWakeLocks.release(this);stopForeground(true);stopSelf();' in s
    locks=(ROOT/'apk-fix/java/com/ggufchat/app/WorkWakeLocks.java').read_text()
    assert 'PARTIAL_WAKE_LOCK' in locks and 'lock.acquire(10*60*1000L)' in locks
    assert 'removeCallbacks(this)' in locks and 'lock.release()' in locks

def test_transfer_retains_independent_byte_verification():
    s=(ROOT/'apk-fix/java/com/ggufchat/app/GgufFile.java').read_text()
    assert '.transferTo(' in s and 'if(n==0)' in s
    assert 'verifyPayload(a,b,merged,progress)' in s
    assert 'if(x[i]!=y[i])' in s and 'out.getFD().sync()' in s
    assert 'encoderMatrix&&projectionMatrix' in s

def test_compute_binary_manifest_of_actual_last_release():
    from androguard.core.axml import AXMLPrinter
    from compute_manifest import compute_manifest
    with zipfile.ZipFile(ROOT/'.delivery/GGUF-Chat-mobile.apk') as z:data=z.read('AndroidManifest.xml')
    ns='{http://schemas.android.com/apk/res/android}'
    before=AXMLPrinter(data).get_xml_obj()
    patched=any(x.get(ns+'name')=='com.ggufchat.app.ComputeService' for x in before.findall('application/service'))
    after=before if patched else AXMLPrinter(compute_manifest(data)).get_xml_obj()
    services=after.findall('application/service');assert len(services)==2
    for s in services:
        assert s.get(ns+'exported')=='false'
        assert s.get(ns+'foregroundServiceType') in ('1073741824','0x40000000')
        assert s.find('property').get(ns+'name')=='android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE'
    assert any(x.get(ns+'name')=='android.permission.FOREGROUND_SERVICE_SPECIAL_USE' for x in after.findall('uses-permission'))


def test_power_audit_does_not_confuse_history_with_held_locks():
    sys.path.insert(0,str(ROOT/'scripts'))
    from android_checks import active_wake_locks
    history="\n\nWake Lock Log\n  ACQ GGUFChat:LocalCompute\n  REL GGUFChat:LocalCompute\n"
    assert not active_wake_locks('Wake Locks: size=0\n'+history)
    held="Wake Locks: size=1\n  PARTIAL_WAKE_LOCK 'GGUFChat:LocalCompute' ACQ=2s (uid=123)\n"
    assert 'GGUFChat:LocalCompute' in active_wake_locks(held+history)
    with pytest.raises(AssertionError):active_wake_locks(history)


def test_fast_completion_after_sleep_is_not_mislabeled_before_sleep():
    sys.path.insert(0,str(ROOT/'scripts'))
    from android_checks import completed_after_actual_sleep
    sleep='09-15 15:44:54.424 552 609 I PowerManagerService: Sleeping (uid 1000)...\n'
    done='09-15 15:44:55.297 5100 5408 I GGUFChatNative: GGUF_NATIVE_COMPLETE tokens=40 reason=eog projector=1\n'
    assert completed_after_actual_sleep(sleep+done)
    assert not completed_after_actual_sleep(sleep+done.replace('55.297','53.297'))
    assert not completed_after_actual_sleep(done)
