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
    assert "startService(intent)" in bridge
    # This bridge delegates to a separately installed Termux and exposes code
    # only after the user reviews and confirms it; it is not an embedded shell.
