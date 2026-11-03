from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_termux_handoff_is_explicit_user_confirmed_and_scoped_to_shell_blocks():
    bridge = (ROOT / "apk-fix/java/com/ggufchat/app/TermuxBridge.java").read_text()
    compact_ui = (ROOT / "apk-fix/java/com/ggufchat/app/CompactUi.java").read_text()
    manifest = (ROOT / "apk-fix/attachment_manifest.py").read_text()
    assert "TermuxBridge.chatButton(activity)" in compact_ui
    assert "setPositiveButton(\"Abrir no Termux\"" in bridge
    assert "setNegativeButton(\"Cancelar\"" in bridge
    assert 'setComponent(new ComponentName("com.termux", SERVICE))' in bridge
    assert '"/data/data/com.termux/files/usr/bin/bash"' in bridge
    assert "termux_permission=index('com.termux.permission.RUN_COMMAND')" in manifest
    assert "requestPermissions(new String[]{PERMISSION}, PERMISSION_REQUEST)" in bridge
    assert "TermuxBridge;->permissionResult" in (ROOT / "apk-fix/attachment_patches.py").read_text()
    assert "MAX_COMMAND_CHARS = 6000" in bridge
    assert "assistantCommand(activity)" in bridge
    assert "BARE_COMMAND" in bridge and "bare.indexOf('`') < 0" in bridge
    # Models without native tool/function calling can still return a plain-text
    # one-line command, including the exact bash script invocations used by the
    # requested Termux tasks. Execution remains gated by the review dialog.
    assert "(?:bash|sh|echo|printf" in bridge
    assert r"[^\\r\\n]*" in bridge  # bare text stays a single, reviewed command line
    assert 'setTitle("Revisar comando do Termux")' in bridge
    assert "startService(intent)" in bridge
    # This bridge delegates to a separately installed Termux and exposes code
    # only after the user reviews and confirms it; it is not an embedded shell.


def test_requested_models_use_the_real_reviewed_bridge_not_a_run_as_shell_bypass():
    task = (ROOT / "scripts/test_requested_model_tasks_android.py").read_text()
    workflow = (ROOT / ".github/workflows/requested-model-tasks-android.yml").read_text()
    assert "confirm_in_app_termux_command(device, selected, stage)" in task
    assert "run_in_termux_uid" not in task and '"run-as com.termux' not in task
    assert 'setTitle("Revisar comando do Termux")' in (ROOT / "apk-fix/java/com/ggufchat/app/TermuxBridge.java").read_text()
    assert 'pm revoke {PACKAGE} com.termux.permission.RUN_COMMAND' in task
    assert '"stdout_automatically_returned_to_model": False' in task
    assert ".delivery/GGUF-Chat-mobile-unsigned.apk" in workflow
    assert "emulator-only.p12" in workflow and "NOT FOR RELEASE" in workflow


def test_requested_folder_command_and_description_retry_without_bypassing_the_model():
    task = (ROOT / "scripts/test_requested_model_tasks_android.py").read_text()
    workflow = (ROOT / ".github/workflows/requested-model-tasks-android.yml").read_text()
    assert 'prompts.append("Output only this exact command on one line' in task
    assert 'timeout=360' in task
    assert '"attempts": attempts' in task
    assert 'description_attempts' in task and 'model_describes_actual_folder_contents' in task
    assert 're.search(r"\\b(arquivo|file|pasta|folder)\\b"' in task
    assert 'github.event_name == \'push\' && fromJSON(\'["gemma4-e2b","gemma3-270m"]\')' in workflow


def test_termux_apk_build_uses_current_official_package_mirror():
    build = (ROOT / "tests/android-text-binary/run-build.sh").read_text()
    assert "packages-cf.termux.dev/apt/termux-main stable main" in build
    assert 'rm -f "$PREFIX"/var/lib/apt/lists/*' in build
    assert 'pkg update -y' in build and 'pkg install -y openjdk-21 libc++ aapt2 d8 apksigner' in build


def test_box64_arm64_smoke_test_pins_reviewed_third_party_payload_and_uses_termux_ui():
    installer = (ROOT / "tests/box64-termux/install-box64-arm64.sh").read_text()
    smoke = (ROOT / "scripts/test_box64_termux_arm64.py").read_text()
    workflow = (ROOT / ".github/workflows/box64-termux-arm64.yml").read_text()
    assert 'TAG="v0.4.5-termux.1"' in installer
    assert 'SHA256="0dae8257ac7396db4766721e5e4f317679b2080752d32e90d4e6e6fdfee467cf"' in installer
    assert '"$(uname -m)" != "aarch64"' in installer
    assert '"input", "text", "bash%strun-box64-arm64-test.sh"' in smoke
    assert '"app_mediated_model_handoff": False' in smoke
    assert "arch: arm64-v8a" in workflow
    assert "system-images;android-35;google_apis;arm64-v8a" in workflow


def test_android_harness_runs_app_before_termux_bootstrap_and_recovers_launcher_anr():
    script = (ROOT / "scripts/test_tool_integrations_android.py").read_text()
    main = script[script.index("def main():"):]
    assert main.index('d.adb("install", "-r", "-g", APK') < main.index("d.launch()")
    assert "pm disable-user --user 0 com.google.android.apps.nexuslauncher" in main
    permission_dialog = script[script.index("def permission_dialog():"):script.index("\n    point = d.wait(permission_dialog", script.index("def permission_dialog():"))]
    assert 'position(xml, text=label, package=None)' in permission_dialog
    assert "contains=True" not in permission_dialog
    assert "Android RUN_COMMAND confirmation dialog accepted" in script
    assert 'comando gerado pelo modelo executado no Termux real' in script
    assert main.index("d.launch()") < main.index("set_termux_external_apps(d)")
    android = (ROOT / "scripts/test_android.py").read_text()
    assert "foreground_or_dismiss_launcher_anr" in android
    assert 'position(xml, text="Wait", contains=True, package=None)' in android
    assert "MainActivity em primeiro plano" in android
