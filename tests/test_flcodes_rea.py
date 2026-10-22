"""REA must find the key in every supported capture, and never leak it.

No test contacts Google: the ``api`` collector is exercised against a local
stub endpoint, and every other collector reads fixtures written into
``tmp_path``. The masked forms and the reports are checked to prove they carry
no secret.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "family-link-codes"))

from flcodes import rea, report, secrets as secrets_mod  # noqa: E402

ANDROID_SECRET = "AItest-only-android-secret.abcdefghij"  # NOT a real secret
CHROMEBOOK_SECRET = "ALtest-only-chromebook-secret.klmnop"  # NOT a real secret
XSSI = ")]}'\n"


def config_body() -> str:
    """Shape of the Family Link app config payload (values are dummies)."""
    document = {
        "familyLinkAppConfig": {
            "parentAccessCode": {
                "androidSharedSecret": ANDROID_SECRET,
                "chromebookSharedSecret": CHROMEBOOK_SECRET,
            },
            "language": "pt-BR",
        }
    }
    return XSSI + json.dumps(document)


class _Stub(BaseHTTPRequestHandler):
    body = config_body()
    seen: list = []

    def log_message(self, *_args):  # silence the stub
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        type(self).seen.append(dict(self.headers))
        payload = type(self).body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def stub_server():
    _Stub.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/config"
    finally:
        server.shutdown()
        server.server_close()


def test_sapisidhash_matches_the_documented_formula():
    value = rea.sapisid_hash("SAPISID_VALUE", origin=rea.ORIGIN, timestamp_ms=1700000000123)
    assert value.startswith("1700000000123_")
    import hashlib

    expected = hashlib.sha1(
        f"1700000000123 SAPISID_VALUE {rea.ORIGIN}".encode()
    ).hexdigest()
    assert value == f"1700000000123_{expected}"
    with pytest.raises(ValueError):
        rea.sapisid_hash("")


def test_headers_include_auth_cookie_and_api_key():
    headers = rea.build_headers(sapisid="S", cookie_header="SID=abc;")
    assert headers["Authorization"].startswith("SAPISIDHASH ")
    assert headers["Cookie"] == "SAPISID=S; SID=abc"
    assert headers["X-Goog-Api-Key"] == rea.API_KEY
    assert "Authorization" not in rea.build_headers()


def test_api_harvest_reads_the_stub_without_leaking(stub_server):
    harvest = rea.harvest_api(sapisid="S", endpoints=[stub_server], timeout=5)
    kinds = {candidate.secret: candidate.kind for candidate in harvest.candidates}
    assert kinds[ANDROID_SECRET] == "android"
    assert kinds[CHROMEBOOK_SECRET] == "chromebook"
    assert harvest.best.secret == ANDROID_SECRET
    assert harvest.responses[0]["status"] == 200
    # the request carried the auth header built from the cookie
    assert any("SAPISIDHASH" in header.get("Authorization", "") for header in _Stub.seen)
    masked = harvest.as_dict()
    assert ANDROID_SECRET not in json.dumps(masked)
    assert masked["candidates"][0]["masked"].startswith("AIte…")
    assert "len" in masked["candidates"][0]["masked"]


def test_api_harvest_reports_unreachable_endpoint():
    harvest = rea.harvest_api(sapisid="S", endpoints=["http://127.0.0.1:9/none"], timeout=1)
    assert harvest.candidates == []
    assert harvest.notes
    assert harvest.best is None


def test_text_harvest_handles_quotes_uris_and_base64():
    quoted = rea.harvest_text(f'  "{ANDROID_SECRET}"  ')
    assert quoted.best.secret == ANDROID_SECRET

    uri = f"otpauth://totp/FamilyLink?secret={ANDROID_SECRET}&period=3600"
    assert rea.harvest_text(uri).best.secret == ANDROID_SECRET

    encoded = base64.b64encode(ANDROID_SECRET.encode()).decode()
    wrapped = rea.harvest_text(json.dumps({"blob": encoded}))
    assert wrapped.best.secret == ANDROID_SECRET

    assert rea.harvest_text("nada aqui").candidates == []


def test_harvest_reads_a_browser_har(tmp_path):
    har = {
        "log": {
            "entries": [
                {"request": {"url": "https://familylink.google.com/"},
                 "response": {"content": {"text": config_body()}}},
                {"request": {"url": "https://example.test/none"},
                 "response": {"content": {"text": "{\"a\":1}"}}},
            ]
        }
    }
    path = tmp_path / "capture.har"
    path.write_text(json.dumps(har))
    harvest = rea.harvest_har(path)
    assert {c.secret for c in harvest.candidates} == {ANDROID_SECRET, CHROMEBOOK_SECRET}
    with pytest.raises(ValueError):
        rea.harvest_har(tmp_path / "missing.har")


def test_harvest_scans_directories_and_skips_binaries(tmp_path):
    (tmp_path / "dump.json").write_text(config_body())
    (tmp_path / "prefs.xml").write_text(f'<string name="seed">{ANDROID_SECRET}</string>')
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + ANDROID_SECRET.encode())
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "log.txt").write_text("nada")
    harvest = rea.harvest_files([tmp_path])
    assert {c.secret for c in harvest.candidates} == {ANDROID_SECRET, CHROMEBOOK_SECRET}
    missing = rea.harvest_files([tmp_path / "nope"])
    assert missing.candidates == [] and missing.notes


def test_secret_helpers_classify_and_mask():
    assert secrets_mod.classify_secret("AIabc") == "android"
    assert secrets_mod.classify_secret("ALabc") == "chromebook"
    assert secrets_mod.classify_secret("xx") == "unknown"
    assert secrets_mod.looks_like_secret(ANDROID_SECRET)
    assert secrets_mod.looks_like_secret(CHROMEBOOK_SECRET)
    assert not secrets_mod.looks_like_secret("AI")
    assert not secrets_mod.looks_like_secret("ALLOWEDLIST")
    assert not secrets_mod.looks_like_secret("AIALLOWEDLIST")
    assert not secrets_mod.looks_like_secret("x" * 40)
    masked = secrets_mod.mask_secret(ANDROID_SECRET)
    assert ANDROID_SECRET not in masked and "len" in masked


def test_report_never_contains_the_secret(tmp_path):
    harvest = rea.harvest_text(config_body(), source="fixture")
    document = report.harvest_report(harvest, store_summary={"count": 1})
    text = json.dumps(document)
    assert ANDROID_SECRET not in text and CHROMEBOOK_SECRET not in text
    assert document["created_at_utc"].endswith("+00:00")
    assert document["candidates"][0]["kind"] == "android"
    path = report.write_json(document, tmp_path / "report.json")
    assert path.stat().st_mode & 0o777 == 0o600
    assert ANDROID_SECRET not in path.read_text()


def test_secure_delete_removes_the_file(tmp_path):
    path = tmp_path / "codes.csv"
    path.write_text("code\n123456\n")
    assert report.secure_delete(path) is True
    assert not path.exists()
    assert report.secure_delete(path) is False


def test_code_saving_persists_csv_and_jsonl(tmp_path):
    from flcodes import codes as codes_mod

    code = codes_mod.generate_code(ANDROID_SECRET, 1_700_000_000)
    record = report.code_record(code, label="pai", seed_id="abc")
    csv_path = report.save_codes([record], tmp_path / "out.csv")
    assert "code" in csv_path.read_text().splitlines()[0]
    assert code.code in csv_path.read_text()
    assert csv_path.stat().st_mode & 0o777 == 0o600
    report.save_codes([record], csv_path)  # append keeps a single header
    assert csv_path.read_text().count("valid_from_utc") == 1
    jsonl_path = report.save_codes([record], tmp_path / "out.jsonl")
    assert json.loads(jsonl_path.read_text().splitlines()[0])["code"] == code.code
    with pytest.raises(ValueError):
        report.save_codes([record], tmp_path / "x.txt", fmt="xml")
