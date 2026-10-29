"""Tests for the sign-up probe: the classification, not the browser."""
from __future__ import annotations

import importlib.util
import json
import pathlib

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "family-link-codes" / "tools"


def load_probe():
    spec = importlib.util.spec_from_file_location("signup_probe", TOOLS / "google_signup_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_phone_wall_is_named():
    probe = load_probe()
    assert probe.classify("Enter a phone number so we can verify it's you") == "phone"


def test_the_captcha_wall_is_named():
    probe = load_probe()
    assert probe.classify("This is not a robot test. Unusual traffic from your network") == "captcha"


def test_a_secure_browser_block_is_named():
    probe = load_probe()
    assert probe.classify("Couldn't sign you in. This browser or app may not be secure") == "browser"


def test_a_created_account_is_recognised():
    probe = load_probe()
    assert probe.classify("Welcome, Marina — you're all set") == "done"


def test_an_unknown_screen_is_not_mistaken_for_success():
    probe = load_probe()
    assert probe.classify("Create your Google Account — name") == ""


def test_the_identity_is_plausible_and_unique():
    probe = load_probe()
    first, second = probe.random_identity(), probe.random_identity()
    assert "@" not in first["username"]
    assert first["username"] != second["username"]
    assert len(first["password"]) >= 12
    assert any(ch.isdigit() for ch in first["password"])


def test_a_created_account_writes_credentials_private(tmp_path, monkeypatch):
    """The success path must leave a 0600 file and never print the password."""
    probe = load_probe()
    identity = probe.random_identity()
    out = tmp_path / "signup"
    out.mkdir()
    (out / "credentials.json").write_text(
        json.dumps({"email": "a@b.com", "password": identity["password"]}))
    (out / "credentials.json").chmod(0o600)
    assert (out / "credentials.json").stat().st_mode & 0o777 == 0o600


def test_the_probe_never_has_a_captcha_solver():
    """Guard rail: nothing here may try to defeat a protection."""
    source = (TOOLS / "google_signup_probe.py").read_text()
    for forbidden in ("2captcha", "anticaptcha", "capsolver", "audio_challenge",
                      "solve_captcha", "sms-activate", "smspool", "proxy="):
        assert forbidden not in source.lower()


def test_the_report_names_the_wall(tmp_path):
    import subprocess
    import sys

    probe = load_probe()
    directory = tmp_path / "signup"
    directory.mkdir()
    (directory / "result.json").write_text(json.dumps({
        "created": False, "verdict": "phone", "email": "",
        "steps": [{"step": 1, "verdict": "", "filled": [1, 2], "clicked_next": True},
                  {"step": 2, "verdict": "phone", "filled": [], "clicked_next": False}],
    }))
    summary = tmp_path / "summary.md"
    out = subprocess.run(
        [sys.executable, str(TOOLS / "signup_report.py"), "--dir", str(directory),
         "--summary-file", str(summary)],
        capture_output=True, text=True)
    assert out.returncode == 0
    assert "phone" in out.stdout
    assert "Google stopped the sign-up at: phone" in out.stdout
    assert "| 2 | `phone` |" in summary.read_text()


def test_the_report_offers_the_next_command_when_an_account_exists(tmp_path):
    import subprocess
    import sys

    directory = tmp_path / "signup"
    directory.mkdir()
    (directory / "result.json").write_text(json.dumps({
        "created": True, "verdict": "created", "email": "x@gmail.com",
        "steps": [{"step": 1, "verdict": "done", "filled": [], "clicked_next": True}],
    }))
    (directory / "credentials.json").write_text('{"email": "x@gmail.com", "password": "s"}')
    out = subprocess.run([sys.executable, str(TOOLS / "signup_report.py"),
                          "--dir", str(directory)], capture_output=True, text=True)
    assert "play_run.sh" in out.stdout
    assert "account-created" in out.stdout


def test_a_missing_result_does_not_crash(tmp_path):
    import subprocess
    import sys

    out = subprocess.run([sys.executable, str(TOOLS / "signup_report.py"),
                          "--dir", str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0
    assert "no result" in out.stdout


def test_a_broken_probe_still_reports(tmp_path, monkeypatch):
    """If playwright or the network dies, result.json must still exist."""
    import subprocess
    import sys

    out = tmp_path / "signup"
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(TOOLS)
    # force the import inside main() to fail without touching the network
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, json;"
         "sys.modules['playwright'] = None;"
         f"sys.argv=['p','--out-dir','{out}'];"
         f"exec(open('{TOOLS}/google_signup_probe.py').read())"],
        capture_output=True, text=True, env=env)
    assert result.returncode == 1
    data = json.loads((out / "result.json").read_text())
    assert data["verdict"] == "probe-error"
    assert data["error"]


def test_the_verbatim_refusal_is_recognised_as_the_wall():
    """This is the exact string Google returned on run 40935535887."""
    probe = load_probe()
    assert probe.classify("Error\\nSorry, we could not create your Google Account.\\nNext") == "blocked"


def test_the_refusal_beats_the_terms_line_on_the_same_page():
    """The refusal page also carries 'Privacy / Terms'; the refusal must win."""
    probe = load_probe()
    page = "Error Sorry, we could not create your Google Account. Next Privacy Terms"
    assert probe.classify(page) == "blocked"
