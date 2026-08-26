#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(os.path.dirname(ROOT), "NovaLinux-1.0-n5030.iso")
VHD = os.path.join(os.path.dirname(ROOT), "NovaLinux-1.0-n5030.vhd")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        if self.path.endswith(".vhd") or self.path.endswith(".iso"):
            name = "NovaLinux-1.0-n5030.vhd" if self.path.endswith(".vhd") else "NovaLinux-1.0-n5030.iso"
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        super().end_headers()

    def _send_file(self, path, name):
        try:
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(size))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except BrokenPipeError:
            pass

    def do_GET(self):
        if self.path in ("/NovaLinux-1.0-n5030.vhd", "/NovaLinux-1.0-n5030.vhd/", "/disco", "/disco/"):
            return self._send_file(VHD, "NovaLinux-1.0-n5030.vhd")
        if self.path in ("/NovaLinux-1.0-n5030.iso", "/NovaLinux-1.0-n5030.iso/"):
            return self._send_file(ISO, "NovaLinux-1.0-n5030.iso")
        return super().do_GET()


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("serving download on :8080", flush=True)
    httpd.serve_forever()
