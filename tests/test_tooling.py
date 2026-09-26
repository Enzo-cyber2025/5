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
                            gpu_offloaded, has_package, imported, position, unified_vision)

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


def unificado():
    """O par como a importação ATUAL entrega: um GGUF físico, sem projetor solto."""
    return [{"id": "u", "fileName": "abc-unified.gguf", "path": "/models/abc-unified.gguf",
             "mmprojPath": "/models/abc-unified.gguf", "multimodal": True,
             "capability": "VISION_SINGLE_GGUF"}]


def test_unified_vision_accepts_the_single_physical_file_the_app_writes():
    unidade = unified_vision(unificado())
    assert unidade["id"] == "u" and unidade["path"] == unidade["mmprojPath"]


@pytest.mark.parametrize("data", [
    [],                                              # biblioteca vazia
    models(),                                        # formato legado: dois registros
    [{"id": "x", "path": "/x", "mmprojPath": None, "multimodal": False}],   # o FAIL real
    [{"id": "x", "path": "/x", "mmprojPath": "/x", "multimodal": True,
      "capability": "IMAGE_TOKENS_ONLY"}],           # marcado multimodal sem pesos de visão
])
def test_unified_vision_rejects_anything_that_is_not_one_unified_pair(data):
    with pytest.raises(AssertionError):
        unified_vision(data)


def test_pair_import_proves_the_app_unified_the_two_files(tmp_path):
    """Duas seleções separadas não vinculam nada — o teste tem que exigir a do app.

    Rodada 36258711211: o caminho antigo (importar o GGUF de visão e depois o
    projetor) deixou `mmprojPath: null`, `multimodal: false` e derrubou a fase do
    emulador. O que vale é a unificação atômica registrada pelo aplicativo.
    """
    harness = (ROOT / "scripts/test_android.py").read_text()
    assert "GGUF_PHYSICAL_UNIFICATION_OK" in harness
    assert "select_exact_documents(self, [vision.name, projector.name])" in harness


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
    ('Hello!', 'Two + two = four.', True),
    ('Hello!', 'Two + two = five.', False),
    ('Hi!', 'Two plus two is a number multiplied by itself.', False),
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
    # O envio confere o foco do campo antes de digitar: a tela de mentira responde
    # com o campo focado e o botão Enviar, sem tocar no adb de verdade.
    monkeypatch.setattr(d, 'ui', lambda: '<hierarchy><node package="com.ggufchat.app" '
                        'class="android.widget.EditText" text="" focused="true" enabled="true" '
                        'bounds="[0,0][10,10]" /><node package="com.ggufchat.app" '
                        'class="android.widget.Button" text="Enviar" enabled="true" '
                        'bounds="[0,0][10,10]" /></hierarchy>')
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
    with pytest.raises(ValueError, match='28.2.13676358'):
        build_diagnostics(tmp_path)


