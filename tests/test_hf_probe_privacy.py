#!/usr/bin/env python3
"""Regression tests for the HF probe's privacy contract.

These exist because of a real incident: a parameter named `raw` shadowed the local
variable holding the response bytes, so every call returned bytes instead of a
parsed dict. whoami-v2 answered 200, the code failed to recognise it, fell into
its error branch, and that branch printed the raw response body - which for a
*successful* whoami call is exactly the account name and full name. On a public
repository those logs are public.

Two rules are asserted here:

1. Identity material must never reach stdout in the default (CI) mode, on ANY
   code path - success, HTTP error, or unparseable body.
2. The full flow must be exercised, not just the newly added function. The bug
   above survived precisely because only the new function was tested.

Runs against a local HTTP server; no network access and no real credentials.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ci"))
import hf_token_probe as probe  # noqa: E402

# Sentinels: if any of these reaches stdout, the privacy contract is broken.
HF_NAME = "enzo123456789"
HF_FULLNAME = "enzo miguel silva"
HF_EMAIL = "private-personal@example.com"
HF_ORG = "acme-secret-org"
PRIVATE_REPO = f"{HF_NAME}/my-private-dataset"
SENTINELS = [HF_NAME, HF_FULLNAME, HF_EMAIL, HF_ORG, PRIVATE_REPO]

WHOAMI = {
    "type": "user", "id": "6a2b4d45915f77221b7c95aa",
    "name": HF_NAME, "fullname": HF_FULLNAME, "email": HF_EMAIL,
    "canPay": False, "billingMode": "prepaid", "periodEnd": 1793491200,
    "isPro": False, "avatarUrl": "/avatars/x.png",
    "orgs": [{"name": HF_ORG, "type": "org", "isEnterprise": False}],
    "auth": {"type": "access_token", "accessToken": {
        "role": "fineGrained", "createdAt": "2026-09-30T18:55:54.442Z",
        "displayName": "my-secret-token-label",
        "fineGrained": {"canReadGatedRepos": True,
                        "global": ["repos.read", "datasets.read"],
                        "scoped": [{"repo": PRIVATE_REPO, "permissions": ["read"]}]}}},
}
DATASETS = [{"id": PRIVATE_REPO, "private": True, "gated": False,
             "downloads": 0, "likes": 0, "sha": "b573623d80ed"}]
ZIP_NAME = f"{HF_NAME}/sla1"


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("weights/part-a.gguf", b"G" * 200000)
        z.writestr("weights/part-b.safetensors", b"S" * 100000)
        z.writestr("README.md", b"# doc")
        z.writestr(".gitattributes", b"*")
    return buf.getvalue()


ZIP_BYTES = build_zip()


class Handler(BaseHTTPRequestHandler):
    """Serves the probe's endpoints, with Range support for the ZIP."""

    mode = "ok"

    def log_message(self, *args):  # silence
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _zip(self):
        rng = self.headers.get("Range")
        total = len(ZIP_BYTES)
        if rng and rng.startswith("bytes="):
            a, b = rng[6:].split("-")
            start = int(a)
            end = int(b) if b else total - 1
            end = min(end, total - 1)
            chunk = ZIP_BYTES[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        else:
            chunk = ZIP_BYTES
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(chunk)

    def do_GET(self):
        path = self.path.split("?")[0]
        mode = type(self).mode

        if path == "/api/whoami-v2":
            if not self.headers.get("Authorization"):
                return self._json(401, {"error": "Invalid username or password."})
            if mode == "whoami_html":
                # 200 with a body that is not JSON: the unparseable path.
                body = (f"<html>sorry {HF_FULLNAME} your account {HF_NAME}"
                        f" email {HF_EMAIL}</html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if mode == "whoami_401_text":
                return self._json(401, {"error": f"Invalid username or password for {HF_NAME}"})
            if mode == "whoami_500":
                return self._json(500, {"error": f"boom for {HF_NAME}"})
            return self._json(200, WHOAMI)

        if path.endswith("/sla1/resolve/main/archive.zip"):
            return self._zip()

        if path in ("/api/models", "/api/datasets", "/api/spaces"):
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            if "search=sla1" in q or f"author={HF_NAME}" in q:
                if path == "/api/datasets":
                    item = dict(DATASETS[0])
                    if "search=sla1" in q:
                        item["id"] = ZIP_NAME
                    return self._json(200, [item])
                return self._json(200, [])
            return self._json(200, [])

        if path.startswith("/api/datasets/") and "/tree/main" in path:
            return self._json(200, [
                {"type": "file", "path": "archive.zip", "size": len(ZIP_BYTES)},
                {"type": "file", "path": ".gitattributes", "size": 4},
            ])
        if path.startswith("/api/datasets/"):
            return self._json(200, {"id": PRIVATE_REPO, "private": True, "gated": False,
                                    "disabled": False, "downloads": 0, "likes": 0,
                                    "sha": "b573623d80ed", "lastModified": "2026-10-10",
                                    "tags": ["x"], "cardData": None,
                                    "siblings": [{"rfilename": "archive.zip"}]})
        if "/resolve/main/" in path:
            self.send_response(200)
            self.send_header("Content-Length", "1")
            self.end_headers()
            return self.wfile.write(b"x")
        return self._json(404, {"error": "not found"})


class PrivacyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.origin = probe.HF
        probe.HF = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        probe.HF = cls.origin

    def run_full_flow(self, mode="ok", reveal=False, token="hf_" + "T" * 34):
        """Run the ENTIRE probe flow the way CI does, capturing stdout."""
        Handler.mode = mode
        probe.REVEAL = reveal
        probe.TARGETS = ["sla1"]
        argv = [sys.argv[0], "--named-inventory", "--target", "sla1"]
        if reveal:
            # main() assigns REVEAL from this flag, so setting the module global
            # alone is not enough - it gets overwritten.
            argv.append("--reveal-names")
        env = {"SECRET_NAMES": "HF_TOKEN", "VAR_NAMES": "", "S001": token,
               "CTRL_GITHUB_TOKEN": "ghs_" + "x" * 30}
        saved_argv, saved_env = sys.argv, dict(os.environ)
        buf = io.StringIO()
        try:
            sys.argv = argv
            os.environ.update(env)
            with contextlib.redirect_stdout(buf):
                probe.main()
        finally:
            sys.argv = saved_argv
            os.environ.clear()
            os.environ.update(saved_env)
            Handler.mode = "ok"
            probe.REVEAL = False
        return buf.getvalue()

    def assertNoIdentity(self, out: str, ctx: str):
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, out,
                             f"IDENTITY LEAK ({ctx}): {sentinel!r} reached stdout")
        self.assertNotIn("my-secret-token-label", out,
                         f"token displayName leaked ({ctx})")

    def test_happy_path_leaks_nothing(self):
        out = self.run_full_flow("ok")
        self.assertIn("token ACCEPTED", out)
        self.assertIn("datasets: 1 total", out)
        self.assertNoIdentity(out, "happy path")

    def test_unparseable_200_body_leaks_nothing(self):
        """The exact incident: 200 with a body the parser rejects."""
        out = self.run_full_flow("whoami_html")
        self.assertIn("could not validate", out)
        self.assertNoIdentity(out, "unparseable 200 body")

    def test_http_error_body_leaks_nothing(self):
        """An error message from the server must not be echoed verbatim."""
        out = self.run_full_flow("whoami_500")
        self.assertIn("could not validate", out)
        self.assertIn("unrecognised error message withheld", out)
        self.assertNotIn("boom for", out, "server error text was echoed")
        self.assertNoIdentity(out, "HTTP 500 body")

    def test_rejected_token_verdict_is_clear_and_echoes_nothing(self):
        """401 has its own verdict branch: it must stay clear and echo no body."""
        out = self.run_full_flow("whoami_401_text")
        self.assertIn("token REJECTED (401)", out)
        self.assertNotIn("Invalid username or password for", out,
                         "server error text was echoed on the 401 path")
        self.assertNoIdentity(out, "401 verdict")

    def test_classify_error_never_echoes_arbitrary_text(self):
        """Direct unit check on the labeller used by the failure branch."""
        msg = "Invalid username or password."
        self.assertEqual(probe.classify_error({"error": msg}),
                         f"invalid-credentials ({len(msg)} chars)")
        self.assertEqual(probe.classify_error({"error": f"boom for {HF_NAME}"}),
                         f"<unrecognised error message withheld, {len('boom for ' + HF_NAME)} chars>")
        self.assertEqual(probe.classify_error({}), "<no error message>")
        for payload in ({"error": f"leaked {HF_FULLNAME}"},
                        {"message": HF_EMAIL}, f"raw text {HF_NAME}"):
            label = probe.classify_error(payload)
            for sentinel in SENTINELS:
                self.assertNotIn(sentinel, label, "classify_error echoed identity")

    def test_rejected_token_leaks_nothing(self):
        out = self.run_full_flow("ok", token="")
        self.assertNoIdentity(out, "empty token")

    def test_archive_inventory_runs_and_counts(self):
        """Range-based ZIP listing must work after the as_bytes rename."""
        out = self.run_full_flow("ok")
        self.assertIn("Archive inventory", out)
        self.assertIn("entries parsed", out)
        self.assertIn("'gguf'", out)
        self.assertIn("Windows PE binaries present: NONE", out)
        self.assertNoIdentity(out, "archive inventory")

    def test_reveal_mode_is_opt_in_and_does_show_names(self):
        hidden = self.run_full_flow("ok", reveal=False)
        shown = self.run_full_flow("ok", reveal=True)
        self.assertNotIn(HF_NAME, hidden)
        self.assertIn(HF_NAME, shown,
                      "--reveal-names should expose identity locally")

    def test_default_mode_never_sets_reveal(self):
        self.assertFalse(probe.REVEAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
