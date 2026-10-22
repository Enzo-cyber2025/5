#!/usr/bin/env python3
"""Tests for the PE header reader that settles the DLL-merge question.

The reader decides, from bytes inside a remote ZIP, whether a binary is a .NET
assembly (mergeable into an EXE by ILMerge/ILRepack/Costura) or native code (not
mergeable by any tool that exists), and which CPU it targets.

Crafted PE headers are used rather than real binaries: the assertions are about
format parsing, and no proprietary code is involved or needed.
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


def make_pe(machine=0x8664, pe32plus=True, is_dll=True, dotnet=False, subsystem=2):
    """Build a minimal but structurally valid PE image."""
    e_lfanew = 128
    dos = bytearray(e_lfanew)
    dos[0:2] = b"MZ"
    dos[0x3C:0x40] = e_lfanew.to_bytes(4, "little")

    out = bytearray(dos)
    out += b"PE\x00\x00"

    size_opt = 240 if pe32plus else 224
    coff = bytearray(20)
    coff[0:2] = machine.to_bytes(2, "little")
    coff[2:4] = (3).to_bytes(2, "little")              # NumberOfSections
    coff[16:18] = size_opt.to_bytes(2, "little")       # SizeOfOptionalHeader
    chars = 0x2000 if is_dll else 0x0002               # IMAGE_FILE_DLL / EXECUTABLE
    coff[18:20] = chars.to_bytes(2, "little")
    out += coff

    opt = bytearray(size_opt)
    opt[0:2] = (0x20B if pe32plus else 0x10B).to_bytes(2, "little")
    opt[68:70] = subsystem.to_bytes(2, "little")
    base = 112 if pe32plus else 96                     # data directory table
    if dotnet:                                         # index 14 = COM descriptor
        opt[base + 14 * 8: base + 14 * 8 + 4] = (0x2000).to_bytes(4, "little")
    out += opt
    return bytes(out)


class ParsePeHeadTest(unittest.TestCase):
    def test_native_x64_dll(self):
        info = probe.parse_pe_head(make_pe())
        self.assertEqual(info["machine"], "x64 (AMD64)")
        self.assertEqual(info["kind"], "DLL")
        self.assertEqual(info["format"], "PE32+")
        self.assertFalse(info["dotnet"])

    def test_dotnet_x86_exe(self):
        info = probe.parse_pe_head(make_pe(machine=0x014C, pe32plus=False,
                                           is_dll=False, dotnet=True))
        self.assertEqual(info["machine"], "x86 (i386)")
        self.assertEqual(info["kind"], "EXE")
        self.assertEqual(info["format"], "PE32")
        self.assertTrue(info["dotnet"], "CLR directory must mark it managed")

    def test_arm64_exe(self):
        info = probe.parse_pe_head(make_pe(machine=0xAA64, is_dll=False))
        self.assertEqual(info["machine"], "ARM64")
        self.assertFalse(info["dotnet"])

    def test_subsystem_and_section_count(self):
        info = probe.parse_pe_head(make_pe(subsystem=3))
        self.assertEqual(info["subsystem"], "console")
        self.assertEqual(info["sections"], 3)

    def test_non_pe_is_rejected(self):
        self.assertIsNone(probe.parse_pe_head(b"not a pe image at all" * 20))
        self.assertIsNone(probe.parse_pe_head(b""))
        # MZ present but a bogus e_lfanew must not be treated as PE.
        bad = bytearray(make_pe())
        bad[0x3C:0x40] = (0xFFFF).to_bytes(4, "little")
        self.assertIsNone(probe.parse_pe_head(bytes(bad)))

    def test_inflate_prefix_handles_stored_and_deflate(self):
        import zlib
        payload = make_pe()
        self.assertEqual(probe.inflate_prefix(payload, 0)[:2], b"MZ")
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = co.compress(payload) + co.flush()
        self.assertEqual(probe.inflate_prefix(comp, 8)[:2], b"MZ")
        self.assertEqual(probe.inflate_prefix(b"garbage", 8), b"")
        self.assertEqual(probe.inflate_prefix(comp, 12), b"", "method 12 is not handled")


class RangeServer(BaseHTTPRequestHandler):
    blob = b""

    def log_message(self, *a):
        pass

    def do_GET(self):
        total = len(type(self).blob)
        rng = self.headers.get("Range")
        with io.BytesIO(type(self).blob) as f:
            if rng and rng.startswith("bytes="):
                a, b = rng[6:].split("-")
                start = int(a)
                end = min(int(b) if b else total - 1, total - 1)
                f.seek(start)
                data = f.read(end - start + 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            else:
                data = f.read()
                self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


class RemoteInspectionTest(unittest.TestCase):
    """End to end: read PE headers out of a ZIP over Range requests."""

    def setUp(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("bin/native_x64.dll", make_pe())
            z.writestr("bin/managed_x86.exe",
                       make_pe(machine=0x014C, pe32plus=False, is_dll=False, dotnet=True))
            z.writestr("bin/game_x64.exe", make_pe(is_dll=False))
            z.writestr("data/archive.scs", b"S" * 50000)
            z.writestr("README.md", b"# x")
        RangeServer.blob = buf.getvalue()
        self.srv = HTTPServer(("127.0.0.1", 0), RangeServer)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.origin = probe.HF
        probe.HF = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.out = io.StringIO()
        self._stdout, sys.stdout = sys.stdout, self.out

    def tearDown(self):
        sys.stdout = self._stdout
        self.srv.shutdown()
        probe.HF = self.origin

    def test_reads_headers_from_inside_the_zip(self):
        probe.inventory_remote_zip("/x/a.zip", "tok", len(RangeServer.blob))
        text = self.out.getvalue()
        self.assertIn("PE header inspection", text)
        self.assertIn("NATIVE (no CLR directory)", text)
        self.assertIn("MANAGED (.NET)", text)
        self.assertIn("x64 (AMD64)", text)
        self.assertIn("x86 (i386)", text)
        self.assertIn("1 .NET, 2 native", text)
        # a managed binary IS present, so the "no .NET" verdict must not fire
        self.assertNotIn("No .NET assembly here", text)
        # names stay hidden unless REVEAL
        self.assertIn("name withheld", text)
        self.assertNotIn("native_x64.dll", text)

    def test_all_native_triggers_the_merge_verdict(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("bin/a.dll", make_pe())
            z.writestr("bin/b.dll", make_pe())
            z.writestr("bin/game.exe", make_pe(is_dll=False))
        RangeServer.blob = buf.getvalue()
        probe.inventory_remote_zip("/x/b.zip", "tok", len(RangeServer.blob))
        text = self.out.getvalue()
        self.assertIn("0 .NET, 3 native", text)
        self.assertIn("No .NET assembly here", text)
        self.assertIn("No ARM binary present", text)

    def test_reveal_mode_shows_names(self):
        probe.REVEAL = True
        try:
            probe.inventory_remote_zip("/x/a.zip", "tok", len(RangeServer.blob))
        finally:
            probe.REVEAL = False
        self.assertIn("native_x64.dll", self.out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
