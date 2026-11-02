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
