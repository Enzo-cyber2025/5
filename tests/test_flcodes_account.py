"""Tests for the Play Store identity preflight (``flcodes account``)."""
from __future__ import annotations

import json
import pathlib

import pytest

from flcodes import account as account_mod


GOOD = ("tester.familylink.2026@gmail.com", "Zx9-quiet-heron-77")


def test_missing_both_fails():
    findings = account_mod.check("", "")
    assert account_mod.blocked(findings)
    assert sum(1 for f in findings if f.level == account_mod.FAIL) == 2


def test_a_good_pair_passes():
    findings = account_mod.check(*GOOD)
    assert not account_mod.blocked(findings)
    assert "usable" in account_mod.render(findings)


@pytest.mark.parametrize("email", ["not-an-email", "you@example.com", "test@test.com", "user@"])
def test_bad_or_placeholder_addresses_fail(email):
    assert account_mod.blocked(account_mod.check(email, GOOD[1]))


@pytest.mark.parametrize("password", ["short", "CHANGEME", "password"])
def test_bad_passwords_fail(password):
    assert account_mod.blocked(account_mod.check(GOOD[0], password))


def test_a_dollar_in_the_password_is_only_a_warning():
    findings = account_mod.check(GOOD[0], "Zx9-quiet-heron-77$a")
    assert not account_mod.blocked(findings)
    assert any(f.level == account_mod.WARN and "metacharacter" in f.message
               for f in findings)


def test_two_step_and_device_check_are_always_flagged():
    messages = " ".join(f.message for f in account_mod.check(*GOOD))
    assert "2-step verification" in messages
    assert "device check" in messages


def test_json_is_machine_readable():
    payload = json.loads(account_mod.as_json(account_mod.check(*GOOD)))
    assert payload["usable"] is True
    assert {f["level"] for f in payload["findings"]} <= {"ok", "warn", "fail"}


def test_every_failure_carries_a_fix():
    for item in account_mod.check("", ""):
        assert item.level != account_mod.FAIL or item.fix


def test_env_is_the_default_source(monkeypatch):
    monkeypatch.setenv("FLCODES_GPLAY_EMAIL", GOOD[0])
    monkeypatch.setenv("FLCODES_GPLAY_PASSWORD", GOOD[1])
    assert not account_mod.blocked(account_mod.check())


def test_the_howto_says_what_is_not_done():
    text = account_mod.howto()
    assert "NÃO faz: criar conta Google" in text
    assert "setup_play_secrets.sh" in text
    assert "Cloud Identity" in text


