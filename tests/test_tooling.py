import json
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import zipfile
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apk-fix"))
sys.path.insert(0, str(ROOT / "scripts"))
from build_apk import rebuild_zip, verify_alignment, verify_payload
from patch_dex import PATCHES, patch_bytes
from patch_smali import GENERATE, MODEL_PICKER_METHOD, MODEL_PICKER_FILTER, patch_model_picker, apply
from android_checks import (PACKAGE, PICKERS, assistant_reply, fusion, generation_completed,
                            gpu_offloaded, has_package, imported, position)

PICKER = '''<hierarchy><node package="com.google.android.documentsui" text="Images" enabled="true" bounds="[0,0][30,30]"/>
<node package="com.google.android.documentsui" text="RECENT FILES" enabled="true" bounds="[0,30][90,60]"/>
<node package="com.google.android.documentsui" text="tiny-llava.gguf" enabled="true" bounds="[20,100][100,140]"/>
<node package="com.google.android.documentsui" text="Select all" enabled="true" bounds="[0,160][90,190]"/>
</hierarchy>'''


def test_saf_never_counts_as_app_or_chat_reply():
    assert has_package(PICKER, PICKERS)
    assert not has_package(PICKER, {PACKAGE})
    assert position(PICKER, text="Images", package={PACKAGE}) is None
    with pytest.raises(AssertionError):
        assistant_reply([{"id": "1", "modelPath": "m", "messages": []}], "1", "Ola")
    assert not generation_completed("REPLY: Images\nREPLY: Audio\nRECENT FILES")


def test_picker_selection_is_exact_not_select_all():
    assert position(PICKER, text="Select", package=PICKERS) is None
    assert position(PICKER, text="tiny-llava.gguf", package=PICKERS) == (60, 120)
    assert position(PICKER, text="tiny", package=PICKERS, contains=True) == (60, 120)


def test_disabled_or_invisible_control_not_tapped():
    assert position('<hierarchy><node text="Open" enabled="false" bounds="[0,0][30,30]"/></hierarchy>', text="Open") is None
    assert position('<hierarchy><node text="Open" enabled="true" bounds="[0,0][0,0]"/></hierarchy>', text="Open") is None


def models():
    # Real vision models commonly have architecture=llama, NOT llava.
    return [{"id": "v", "fileName": "vision.gguf", "path": "/v", "architecture": "llama",
             "mmprojPath": "/p", "multimodal": True},
            {"id": "p", "fileName": "mmproj.gguf", "path": "/p", "architecture": "clip"}]


def test_fusion_uses_imported_paths_not_architecture_guess():
    assert fusion(models(), "vision.gguf", "mmproj.gguf") == ("v", "/v", "/p")


@pytest.mark.parametrize("value", [None, "", "null", "/wrong"])
def test_fusion_missing_wrong_projector_fails(value):
    data = models()
    data[0]["mmprojPath"] = value
    with pytest.raises(AssertionError):
        fusion(data, "vision.gguf", "mmproj.gguf")


@pytest.mark.parametrize("data", [[], {}, [{"fileName": "vision.gguf"}], models() + [models()[0]]])
def test_import_missing_or_duplicate_does_not_pass(data):
    with pytest.raises(AssertionError):
        imported(data, "vision.gguf")


def test_reply_requires_correct_chat_prompt_role_and_order():
    data = [{"id": "c", "modelPath": "/model", "messages": [
        {"role": "assistant", "content": "Old reply"},
        {"role": "user", "content": "Ola"}]}]
    with pytest.raises(AssertionError):
        assistant_reply(data, "c", "Ola")
    data[0]["messages"].append({"role": "assistant", "content": "Olá!"})
    assert assistant_reply(data, "c", "Ola") == "Olá!"
    with pytest.raises(AssertionError):
        assistant_reply(data, "other", "Ola")


def test_generation_failure_overrides_success_marker():
    assert generation_completed("GGUF_REPAIR_GENERATION_OK")
    for failure in ["GGUF_REPAIR_GENERATION_FAILED", "FATAL EXCEPTION", "Fatal signal 11"]:
        with pytest.raises(AssertionError):
            generation_completed("GGUF_REPAIR_GENERATION_OK\n" + failure)


