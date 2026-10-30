"""Endpoint discovery: does the tool look at the right paths?

The paths cannot be invented. These tests pin three things: the curated list
keeps its provenance, discovery finds the real paths in a capture without
inventing host/path combinations that do not exist, and `check` reports what an
endpoint answered (status, size, whether a secret was in the body).

No test talks to Google: `check` runs against a local stub.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "family-link-codes"))

from flcodes import endpoints  # noqa: E402

SECRET = "AItest-only-endpoint-secret.abcdefghij"  # NOT a real secret


def test_known_endpoints_carry_their_provenance():
    known = endpoints.known_endpoints()
    assert len(known) >= 5
    assert all(endpoint.why for endpoint in known)
    urls = [endpoint.url for endpoint in known]
    assert any("familyLinkAppConfig" in url for url in urls)
    assert any(url.startswith("file://") and "preferences" in url for url in urls)


def test_discovery_finds_the_config_paths_in_a_har():
    har = {
        "log": {
            "entries": [
                {"request": {"url": "https://familylink.google.com/?hl=pt-BR"},
                 "response": {"content": {"text": ""}}},
                {"request": {"url": "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members"},
                 "response": {"content": {"text": ""}}},
                {"request": {"url": "https://familylink.googleapis.com/v1/familyLinkAppConfig?alt=json"},
                 "response": {"content": {"text": ""}}},
                {"request": {"url": "https://www.google-analytics.com/collect"},
                 "response": {"content": {"text": ""}}},
            ]
        }
    }
    found = endpoints.discover(json.dumps(har), source="capture.har")
    urls = [endpoint.url for endpoint in found]
    assert "https://familylink.googleapis.com/v1/familyLinkAppConfig?alt=json" in urls
    assert any("families/mine/members" in url for url in urls)
    assert not any("google-analytics" in url for url in urls)
    # best first: the app config outranks the session check
    assert found[0].kind == "app-config"


def test_discovery_does_not_invent_hosts_for_bare_paths():
    text = 'fetch("/kidsmanagement/v1/familyLinkAppConfig?hl=pt-BR")'
    found = endpoints.discover(text)
    urls = {endpoint.url for endpoint in found}
    assert "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/familyLinkAppConfig?hl=pt-BR" in urls
    # the same path must not be glued onto a host that never served it
    assert "https://familylink.googleapis.com/kidsmanagement/v1/familyLinkAppConfig?hl=pt-BR" not in urls


def test_discovery_keeps_js_bundles_and_ignores_static_noise():
    text = (
        '<script src="https://www.gstatic.com/_/mss/boq-familylink/_/js/k=familylink.abc.js"></script>'
        '<img src="https://www.gstatic.com/logo.png">'
    )
    found = endpoints.discover(text)
    kinds = {(endpoint.kind, endpoint.url) for endpoint in found}
    assert any(kind == "js-bundle" and url.endswith(".js") for kind, url in kinds)
    assert not any(url.endswith(".png") for _kind, url in kinds)


def test_discovery_on_empty_or_irrelevant_input():
    assert endpoints.discover("") == []
    assert endpoints.discover("hello world, nothing to see") == []


class _Stub(BaseHTTPRequestHandler):
    body = json.dumps(
        {
            "familyLinkAppConfig": {
                "parentAccessCode": {"sharedSecret": SECRET, "accessCodeTtl": 600}
            }
        }
    )
    status = 200

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        payload = type(self).body.encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/familyLinkAppConfig"
    finally:
        server.shutdown()
        server.server_close()


def test_check_reports_status_secret_and_nested_paths(stub):
    result = endpoints.check(stub, sapisid="SAPISID_VALUE", timeout=5)
    assert result["status"] == 200
    assert result["secrets"] == 1
    assert result["kinds"] == ["android"]
    assert SECRET not in json.dumps(result)  # the result only counts secrets


def test_check_reports_unauthorised_and_local_paths(stub):
    original_body, _Stub.status, _Stub.body = _Stub.body, 401, '{"error": {"code": 401}}'
    try:
        result = endpoints.check(stub, timeout=5)
        assert result["status"] == 401
        assert "secrets" not in result  # an error body is not treated as a hit
    finally:
        _Stub.status, _Stub.body = 200, original_body

    local = endpoints.check("file:///var/lib/whitelist/preferences")
    assert local["status"] == 0 and "local path" in local["error"]