def test_cli_check_exit_codes(monkeypatch, capsys):
    from flcodes import cli

    monkeypatch.delenv("FLCODES_GPLAY_EMAIL", raising=False)
    monkeypatch.delenv("FLCODES_GPLAY_PASSWORD", raising=False)
    assert cli.main(["account", "check"]) == 1
    assert "verdict" in capsys.readouterr().out

    monkeypatch.setenv("FLCODES_GPLAY_EMAIL", GOOD[0])
    monkeypatch.setenv("FLCODES_GPLAY_PASSWORD", GOOD[1])
    assert cli.main(["account", "check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["usable"] is True


def test_cli_howto(capsys):
    from flcodes import cli

    assert cli.main(["account", "howto"]) == 0
    assert "conta descartável" in capsys.readouterr().out.lower()


SCRIPT = (pathlib.Path(__file__).resolve().parents[1] / "family-link-codes"
          / "tools" / "setup_play_secrets.sh")


def _run_script(tmp_path, env, *args):
    import os
    import subprocess

    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    calls = tmp_path / "gh-calls.log"
    gh = fake / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "gh $*" >> {calls}\n'
        'case "$1 $2" in\n'
        '  "auth status") exit 0 ;;\n'
        '  "repo view") echo "owner/repo" ;;\n'
        '  "secret set") cat > /dev/null ;;\n'
        'esac\nexit 0\n'
    )
    gh.chmod(0o755)
    full_env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", **env)
    result = subprocess.run(["bash", str(SCRIPT), *args], env=full_env,
                            capture_output=True, text=True)
    calls_text = calls.read_text() if calls.exists() else ""
    return result, calls_text


def test_the_script_refuses_a_short_password(tmp_path):
    result, calls = _run_script(tmp_path, {"FLCODES_GPLAY_EMAIL": "a@b.com",
                                           "FLCODES_GPLAY_PASSWORD": "abc"})
    assert result.returncode == 2
    assert "gh secret set" not in calls


def test_the_script_refuses_a_missing_pair(tmp_path):
    result, calls = _run_script(tmp_path, {})
    assert result.returncode == 2
    assert "read -rs FLCODES_GPLAY_PASSWORD" in result.stdout


def test_dry_run_writes_nothing(tmp_path):
    result, calls = _run_script(tmp_path, {"FLCODES_GPLAY_EMAIL": GOOD[0],
                                           "FLCODES_GPLAY_PASSWORD": GOOD[1]}, "--dry-run")
    assert result.returncode == 0
    assert "gh secret set" not in calls


def test_the_script_publishes_both_secrets_without_printing_the_password(tmp_path):
    result, calls = _run_script(tmp_path, {"FLCODES_GPLAY_EMAIL": GOOD[0],
                                           "FLCODES_GPLAY_PASSWORD": GOOD[1]})
    assert result.returncode == 0
    assert "gh secret set FLCODES_GPLAY_EMAIL --repo owner/repo" in calls
    assert "gh secret set FLCODES_GPLAY_PASSWORD --repo owner/repo" in calls
    assert GOOD[1] not in result.stdout + result.stderr


PLAY_RUN = (pathlib.Path(__file__).resolve().parents[1] / "family-link-codes"
            / "tools" / "play_run.sh")
REAP = (pathlib.Path(__file__).resolve().parents[1] / "family-link-codes"
        / "tools" / "play_store_reap.sh")


def _run_play_run(tmp_path, env, *args):
    import os
    import subprocess

    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    calls = tmp_path / "calls.log"
    (fake / "gh").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "gh $*" >> {calls}\n'
        'case "$1 $2" in\n'
        '  "auth status") exit 0 ;;\n'
        '  "repo view") echo "owner/repo" ;;\n'
        '  "secret set") cat > /dev/null ;;\n'
        '  "workflow run") exit 1 ;;\n'
        'esac\nexit 0\n'
    )
    (fake / "gh").chmod(0o755)
    full_env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", **env)
    result = subprocess.run(["bash", str(PLAY_RUN), *args], env=full_env,
                            capture_output=True, text=True, input="")
    return result, (calls.read_text() if calls.exists() else "")


def test_play_run_refuses_a_bad_pair_and_publishes_nothing(tmp_path):
    result, calls = _run_play_run(tmp_path, {"FLCODES_GPLAY_EMAIL": "a@b.com",
                                             "FLCODES_GPLAY_PASSWORD": "abc"})
    assert result.returncode == 1
    assert "secret set" not in calls
    assert "nothing was published" in result.stderr


def test_play_run_check_validates_without_publishing(tmp_path):
    result, calls = _run_play_run(tmp_path, {"FLCODES_GPLAY_EMAIL": GOOD[0],
                                             "FLCODES_GPLAY_PASSWORD": GOOD[1]}, "--check")
    assert result.returncode == 0
    assert "secret set" not in calls
    assert "nothing was published" in result.stdout


def test_play_run_without_credentials_says_what_to_set(tmp_path):
    result, _calls = _run_play_run(tmp_path, {"FLCODES_GPLAY_EMAIL": "",
                                              "FLCODES_GPLAY_PASSWORD": ""})
    assert result.returncode == 1
    assert "FLCODES_GPLAY_EMAIL" in result.stderr


def test_the_reap_script_names_the_signin_wall():
    """The four sign-in walls look alike in a screenshot; the script names them."""
    text = REAP.read_text()
    for needle in ("2-step verification", "wrong", "unusual", "disabled",
                   "certified", "sign-in stopped at"):
        assert needle in text