def test_vulkan_library_loading_is_not_gpu_inference():
    assert not gpu_offloaded("loaded libggml-vulkan.so; SwiftShader; offloaded 0/24 layers to GPU")
    assert gpu_offloaded("llama_model_load: offloaded 12/24 layers to GPU")


def test_zip_rebuild_strips_signatures_preserves_resources_and_alignment(tmp_path):
    orig, fixed = tmp_path / "original.apk", tmp_path / "fixed.apk"
    with zipfile.ZipFile(orig, "w") as z:
        z.writestr("classes.dex", b"original dex")
        z.writestr("resources.arsc", b"binary resources")
        info = zipfile.ZipInfo("assets/a")
        info.extra = b"\0\0"  # zipalign-style old padding must not corrupt new extra fields
        z.writestr(info, b"12345")
        z.writestr("lib/arm64-v8a/libaijni.so", b"unchanged library", zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/CERT.RSA", b"obsolete signature")
    rebuild_zip(orig, b"new dex", fixed)
    verify_alignment(fixed)
    verify_payload(orig, fixed)
    with zipfile.ZipFile(fixed) as z:
        assert z.read("classes.dex") == b"new dex"
        assert "META-INF/CERT.RSA" not in z.namelist()


def test_unknown_dex_fails_even_without_assert_statements():
    with pytest.raises(ValueError, match="DEX desconhecido"):
        patch_bytes(bytes(90000))


def test_original_dex_patches_and_checksums():
    path = ROOT / ".cache/gguf/GGUF-Chat.apk"
    if not path.exists():
        pytest.skip("Original APK fixture not downloaded")
    with zipfile.ZipFile(path) as z:
        original = z.read("classes.dex")
    repaired = patch_bytes(original)
    assert len(repaired) == len(original)
    assert repaired[12:32] == hashlib.sha1(repaired[32:]).digest()
    assert struct.unpack_from("<I", repaired, 8)[0] == zlib.adler32(repaired[12:]) & 0xFFFFFFFF
    for offset, old, new, _ in PATCHES:
        assert repaired[offset:offset + len(bytes.fromhex(new))] == bytes.fromhex(new)
    with pytest.raises(ValueError):
        patch_bytes(repaired)


def test_service_check_inserted_inside_original_exception_handler(tmp_path):
    app = tmp_path / "smali/com/ggufchat/app"
    app.mkdir(parents=True)
    (app / 'MainActivity.smali').write_text(MODEL_PICKER_METHOD + '\n' + MODEL_PICKER_FILTER + '\n.end method')
    write_chat_access_fixture(app)
    (app / "Native.smali").write_text('    const-string v0, "aijni"')
    service = app / "GenerationService.smali"
    service.write_text(":try_start_0\n" + GENERATE + ":try_end_0\n.catch Ljava/lang/Exception;\n")
    apply(tmp_path)
    text = service.read_text()
    assert text.index("move-result v6") < text.index(":try_end_0")
    assert "GenerationResult;->check(ZJ)V" in text
    with pytest.raises(ValueError):
        apply(tmp_path)


def test_runner_propagates_suite_failure(tmp_path):
    adb = tmp_path / "adb"
    adb.write_text('#!/bin/sh\ncase "$*" in *sys.boot_completed*) echo 1;; *ro.product.cpu.abi*) echo x86_64;; esac\n')
    python = tmp_path / "python3"
    python.write_text("#!/bin/sh\nexit 17\n")
    adb.chmod(0o755)
    python.chmod(0o755)
    import os
    env = dict(os.environ, PATH=str(tmp_path) + ":" + os.environ["PATH"],
               ANDROID_SERIAL="emulator-5554", GGUF_TEST_MODEL="real.gguf")
    result = subprocess.run(["bash", ".github/emu-test-x86.sh"], cwd=ROOT, env=env)
    assert result.returncode == 17


def test_android_suite_rejects_physical_device_before_adb():
    result = subprocess.run([sys.executable, "scripts/test_android.py", "--serial", "phone",
                             "--apk", "a.apk", "--model", "m.gguf", "--allow-data-reset"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "emulador descartável" in result.stderr


@pytest.mark.parametrize('first_result', ['ok', 'command-failure', 'wrong-hash'])
def test_original_download_is_binary_and_verified(tmp_path, monkeypatch, first_result):
    import fetch_original
    payload = b'original APK fixture'
    monkeypatch.setattr(fetch_original, 'DEST', tmp_path / 'original.apk')
    monkeypatch.setattr(fetch_original, 'SHA256', hashlib.sha256(payload).hexdigest())
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'curl':
            if first_result == 'command-failure':
                raise subprocess.CalledProcessError(1, command)
            Path(command[-1]).write_bytes(payload if first_result == 'ok' else b'bad data')
        else:
            assert 'Accept: application/vnd.github.raw' in command
            kwargs['stdout'].write(payload)
    monkeypatch.setattr(fetch_original.subprocess, 'run', run)
    fetch_original.main()
    assert fetch_original.DEST.read_bytes() == payload
    assert len(calls) == (1 if first_result == 'ok' else 2)
    assert not fetch_original.DEST.with_suffix('.part').exists()


def test_adb_error_includes_original_command_diagnostics(tmp_path, monkeypatch):
    from test_android import Android
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 255, stdout=b'', stderr=b'Unknown option: --activity-new-task')
    monkeypatch.setattr(subprocess, 'run', run)
    device = Android('emulator-5554', tmp_path)
    with pytest.raises(RuntimeError, match='Unknown option'):
        device.shell('am start --activity-new-task')


def test_launch_uses_android_11_compatible_intent_flags(tmp_path, monkeypatch):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    commands = []
    monkeypatch.setattr(device, 'shell', lambda command: commands.append(command) or 'Status: ok')
    monkeypatch.setattr(device, 'wait', lambda *args: True)
    monkeypatch.setattr(device, 'alive', lambda: '123')
    device.launch()
    assert '-f 0x10008000' in commands[0]
    assert '--activity-new-task' not in commands[0]


def test_saf_downloads_selector_ignores_obscured_breadcrumb():
    from android_checks import position
    xml = '''<hierarchy><node package="com.google.android.documentsui"
        text="Downloads" resource-id="com.google.android.documentsui:id/breadcrumb_text"
        enabled="true" bounds="[0,321][303,453]"/>
        <node package="com.google.android.documentsui" text="Downloads"
        resource-id="android:id/title" enabled="true" bounds="[176,657][748,710]"/>
        </hierarchy>'''
    assert position(xml, text="Downloads", resource_id="android:id/title") == (462, 683)


@pytest.mark.parametrize('correct_hash', [True, False])
def test_provision_real_file_requires_matching_device_hash(tmp_path, monkeypatch, correct_hash):
    from test_android import Android
    source = tmp_path / 'model.gguf'
    source.write_bytes(b'unit test transfer payload, not an inference model')
    device = Android('emulator-5554', tmp_path / 'evidence')
    records, commands = {}, []
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    def shell(command):
        commands.append(command)
        if command.startswith('stat '): return '10167'
        if command.startswith('sha256sum '): return (digest if correct_hash else 'wrong') + '  model.gguf'
        return ''
    monkeypatch.setattr(device, 'shell', shell)
    monkeypatch.setattr(device, 'adb', lambda *args, **kwargs: None)
    monkeypatch.setattr(device, 'launch', lambda: None)
    monkeypatch.setattr(device, 'write_private', lambda name, text: records.update({name: json.loads(text)}))
    monkeypatch.setattr(device, 'read_json', lambda name: records['files/' + name])
    if not correct_hash:
        with pytest.raises(AssertionError, match='difere'):
            device.provision_model(source)
        assert not records
    else:
        model = device.provision_model(source)
        assert model['fileName'] == source.name
        assert model['path'].endswith('/files/models/model.gguf')
        assert any('restorecon' in c for c in commands)


@pytest.mark.parametrize('output,valid', [('[]', True), ('', False), ('cat: No such file', False)])
def test_optional_android_store_only_allows_explicit_absence(tmp_path, monkeypatch, output, valid):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    calls = []
    monkeypatch.setattr(device, 'shell', lambda c: calls.append(c) or output)
    if valid:
        assert device.read_json('chats.json', optional=True) == []
    else:
        with pytest.raises(AssertionError, match='JSON inválido'):
            device.read_json('chats.json', optional=True)
    assert "if [ -e " in calls[0]
    assert "else printf '[]'" in calls[0]


def test_model_picker_filter_shows_non_projectors_and_is_guarded():
    original = MODEL_PICKER_METHOD + "\n" + MODEL_PICKER_FILTER + "\n.end method"
    fixed = patch_model_picker(original)
    assert 'if-eqz v1, :cond_0' in fixed  # false contains(mmproj) -> render model
    assert 'if-nez v1, :cond_0' not in fixed
    with pytest.raises(ValueError):
        patch_model_picker(fixed)
    with pytest.raises(ValueError):
        patch_model_picker(original.replace('"mmproj"', '"other"'))


def write_chat_access_fixture(app):
    from patch_chat_access import OWNER, REPAIRS
    from patch_smali import SEND_GUARD
    (app / 'ChatActivity.smali').write_text(
        '.field private loading:Z\n.field private loadPct:I\n'
        '.field private statusLine:Landroid/widget/TextView;\n'
        '.method private updateModelStatus()V\n.end method\n'
        f'.method static synthetic access$400({OWNER})Lcom/ggufchat/app/Chat;\n.end method\n'
        + '.method private onSend()V\n' + SEND_GUARD + '\n.end method\n')
    for name, replacements in REPAIRS.items():
        (app / (name + '.smali')).write_text('\n'.join(replacements))


def test_chat_workers_use_accessors_without_exposing_private_members(tmp_path):
    from patch_chat_access import patch_chat_access, REPAIRS
    write_chat_access_fixture(tmp_path)
    patch_chat_access(tmp_path)
    owner = (tmp_path / 'ChatActivity.smali').read_text()
    assert '.field private loading:Z' in owner
    assert '.method private updateModelStatus()V' in owner
    for name, replacements in REPAIRS.items():
        fixed = (tmp_path / (name + '.smali')).read_text()
        for old, new in replacements.items():
            assert old not in fixed
            assert new in fixed
    with pytest.raises(ValueError):
        patch_chat_access(tmp_path)


def test_send_guard_rejects_null_chat_not_valid_chat():
    from patch_smali import SEND_GUARD, patch_send_guard
    original = '.method private onSend()V\n' + SEND_GUARD + '\n.end method'
    fixed = patch_send_guard(original)
    assert 'if-eqz v0, :cond_8' in fixed
    assert 'if-nez v0, :cond_8' not in fixed
    with pytest.raises(ValueError):
        patch_send_guard(fixed)


@pytest.mark.parametrize('abi', ['arm64-v8a', 'x86_64'])
def test_jni_libdl_fix_preserves_executable_code(tmp_path, abi):
    from patch_native import patch_jni, executable_sections
    original = ROOT / '.cache/gguf/GGUF-Chat.apk'
    if not original.exists() or not (ROOT / '.venv/bin/patchelf').exists():
        pytest.skip('Pinned original APK and patchelf needed for ELF integration test')
    with zipfile.ZipFile(original) as z:
        data = z.read(f'lib/{abi}/libaijni.so')
    result = patch_jni(data, tmp_path / 'jni.so')
    assert executable_sections(result) == executable_sections(data)
    assert result != data
    with pytest.raises(ValueError, match='dependencies differ'):
        patch_jni(result, tmp_path / 'already-patched.so')


@pytest.mark.parametrize('greeting,answer,valid', [
    ('Hello! How can I help?', 'Two plus two is four.', True),
    ('Houston, I am writing about a conference.', '4', False),
    ('Hi there!', 'O que é um idioma?', False),
])
def test_basic_generation_quality_rejects_irrelevant_answers(greeting, answer, valid):
    from android_checks import basic_response_quality
    if valid:
        assert basic_response_quality(greeting, answer)
    else:
        with pytest.raises(AssertionError):
            basic_response_quality(greeting, answer)


@pytest.mark.parametrize('log,expected', [
    ('engine loaded: libllama.so (Vulkan-ready); gpu_offload=0', False),
    ('registered backend Vulkan from libggml-vulkan.so; offloaded 0/30 layers to GPU', False),
    ('offloaded 30/30 layers to GPU', False),
    ('registered backend Vulkan from libggml-vulkan.so; offloaded 30/30 layers to GPU', True),
])
def test_vulkan_requires_initialized_backend_and_positive_offload(log, expected):
    from android_checks import vulkan_offloaded
    assert vulkan_offloaded(log) is expected


def test_vulkan_mode_cannot_be_hidden_by_cpu_generation_only():
    result = subprocess.run([sys.executable, 'scripts/test_android.py', '--serial', 'emulator-5554',
                             '--apk', 'a.apk', '--model', 'm.gguf', '--generation-only', '--vulkan-only'],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'not allowed with argument' in result.stderr


def test_send_can_preserve_backend_preload_logs(tmp_path, monkeypatch):
    from test_android import Android
    d = Android('emulator-5554', tmp_path)
    commands = []
    monkeypatch.setattr(d, 'adb', lambda *a: commands.append(a))
    monkeypatch.setattr(d, 'shell', lambda c: None)
    monkeypatch.setattr(d, 'tap', lambda **k: None)
    d.send('Hello', clear_log=False)
    assert not commands
    d.send('Hello')
    assert commands == [('logcat', '-c')]


def test_native_diagnostics_load_before_jni_and_reject_double_patch():
    from patch_smali import patch_native_logging
    original = '    const-string v0, "aijni"\n    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V'
    fixed = patch_native_logging(original)
    assert fixed.index('"ggufdiagnostics"') < fixed.index('"aijni"')
    assert fixed.count('->loadLibrary') == 2
    with pytest.raises(ValueError):
        patch_native_logging(fixed)


def test_diagnostic_library_is_explicit_and_payload_checked(tmp_path):
    from build_diagnostics import DIAGNOSTIC_ENTRIES
    original, rebuilt = tmp_path / 'orig.apk', tmp_path / 'fixed.apk'
    with zipfile.ZipFile(original, 'w') as z:
        z.writestr('classes.dex', b'dex')
        z.writestr('lib/x86_64/libggml-vulkan.so', b'unchanged real backend')
    additions = {name: b'compiled diagnostic helper fixture' for name in DIAGNOSTIC_ENTRIES}
    rebuild_zip(original, b'dex2', rebuilt, additions)
    verify_payload(original, rebuilt, additions)
    with pytest.raises(ValueError):
        verify_payload(original, rebuilt, {name: b'wrong' for name in additions})
    with pytest.raises(ValueError):
        rebuild_zip(original, b'dex2', rebuilt, {'lib/x86_64/unapproved.so': b'bad'})


def test_diagnostics_requires_pinned_ndk(tmp_path, monkeypatch):
    from build_diagnostics import build_diagnostics
    monkeypatch.setenv('ANDROID_NDK_HOME', str(tmp_path))
    (tmp_path / 'source.properties').write_text('Pkg.Revision = 0.0.0')
    with pytest.raises(ValueError, match='27.2.12479018'):
        build_diagnostics(tmp_path)


def test_native_stderr_forwarding_preserves_fragments_and_long_lines(tmp_path):
    exe = tmp_path / 'diagnostics-test'
    subprocess.run(['gcc', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror',
                    '-Itests/native', 'tests/native/diagnostics_test.c', '-pthread', '-ldl',
                    '-o', str(exe)], cwd=ROOT, check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout.splitlines() == ['fragment continued', '100% literal',
                                          'x' * 3000, 'x' * 3000, 'x' * 1000, 'EOF tail']
