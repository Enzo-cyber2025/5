#!/usr/bin/env python3
"""Clean Android: only one complete multimodal GGUF, no pair import or sidecar.
Uses actual signed APK, SAF import, native mtmd/Vulkan and unedited model replies.
"""
import hashlib
import json
import re
import shlex
import traceback
from pathlib import Path
from test_mobile import MobileAndroid, APK, VULKAN
from test_inference_android import fixtures, attach, reply
from android_checks import PACKAGE, position, vulkan_offloaded

E = Path('evidence')
MODEL = Path('.cache/standalone-500m/model.gguf')
EXPECTED_APK = '4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6'


def main():
    E.mkdir(exist_ok=True)
    d = MobileAndroid('emulator-5554', E)
    summary = {'status': 'FAIL', 'scope': 'standalone-500m-clean-install-no-sidecar',
               'apk_sha256': hashlib.sha256(APK.read_bytes()).hexdigest(),
               'environment': 'Android emulator, Mesa software Vulkan; exact delivery signature',
               'checks': {}, 'response_quality': {},
               'fixture_origin': 'Real SmolVLM-500M weights packaged by upstream GGUFWriter outside the app; not a public pre-unified download'}
    checks = summary['checks']

    def save():
        (E / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    def inventory(unit, stage):
        models = d.read_json('models.json')
        assert models == [unit], models
        private = d.shell('find /data/user/0/' + PACKAGE + " -type f -name '*.gguf'").splitlines()
        shared = d.shell("find /sdcard/Download -type f -name '*.gguf'").splitlines()
        assert private == [unit['path']], private
        assert shared == [], shared
        assert d.shell('sha256sum ' + shlex.quote(unit['path'])).split()[0] == provenance['sha256']
        result = {'models': models, 'private_gguf_files': private, 'download_gguf_files': shared}
        (E / f'physical-standalone-{stage}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def native_load():
        pid = d.alive()
        def ready():
            assert d.alive() == pid, 'Native process changed, no crash retry'
            log = d.adb('logcat', '-d', f'--pid={pid}')
            assert not any(x in log for x in ('Create failed:', 'Fatal signal', 'Generation failed:')), log[-8000:]
            if 'GGUF_SINGLE_FILE_LOADED same_path=1' not in log or 'GGUF_UNIT_LOADED language=' not in log:
                return None
            assert 'GGUF_PROJECTOR_LOADED vision=1' in log
            assert 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in log
            assert vulkan_offloaded(log)
            assert 'GGUF_UNIT_LOADED language=Vulkan' in log and 'projector=Vulkan' in log
            return log
        return d.wait(ready, 'linguagem e visão carregadas do único arquivo', timeout=300)

    def answer(chat, question, stage, images, pattern):
        text = reply(d, chat, question, stage, images=images)
        summary['response_quality'][stage] = {'status': 'PASS' if re.search(pattern, text, re.I) else 'FAIL',
                                               'criterion': 'Expected object/answer match, not general accuracy',
                                               'response': text}
        checks[stage + '_native_inference'] = 'PASS'
        save()
        return text

    try:
        assert VULKAN and summary['apk_sha256'] == EXPECTED_APK
        provenance = json.loads((E / 'physical-standalone-fixture.json').read_text())
        assert provenance['status'] == 'PASS' and provenance['source_files_removed_before_emulator']
        assert list(MODEL.parent.glob('*.gguf')) == [MODEL]
        summary['single_gguf_sha256'] = provenance['sha256']
        summary['single_gguf_size'] = provenance['size']
        summary['tensor_count'] = provenance['tensor_count']
        assert d.shell('getprop ro.kernel.qemu') == '1'
        d.adb('root', check=False); d.adb('wait-for-device', timeout=60)
        d.shell('wm size 720x1280'); d.shell('wm density 240')
        d.adb('logcat', '-G', '16M'); d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install', '-r', '-g', APK, timeout=180)
        assert d.shell('pm clear ' + PACKAGE) == 'Success'
        d.grant_test_notifications(); d.launch()
        assert d.read_json('models.json', optional=True) == []
        d.shell('mkdir -p /sdcard/Download')
        assert d.shell("find /sdcard/Download -type f -name '*.gguf'") == ''
        d.adb('logcat', '-c')
        # Only this complete, neutral-named file is ever copied to the emulator.
        unit = d.import_model(MODEL)
        assert unit['capability'] == 'VISION_SINGLE_GGUF' and unit['multimodal'] is True
        assert unit['path'] == unit['mmprojPath'] and unit['size'] == provenance['size']
        log = d.adb('logcat', '-d')
        assert 'GGUF_PHYSICAL_UNIFICATION_OK' not in log, 'This test must not use the app pair merger'
        # Remove the SAF source after the private byte-exact import is complete.
        d.shell('rm -- ' + shlex.quote('/sdcard/Download/' + MODEL.name))
        inventory(unit, 'import')
        assert position(d.ui(), text='Visão', contains=True, package={PACKAGE})
        d.capture('physical-standalone-library.png')
        checks['single_SAF_import_intrinsic_vision_no_pair_no_sidecar'] = 'PASS'; save()
        fixtures()
        for filename, question, stage, pattern in (
            ('frame-a.jpg', 'Name the main animal in the image. Reply in English.', 'standalone-animal', r'\bdog\b'),
            ('frame-b.jpg', 'Name the main vehicle in the image. Reply in English.', 'standalone-vehicle', r'\bbus\b'),
        ):
            chat = d.new_chat(unit, 99, context_size=4096)
            load = native_load()
            (E / f'physical-{stage}-load.txt').write_text(load)
            attach(d, chat, [filename])
            answer(chat, question, stage, 1, pattern)
            inventory(unit, stage)
        # Force-stop/reopen the bus conversation, with no source GGUF or projector available.
        d.launch(); inventory(unit, 'restart')
        d.open_existing_chat(chat['title'])
        (E / 'physical-standalone-restart-load.txt').write_text(native_load())
        answer(chat, 'Name the main vehicle in the attached image again. Reply in English.',
               'standalone-restart', 1, r'\bbus\b')
        checks['restart_same_single_file_and_image_history'] = 'PASS'
        chat = d.new_chat(unit, 99, context_size=4096)
        (E / 'physical-standalone-text-load.txt').write_text(native_load())
        answer(chat, 'What is two plus two? Reply with only the number.', 'standalone-text', 0, r'\b4\b')
        inventory(unit, 'final')
        checks['image_inference'] = 'PASS'
        summary['quality_limitations'] = 'Object/answer matches are recorded separately. Read unedited replies; no general response-quality approval.'
        summary['status'] = 'PASS'
    except Exception as ex:
        summary['error'] = str(ex)
        traceback.print_exc()
        (E / 'physical-standalone-failure.txt').write_text(traceback.format_exc())
    finally:
        save(); print(json.dumps(summary, ensure_ascii=False, indent=2))
        try:
            d.capture('physical-standalone-final.png')
            (E / 'physical-standalone-final-logcat.txt').write_text(d.adb('logcat', '-d'))
        except Exception:
            pass
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
