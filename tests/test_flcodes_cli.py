"""End-to-end checks of the CLI and the local web UI.

The CLI is exercised as a real subprocess with an isolated ``FLCODES_HOME`` and
passphrase from the environment, so nothing touches the tester's own store.
The web server runs in a thread on port 0; only the local API is called.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "family-link-codes"
sys.path.insert(0, str(PACKAGE))

from flcodes import codes as codes_mod  # noqa: E402
from flcodes.server import make_handler  # noqa: E402
from flcodes.store import Store  # noqa: E402

SECRET = "AItest-only-cli-secret.abcdefghij"  # NOT a real secret
PASSPHRASE = "test-passphrase"


def run_cli(*args: str, home: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "FLCODES_HOME": str(home),
            "FLCODES_PASSPHRASE": PASSPHRASE,
            "PYTHONPATH": str(PACKAGE),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "flcodes.cli", *args],
        cwd=PACKAGE,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def write_capture(home: Path) -> Path:
    path = home / "capture.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        ")]}'\n" + json.dumps({"familyLinkAppConfig": {"androidSharedSecret": SECRET}})
    )
    return path


def test_rea_save_then_generate_end_to_end(tmp_path):
    home = tmp_path / "home"
    capture = write_capture(home)

    harvested = run_cli("rea", "scan", str(capture), "--save", "--label", "pai", home=home)
    assert harvested.returncode == 0, harvested.stderr
    assert "saved:" in harvested.stdout
    assert SECRET not in harvested.stdout

    listing = run_cli("keys", "list", home=home)
    assert listing.returncode == 0
    assert "pai" in listing.stdout
    assert SECRET not in listing.stdout
    assert "AIte…" in listing.stdout

    generated = run_cli("gen", "--label", "pai", "--time", "1700000000", home=home)
    assert generated.returncode == 0, generated.stderr
    assert generated.stdout.strip().splitlines()[0] == codes_mod.generate_code(SECRET, 1700000000).code

    as_json = run_cli("gen", "--json", "--time", "1700028000", home=home)
    assert as_json.returncode == 0
    document = json.loads(as_json.stdout)
    assert document["code"] == codes_mod.generate_code(SECRET, 1700028000).code
    assert document["label"] == "pai"

    day = run_cli("gen", "--day", "2026-10-22", "--out", str(tmp_path / "day.csv"), home=home)
    assert day.returncode == 0, day.stderr
    rows = (tmp_path / "day.csv").read_text().splitlines()
    assert len(rows) == 25  # header + 24 hours (UTC day, no DST)
    assert (tmp_path / "day.csv").stat().st_mode & 0o777 == 0o600


def test_reports_are_written_without_the_secret(tmp_path):
    home = tmp_path / "home"
    capture = write_capture(home)
    result = run_cli("rea", "scan", str(capture), home=home)
    assert result.returncode == 0
    reports = list((home / "output").glob("rea-scan-*.json"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert SECRET not in text
    assert json.loads(text)["candidates"][0]["masked"].startswith("AIt")


def test_gen_hour_offsets_and_extra_hours(tmp_path):
    home = tmp_path / "home"
    write_capture(home)
    assert run_cli("rea", "scan", str(home / "capture.txt"), "--save", home=home).returncode == 0

    result = run_cli(
        "gen", "--time", "1700000000", "--count", "3", "--tz-offset-minutes", "330", home=home
    )
    assert result.returncode == 0, result.stderr
    printed = [line.split()[1] for line in result.stdout.splitlines() if line.strip()]
    expected = [
        codes_mod.generate_code(SECRET, 1700000000 + index * 3600, offset_minutes=330).code
        for index in range(3)
    ]
    assert printed == expected


def test_cli_error_paths(tmp_path):
    home = tmp_path / "home"
    no_key = run_cli("gen", home=home)
    assert no_key.returncode == 1
    assert "no stored key" in no_key.stderr

    add = run_cli("keys", "add", "not-a-real-secret", home=home)
    assert add.returncode == 1 and "warning" in add.stdout
    forced = run_cli("keys", "add", "not-a-real-secret", "--force", home=home)
    assert forced.returncode == 0

    unknown = run_cli("keys", "rm", "000000", home=home)
    assert unknown.returncode == 1

    missing_file = run_cli("rea", "har", str(tmp_path / "missing.har"), home=home)
    assert missing_file.returncode == 1 and "cannot read HAR" in missing_file.stderr


def test_keys_use_export_import_and_audit(tmp_path):
    home = tmp_path / "home"
    first = run_cli("keys", "add", SECRET, "--label", "um", home=home)
    assert first.returncode == 0, first.stderr
    second = run_cli("keys", "add", SECRET + "b", "--label", "dois", "--force", home=home)
    assert second.returncode == 0

    listing = run_cli("keys", "list", home=home).stdout
    ids = [line.split()[1] for line in listing.splitlines() if line.strip()]
    assert len(ids) == 2

    assert run_cli("keys", "use", ids[1], home=home).returncode == 0
    assert run_cli("keys", "show", home=home).stdout.count(ids[1]) >= 1

    exported = tmp_path / "export.json"
    assert run_cli("keys", "export", str(exported), home=home).returncode == 0
    assert SECRET not in exported.read_text()

    other_home = tmp_path / "other"
    full = tmp_path / "full.json"
    assert run_cli("keys", "export", str(full), "--reveal", home=home).returncode == 0
    imported = run_cli("keys", "import", str(full), home=other_home)
    assert imported.returncode == 0 and "imported 2" in imported.stdout

    audit = run_cli("audit", home=home)
    assert audit.returncode == 0, audit.stdout + audit.stderr
    assert "all checks passed" in audit.stdout


def test_audit_without_store(tmp_path):
    audit = run_cli("audit", home=tmp_path / "empty")
    assert audit.returncode == 0
    assert "[skip] no store" in audit.stdout


# ---------------------------------------------------------------------- server
@pytest.fixture()
def web(tmp_path):
    store = Store(path=tmp_path / "store.json", passphrase=PASSPHRASE)
    store.add_seed(SECRET, label="pai", kind="android")
    token = "test-token-value"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, token, store
    finally:
        server.shutdown()
        server.server_close()


def call(base: str, path: str, token: str = "", method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if token:
        request.add_header("X-Token", token)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def test_web_page_is_served_with_security_headers(web):
    base, token, _store = web
    status, body, headers = call(base, "/")
    assert status == 200
    assert "flcodes" in body
    assert token not in body
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert headers["Cache-Control"] == "no-store"


def test_web_head_is_supported_for_health_checks(web):
    base, _token, _store = web
    request = urllib.request.Request(base + "/", method="HEAD")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        assert response.read() == b""
    request = urllib.request.Request(base + "/nope", method="HEAD")
    try:
        urllib.request.urlopen(request, timeout=10)
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_web_api_requires_the_token_and_masks_keys(web):
    base, token, _store = web
    assert call(base, "/api/health")[0] == 200
    status, body, _headers = call(base, "/api/keys")
    assert status == 401 and "token" in body
    status, body, _headers = call(base, "/api/keys", token="wrong")
    assert status == 401

    status, body, _headers = call(base, "/api/keys", token=token)
    assert status == 200
    document = json.loads(body)
    assert document["keys"][0]["label"] == "pai"
    assert SECRET not in body


def test_web_generate_matches_the_library(web):
    base, token, _store = web
    status, body, _headers = call(
        base,
        "/api/generate",
        token=token,
        method="POST",
        body={"timestamp": 1_700_000_000, "count": 2},
    )
    assert status == 200
    rows = json.loads(body)["rows"]
    assert [row["code"] for row in rows] == [
        codes_mod.generate_code(SECRET, 1_700_000_000).code,
        codes_mod.generate_code(SECRET, 1_700_003_600).code,
    ]
    assert SECRET not in body

    status, body, _headers = call(base, "/api/generate", token=token, method="POST", body={"count": 0})
    assert status == 400

    status, body, _headers = call(base, "/api/code", token=token)
    assert status == 200 and len(json.loads(body)["code"]) == 6


def test_web_add_and_select_key(web):
    base, token, store = web
    new_secret = "AItest-only-web-secret.klmnopqrst"
    status, body, _headers = call(
        base, "/api/keys", token=token, method="POST", body={"secret": new_secret, "label": "web"}
    )
    assert status == 200
    seed_id = json.loads(body)["id"]
    assert store.get_seed(seed_id)["secret"] == new_secret

    status, _body, _headers = call(
        base, "/api/select", token=token, method="POST", body={"id": seed_id}
    )
    assert status == 200
    assert store.active_seed()["id"] == seed_id

    status, body, _headers = call(base, "/api/keys", token=token, method="POST", body={})
    assert status == 400


def test_web_blocks_repeated_bad_tokens(web):
    base, _token, _store = web
    codes = [call(base, "/api/keys")[0] for _ in range(10)]
    assert codes == [401] * 10
    assert call(base, "/api/keys")[0] == 429


def test_web_allow_embed_only_relaxes_the_frame_policy(tmp_path):
    from flcodes.server import make_handler

    store = Store(path=tmp_path / "store.json", passphrase=PASSPHRASE)
    store.add_seed(SECRET, label="pai", kind="android")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, "tok", allow_embed=True))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, _body, headers = call(base, "/")
        assert status == 200
        assert "frame-ancestors *" in headers["Content-Security-Policy"]
        assert "X-Frame-Options" not in headers
        status, body, _headers = call(base, "/api/keys")
        assert status == 401  # the token is still required
    finally:
        server.shutdown()
        server.server_close()