def test_native_stderr_forwarding_preserves_fragments_and_long_lines(tmp_path):
    exe = tmp_path / 'diagnostics-test'
    subprocess.run(['gcc', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror',
                    '-Itests/native', 'tests/native/diagnostics_test.c', '-pthread', '-ldl',
                    '-o', str(exe)], cwd=ROOT, check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout.splitlines() == [
        'Emulator-only GGML_VK_VISIBLE_DEVICES=0; software Vulkan is not hardware acceleration',
        'fragment continued', '100% literal',
                                          'x' * 3000, 'x' * 3000, 'x' * 1000, 'EOF tail']


@pytest.mark.parametrize('sdk,granted', [(30, False), (33, True), (35, True)])
def test_notification_grant_after_reset_is_api_scoped(tmp_path, monkeypatch, sdk, granted):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    calls = []
    def shell(command):
        calls.append(command)
        return str(sdk) if command.startswith('getprop') else ''
    monkeypatch.setattr(device, 'shell', shell)
    assert device.grant_test_notifications() == sdk
    assert calls == ['getprop ro.build.version.sdk'] + (
        [f'pm grant {PACKAGE} android.permission.POST_NOTIFICATIONS'] if granted else [])


@pytest.mark.parametrize('tail,expected', [
    ('llama_model_loader: loaded meta data\nCPU model loaded', False),
    ('llama_model_loader: loaded meta data\noffloaded 0/31 layers to GPU', False),
    ('llama_model_loader: loaded meta data\noffloaded 31/31 layers to GPU', True),
    ('offloaded 0/31 layers to GPU', False),
])
def test_abandoned_vulkan_attempt_does_not_approve_cpu_fallback(tail, expected):
    from android_checks import vulkan_offloaded
    log = ('registered backend Vulkan\nllama_model_loader: loaded meta data\n'
           'offloaded 31/31 layers to GPU\ncontext failed\n' + tail)
    assert vulkan_offloaded(log) is expected


def test_chat_navigation_retries_same_row_not_creation(tmp_path, monkeypatch):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    clicks = []
    attempts = []
    monkeypatch.setattr(device, 'tap', lambda **kw: clicks.append(kw))
    monkeypatch.setattr(device, 'alive', lambda: '123')
    monkeypatch.setattr(device, 'ui', lambda: '<hierarchy><node package="com.ggufchat.app" '
                        'text="existing" enabled="true" bounds="[0,0][100,100]"/></hierarchy>')
    def wait(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise AssertionError('input not ready')
        return (10, 20)
    monkeypatch.setattr(device, 'wait', wait)
    device.open_existing_chat('existing')
    assert clicks == [dict(text='existing', package={PACKAGE})] * 2


def test_chat_navigation_does_not_retry_native_crash(tmp_path, monkeypatch):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    clicks = []
    monkeypatch.setattr(device, 'tap', lambda **kw: clicks.append(kw))
    def failed(*args, **kwargs):
        raise AssertionError('crash or navigation failure')
    monkeypatch.setattr(device, 'wait', failed)
    monkeypatch.setattr(device, 'alive', failed)
    with pytest.raises(AssertionError):
        device.open_existing_chat('existing')
    assert len(clicks) == 0  # fail before tapping if the process is already absent


def test_chat_navigation_rejects_automatic_process_restart(tmp_path, monkeypatch):
    from test_android import Android
    device = Android('emulator-5554', tmp_path)
    pids = iter(['123', '456'])
    monkeypatch.setattr(device, 'alive', lambda: next(pids))
    monkeypatch.setattr(device, 'tap', lambda **kwargs: None)
    monkeypatch.setattr(device, 'wait', lambda fn, *args, **kwargs: fn())
    with pytest.raises(RuntimeError, match='reiniciou'):
        device.open_existing_chat('existing')
    assert device.generation_pid == '123'


@pytest.mark.parametrize('original_exit,original_preserved,valid', [(1, False, True), (0, True, False), (139, False, False)])
def test_runtime_probe_requires_specific_negative_and_positive_controls(tmp_path, monkeypatch,
                                                                       original_exit, original_preserved, valid):
    from test_android import Android
    device = Android('emulator-5554', tmp_path / 'evidence')
    (tmp_path / 'runtime-provenance.json').write_text('{}')
    monkeypatch.setattr(device, 'shell', lambda *a, **kw: '')
    def adb(*args, **kwargs):
        if not kwargs.get('with_status'):
            return ''
        old = 'original-' in args[-1]
        return subprocess.CompletedProcess(args, original_exit if old else 0,
            stdout=json.dumps({'pthread_mutexattr_size': 8,
                'callee_saved_preserved': original_preserved if old else True}).encode(), stderr=b'')
    monkeypatch.setattr(device, 'adb', adb)
    if valid:
        device.check_cpp_runtime(tmp_path)
    else:
        with pytest.raises(AssertionError):
            device.check_cpp_runtime(tmp_path)
    assert (device.evidence / 'runtime-regression.json').exists()


def test_runtime_replacement_cannot_change_vulkan_code(tmp_path):
    from replace_cpp_runtime import RUNTIME_ENTRIES
    original, fixed = tmp_path / 'original.apk', tmp_path / 'fixed.apk'
    with zipfile.ZipFile(original, 'w') as z:
        z.writestr('classes.dex', b'dex')
        for entry in RUNTIME_ENTRIES:
            z.writestr(entry, b'old runtime')
        z.writestr('lib/x86_64/libggml-vulkan.so', b'original vulkan')
    runtimes = {name: b'official runtime fixture' for name in RUNTIME_ENTRIES}
    rebuild_zip(original, b'dex2', fixed, runtimes)
    verify_payload(original, fixed, runtimes)
    with zipfile.ZipFile(fixed) as z:
        assert z.read('lib/x86_64/libggml-vulkan.so') == b'original vulkan'
    with pytest.raises(ValueError):
        rebuild_zip(original, b'dex2', fixed, {'lib/x86_64/libggml-vulkan.so': b'not allowed'})


def test_promoted_vulkan_alias_never_invents_feature_support(tmp_path):
    source = tmp_path / 'policy.c'
    source.write_text('''#include <assert.h>
#include "vulkan_compat_policy.h"
int main(void) {
    const unsigned v10 = 1u << 22, v11 = v10 | (1u << 12), v13 = v10 | (3u << 12);
    assert(gguf_core_16bit_alias(v11, 1, 0));
    assert(gguf_core_16bit_alias(v13, 1, 0));
    assert(!gguf_core_16bit_alias(v10, 1, 0));
    assert(!gguf_core_16bit_alias(v13, 0, 0));
    assert(!gguf_core_16bit_alias(v13, 1, 1));
    assert(!gguf_core_16bit_alias(v10, 0, 1));
    return 0;
}
''')
    binary = tmp_path / 'policy'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT / 'apk-fix/native'), str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_vulkan_import_adapter_preserves_pinned_native_code():
    from patch_vulkan import patch_imports, VULKAN_ENTRIES
    from patch_native import executable_sections
    original = ROOT / '.cache/gguf/GGUF-Chat.apk'
    if not original.exists():
        pytest.skip('pinned original APK not fetched')
    with zipfile.ZipFile(original) as z:
        for name in VULKAN_ENTRIES:
            old = z.read(name)
            fixed = patch_imports(old)
            assert executable_sections(old) == executable_sections(fixed)
            assert len(old) == len(fixed)
            assert sum(a != b for a, b in zip(old, fixed)) == 14
            with pytest.raises(ValueError):
                patch_imports(fixed)


@pytest.mark.parametrize('abi', ['x86_64', 'arm64-v8a'])
@pytest.mark.parametrize('budget', [1, 2, 3, 128])
def test_native_token_budget_is_success_only_after_all_decodes(abi, budget):
    sys.path.insert(0, str(ROOT / 'tests/native'))
    from emulate_generation import execute
    from patch_generation import patch_generation
    original = ROOT / '.cache/gguf/GGUF-Chat.apk'
    if not original.exists():
        pytest.skip('pinned APK not fetched')
    with zipfile.ZipFile(original) as z:
        data = z.read(f'lib/{abi}/libaijni.so')
    old = execute(data, budget=budget)
    new = execute(patch_generation(data), budget=budget)
    assert old == dict(sampled=budget, tokens=budget, decodes=budget + 1,
                       done=0, done_calls=1, result=0)
    assert new == dict(sampled=budget, tokens=budget, decodes=budget + 1,
                       done=1, done_calls=1, result=1)
    # Especially important: error on the final decode must never be converted
    # to success merely because the token budget has also been exhausted.
    for failure in range(2, budget + 2):
        failed = execute(patch_generation(data), budget=budget, fail_decode_at=failure)
        assert failed['result'] == failed['done'] == 0
        assert failed['decodes'] == failure
        assert failed['tokens'] == failure - 1


@pytest.mark.parametrize('abi', ['x86_64', 'arm64-v8a'])
@pytest.mark.parametrize('scenario,expected', [
    ({'eos_at': 1}, 1), ({'eos_at': 2}, 1), ({'eos_at': 3}, 1),
    ({'cancel_at': 1}, 0), ({'cancel_at': 2}, 0),
    ({'fail_decode_at': 1}, 0), ({'invalid_handle': True}, 0),
    ({'budget': 0}, 0), ({'budget': -1}, 0),
])
def test_native_completion_keeps_eog_errors_and_cancellation(abi, scenario, expected):
    sys.path.insert(0, str(ROOT / 'tests/native'))
    from emulate_generation import execute
    from patch_generation import patch_generation
    original = ROOT / '.cache/gguf/GGUF-Chat.apk'
    if not original.exists():
        pytest.skip('pinned APK not fetched')
    with zipfile.ZipFile(original) as z:
        data = z.read(f'lib/{abi}/libaijni.so')
    old, new = execute(data, **scenario), execute(patch_generation(data), **scenario)
    assert old == new
    assert new['result'] == expected


@pytest.mark.parametrize('abi', ['x86_64', 'arm64-v8a'])
def test_generation_patch_is_pinned_and_bounded(abi):
    from patch_generation import patch_generation, PATCHES
    original = ROOT / '.cache/gguf/GGUF-Chat.apk'
    if not original.exists():
        pytest.skip('pinned APK not fetched')
    with zipfile.ZipFile(original) as z:
        data = z.read(f'lib/{abi}/libaijni.so')
    patched = patch_generation(data)
    machine = struct.unpack_from('<H', data, 18)[0]
    allowed = {i for offset, old, new in PATCHES[machine] for i in range(offset, offset + len(old))}
    assert len(patched) == len(data)
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(data, patched)))
    for bad in (patched, data[:-1], data + b'changed'):
        with pytest.raises(ValueError):
            patch_generation(bad)


