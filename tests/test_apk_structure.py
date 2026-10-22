#!/usr/bin/env python3
"""Tests for reading an APK's structure remotely.

An APK is a ZIP, so the central directory reader applies unchanged. What matters
for "will this install and run on my phone" is three things, all obtainable
without downloading the package:

- which ABIs have native libraries under lib/ (arm64-v8a is the one a 64-bit ARM
  phone needs)
- whether it is signed, under which scheme (v1 = META-INF/*.RSA, v2/v3 = the APK
  Signing Block that sits just before the central directory)
- how many classes*.dex it carries

The ABI logic is deliberately asymmetric and the tests pin both directions: an APK
with native code for the wrong ABI will fail to load it, while an APK with no lib/
entries at all is fine on any architecture because ART runs DEX everywhere.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ci"))
import hf_token_probe as probe  # noqa: E402


def make_apk(abis=(), dex=1, v1=False, signing_block=False, extra_paths=()):
    """Build a ZIP shaped like an APK, optionally with a v2 signing block."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(dex):
            name = "classes.dex" if i == 0 else f"classes{i + 1}.dex"
            z.writestr(name, b"dex\n035\0" + b"D" * 500)
        for abi in abis:
            z.writestr(f"lib/{abi}/libnative.so", b"\x7fELF" + b"N" * 400)
        if v1:
            z.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0")
            z.writestr("META-INF/CERT.RSA", b"\x30\x82" + b"R" * 300)
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00" + b"M" * 200)
        z.writestr("resources.arsc", b"\x02\x00\x0c\x00" + b"A" * 400)
        for path in extra_paths:
            z.writestr(path, b"x" * 100)
    data = buf.getvalue()
    if signing_block:
        data = insert_signing_block(data)
    return data


def insert_signing_block(data: bytes) -> bytes:
    """Splice a minimal valid-shaped APK Signing Block before the CD.

    Layout: size_of_block(8) + pairs + size_of_block(8) + magic(16). The reader
    only looks at the final 24 bytes before the central directory.
    """
    eocd = data.rfind(b"PK\x05\x06")
    cd_off = int.from_bytes(data[eocd + 16:eocd + 20], "little")
    size = (24).to_bytes(8, "little")
    block = size + size + b"APK Sig Block 42"
    out = data[:cd_off] + block + data[cd_off:]
    eocd2 = out.rfind(b"PK\x05\x06")
    return (out[:eocd2 + 16] + (cd_off + len(block)).to_bytes(4, "little")
            + out[eocd2 + 20:])


class Srv(BaseHTTPRequestHandler):
    blob = b""

    def log_message(self, *a):
        pass

    def do_GET(self):
        total = len(type(self).blob)
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, b = rng[6:].split("-")
            start = int(a)
            end = min(int(b) if b else total - 1, total - 1)
            if start < 0:                       # negative offset => refuse
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            chunk = type(self).blob[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        else:
            chunk = type(self).blob
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


class ApkStructureTest(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), Srv)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.origin = probe.HF
        probe.HF = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        probe.HF = self.origin

    def inspect(self, blob: bytes) -> str:
        Srv.blob = blob
        out = io.StringIO()
        saved, sys.stdout = sys.stdout, out
        try:
            probe.inventory_remote_zip("/x/app.apk", "tok", len(blob))
        finally:
            sys.stdout = saved
        return out.getvalue()

    def test_arm64_apk_signed_v1_and_v2(self):
        text = self.inspect(make_apk(abis=["arm64-v8a", "armeabi-v7a"], dex=2,
                                     v1=True, signing_block=True))
        self.assertIn("Android package structure", text)
        self.assertIn("classes*.dex: 2", text)
        self.assertIn("arm64-v8a", text)
        self.assertIn("armeabi-v7a", text)
        self.assertIn("v1 signature (META-INF/*.RSA): present", text)
        self.assertIn("v2/v3 signature (APK Signing Block): present", text)
        self.assertIn("has ARM64 native code", text)

    def test_wrong_abi_only_is_flagged(self):
        text = self.inspect(make_apk(abis=["x86_64"], signing_block=True))
        self.assertIn("native code for ['x86_64'] ONLY", text)
        self.assertIn("will fail to load", text)

    def test_no_native_code_is_not_a_problem(self):
        """No lib/ at all means pure DEX, which runs on any ABI."""
        text = self.inspect(make_apk(abis=[], v1=True))
        self.assertIn("NONE (no lib/ entries)", text)
        self.assertIn("the ABI does not", text)
        self.assertNotIn("will fail to load", text)

    def test_unsigned_apk(self):
        text = self.inspect(make_apk(abis=["arm64-v8a"]))
        self.assertIn("v1 signature (META-INF/*.RSA): absent", text)
        self.assertIn("v2/v3 signature (APK Signing Block): absent", text)

    def test_signing_block_detection_needs_the_magic(self):
        """A block with the wrong magic must not be reported as a signature."""
        data = make_apk(abis=["arm64-v8a"])
        eocd = data.rfind(b"PK\x05\x06")
        cd_off = int.from_bytes(data[eocd + 16:eocd + 20], "little")
        size = (24).to_bytes(8, "little")
        bogus = size + size + b"NOT A Sig Block 42"
        out = data[:cd_off] + bogus + data[cd_off:]
        eocd2 = out.rfind(b"PK\x05\x06")
        out = (out[:eocd2 + 16] + (cd_off + len(bogus)).to_bytes(4, "little")
               + out[eocd2 + 20:])
        text = self.inspect(out)
        self.assertIn("v2/v3 signature (APK Signing Block): absent", text)

    def test_non_apk_zip_prints_no_android_section(self):
        """A plain ZIP (game data, say) must not gain a bogus Android report."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data/archive.scs", b"S" * 5000)
            z.writestr("bin/tool.dll", b"M" * 500)
        text = self.inspect(buf.getvalue())
        self.assertNotIn("Android package structure", text)

    def test_names_stay_withheld(self):
        text = self.inspect(make_apk(abis=["arm64-v8a"], v1=True))
        self.assertNotIn("CERT.RSA", text)
        self.assertNotIn("libnative.so", text)
        self.assertIn("name withheld", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
