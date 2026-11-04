from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "apk-fix/java/com/ggufchat/app/TermuxBridge.java"


def test_modes_default_to_disabled_and_are_user_selectable():
    source = BRIDGE.read_text()
    assert 'private static final int MODE_OFF = 0;' in source
    assert 'private static final int MODE_MODERATE = 1;' in source
    assert 'private static final int MODE_COMPLETE = 2;' in source
    assert 'private static final int MODE_COMPLETE_AUTH = 3;' in source
    assert 'getInt(MODE_KEY, MODE_OFF)' in source
    assert 'public static Button settingsButton(Activity activity)' in source
    assert 'Sem Termux' in source and 'Moderado' in source and 'Completo com autorização' in source


def test_moderate_mode_has_a_narrow_single_command_allowlist():
    source = BRIDGE.read_text()
    assert 'selectedMode == MODE_MODERATE && !isModerateCommand(command)' in source
    assert 'command.length() > 256' in source
    assert 'MODERATE_COMMAND.matcher(command.trim()).matches()' in source
    assert 'pwd|date|whoami|uname' in source
    assert 'pkg list-installed' in source


def test_complete_modes_still_require_visible_review_and_authorization():
    source = BRIDGE.read_text()
    assert 'showReview(activity, command, selectedMode)' in source
    assert 'setTitle("Revisar comando do Termux")' in source
    assert 'setPositiveButton("Abrir no Termux"' in source
    assert 'selectedMode == MODE_COMPLETE_AUTH' in source
    assert 'AUTH_PHRASE = "AUTORIZO"' in source
    assert 'confirmPermissionAndRun(activity, command)' in source
    assert 'com.termux.permission.RUN_COMMAND' in source
    assert 'O resultado permanece no Termux' in source
