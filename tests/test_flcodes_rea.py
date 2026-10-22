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


def test_harvest_decodes_escaped_hex_and_base64(tmp_path):
    import base64

    variants = {
        "unicode.json": json.dumps({"seed": "".join("\\u%04x" % ord(c) for c in ANDROID_SECRET)}),
        "percent.txt": "".join("%%%02X" % ord(c) for c in ANDROID_SECRET),
        "hex.txt": ANDROID_SECRET.encode().hex(),
        "b64.json": json.dumps({"blob": base64.b64encode(ANDROID_SECRET.encode()).decode()}),
    }
    expected = {
        "unicode.json": "unicode-escaped",
        "percent.txt": "percent-encoded",
        "hex.txt": "hex",
        "b64.json": "base64",
    }
    for name, content in variants.items():
        (tmp_path / name).write_text(content)

    for name, encoding in expected.items():
        single = rea.harvest_files([tmp_path / name])
        assert single.best is not None, name
        assert single.best.secret == ANDROID_SECRET, name
        assert single.best.encoding == encoding, name

    harvest = rea.harvest_files([tmp_path])
    assert {c.secret for c in harvest.candidates} == {ANDROID_SECRET}


def test_har_scanned_as_a_file_decodes_double_escaped_secret(tmp_path):
    # A HAR stores the response body as a JSON string, so the body escapes get
    # escaped again: the file holds \\\\u0041 where the body had \\u0041.
    escaped = "".join("\\u%04x" % ord(c) for c in ANDROID_SECRET)
    body = ")]}'\n" + json.dumps([["familyLinkAppConfig", [[None, escaped]]]])
    har = {"log": {"entries": [
        {"request": {"url": "https://familylink.google.com/config"},
         "response": {"content": {"text": body}}}
    ]}}
    path = tmp_path / "capture.har"
    path.write_text(json.dumps(har))

    from_file = rea.harvest_files([path])
    assert from_file.best is not None and from_file.best.secret == ANDROID_SECRET
    assert from_file.best.encoding == "unicode-escaped"

    from_har = rea.harvest_har(path)
    assert from_har.best.secret == ANDROID_SECRET


def test_double_percent_encoded_secret_is_decoded():
    once = "".join("%%%02X" % ord(c) for c in ANDROID_SECRET)
    twice = once.replace("%", "%25")
    harvest = rea.harvest_text(twice)
    assert harvest.best is not None and harvest.best.secret == ANDROID_SECRET


def test_harvest_keeps_the_code_ttl_next_to_the_secret():
    # Chromium's ParentAccessCodeConfig shape: secret + access_code_ttl + drift
    payload = json.dumps(
        {
            "ParentAccessCodeConfig": {
                "current_config": {
                    "shared_secret": ANDROID_SECRET,
                    "access_code_ttl": 600,
                    "clock_drift_tolerance": 300,
                }
            }
        }
    )
    harvest = rea.harvest_text(payload, source="chromeos-policy")
    best = harvest.best
    assert best.secret == ANDROID_SECRET
    assert best.extra == {"validity": 600, "drift": 300}
    assert secrets_mod.config_validity(harvest.candidates) == 600


def test_harvest_reads_the_ttl_inside_a_nested_har_body(tmp_path):
    import base64 as _base64

    escaped = "".join("\\u%04x" % ord(c) for c in ANDROID_SECRET)
    body = ")]}'\n" + json.dumps(
        {
            "familyLinkAppConfig": {
                "parentAccessCode": {
                    "sharedSecret": escaped,
                    "accessCodeTtl": 1800,
                    "clockDriftTolerance": 120,
                }
            }
        }
    )
    path = tmp_path / "capture.har"
    path.write_text(json.dumps({"log": {"entries": [
        {"request": {"url": "https://familylink.google.com/x"},
         "response": {"content": {"text": body}}}
    ]}}))
    harvest = rea.harvest_files([path])
    assert harvest.best.secret == ANDROID_SECRET
    assert harvest.best.extra == {"validity": 1800, "drift": 120}
    assert _base64  # keep the import used by the module docstring examples


def test_invalid_ttl_next_to_a_secret_is_ignored():
    payload = json.dumps({"shared_secret": ANDROID_SECRET, "access_code_ttl": 5})
    harvest = rea.harvest_text(payload)
    assert harvest.best.secret == ANDROID_SECRET
    assert harvest.best.extra == {}


def test_harvest_reads_utf16_zip_gzip_and_leveldb(tmp_path):
    import gzip
    import zipfile

    first = "AIreveng-prefs-secret.aaaa1111"
    second = "AIreveng-apk-secret.bbbb2222"
    third = "AIreveng-gzip-secret.cccc3333"
    fourth = "AIreveng-ldb-secret.dddd4444"

    prefs = f'<?xml version="1.0" encoding="utf-16"?><map><string name="k">{first}</string></map>'
    (tmp_path / "prefs.xml").write_bytes(prefs.encode("utf-16"))
    with zipfile.ZipFile(tmp_path / "dump.apk", "w") as archive:
        archive.writestr("assets/config.json", json.dumps({"parentAccessCode": second}))
    (tmp_path / "log.gz").write_bytes(gzip.compress(f"lixo {third}".encode()))
    (tmp_path / "005.ldb").write_bytes(b"\x00\x01" + fourth.encode() + b"\x00\xff")

    harvest = rea.harvest_files([tmp_path])
    found = {c.secret: c.source for c in harvest.candidates}
    assert set(found) == {first, second, third, fourth}
    assert any("!" in source for source in found.values())  # zip member name

    # a corrupt container is reported, never fatal
    (tmp_path / "broken.zip").write_bytes(b"PK\x03\x04nada")
    again = rea.harvest_files([tmp_path / "broken.zip"])
    assert again.candidates == [] and again.notes


def test_encrypted_secret_is_reported_not_guessed(tmp_path):
    payload = json.dumps(
        {"familyLinkAppConfig": {"parentAccessCode": {"encryptedSharedSecret": "Q2lwaGVydGV4dA=="}}}
    )
    harvest = rea.harvest_text(payload, source="post-patch")
    assert harvest.candidates == []
    assert any("encryptedSharedSecret" in note for note in harvest.notes)

    path = tmp_path / "payload.json"
    path.write_text(payload)
    assert any("encrypted" in note for note in rea.harvest_files([path]).notes)


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


def test_shared_preferences_xml_keeps_the_ttl():
    """Android escapes the JSON inside SharedPreferences (found on a device)."""
    xml = (
        "<map><string name=\"family_link_app_config\">"
        "{&quot;parentAccessCode&quot;:{&quot;sharedSecret&quot;:&quot;AItest-only-escaped-key&quot;,"
        "&quot;accessCodeTtl&quot;:600,&quot;clockDriftTolerance&quot;:300}}"
        "</string></map>"
    )
    candidates = secrets_mod.extract_from_payload(xml, source="prefs.xml")
    assert [candidate.secret for candidate in candidates] == ["AItest-only-escaped-key"]
    assert candidates[0].extra == {"validity": 600, "drift": 300}
    assert secrets_mod.config_validity(candidates) == 600