def test_image_crops_are_not_source_image_count():
    from android_checks import image_prefill_records
    crop = 'GGUF_IMAGE_EVALUATED tokens=64 backend=Vulkan\n'
    one = 'GGUF_MEDIA_PREFILL images=1 tokens=380 positions=380\n'
    two = 'GGUF_MEDIA_PREFILL images=2 tokens=760 positions=760\n'
    assert len(image_prefill_records(crop * 3 + one, 1)) == 3
    assert len(image_prefill_records(crop * 6 + two, 2)) == 6
    for log, count in [(crop * 3 + one, 2), (crop * 3 + two, 1),
                       (one, 1), (crop, 1), (crop + two, 2),
                       (crop + one + one, 1), (crop.replace('64', '0') + one, 1)]:
        with pytest.raises(AssertionError):
            image_prefill_records(log, count)


def test_exact_saf_selection_ignores_recent_diagnostic_xml():
    from android_checks import select_exact_documents

    class Picker:
        def __init__(self):
            self.selected = []

        def ui(self):
            names = ['gguf-test-ui.xml', 'model.gguf', 'projector.gguf']
            # Match named item_root/selected accessibility state. Selection
            # changes the toolbar height: subsequent taps need fresh row Y.
            rows = []
            for i, name in enumerate(names):
                top = i * 100 + (12 if self.selected else 0)
                rows.append(
                    f'<node resource-id="com.android.documentsui:id/item_root" selected="{str(name in self.selected).lower()}" '
                    f'bounds="[0,{top}][720,{top+40}]">'
                    f'<node text="{name}" enabled="true" package="com.android.documentsui" bounds="[80,{top}][600,{top+40}]"/></node>')
            return '<hierarchy>' + ''.join(rows) + f'<node text="{len(self.selected)} selected" enabled="true" package="com.android.documentsui" bounds="[0,0][100,40]"/></hierarchy>'

        def shell(self, command):
            expected = 'input tap 48 120' if not self.selected else 'input tap 48 232'
            assert command == expected
            self.selected.append('model.gguf' if not self.selected else 'projector.gguf')

        def tap(self, *, text, package):
            raise AssertionError('A selection gesture must not open a document')

        def wait(self, predicate, description, timeout=None):
            assert predicate(), description

    picker = Picker()
    select_exact_documents(picker, ['model.gguf', 'projector.gguf'])
    assert picker.selected == ['model.gguf', 'projector.gguf']
