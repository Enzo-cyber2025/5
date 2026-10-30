"""Local web UI for flcodes.

The server is meant for one operator on one machine:

* it binds ``127.0.0.1`` by default;
* every ``/api`` call needs the access token printed at startup;
* the shared secret never leaves the process - the browser only ever sees the
  masked form, the generated codes and the key ids;
* bodies are size limited, responses are ``no-store`` and the page has a strict
  CSP with no external resources.
"""

from __future__ import annotations

import hmac
import json
import secrets as _secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, codes as codes_mod, report, secrets as secrets_mod
from .store import Store, StoreError, default_store_path

__all__ = ["serve", "make_handler"]

WEB_DIR = Path(__file__).with_name("web")
MAX_BODY = 16 * 1024
FAILED_AUTH_LIMIT = 10
FAILED_AUTH_WINDOW = 60.0

CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'self'"
)
# Only for a sandboxed preview behind an embedding proxy; a normal local run
# keeps the default policy.
EMBEDDABLE_CSP = CSP.replace("frame-ancestors 'self'", "frame-ancestors *")


def serve(args) -> int:
    """Start the HTTP server (blocking)."""
    token = args.token or _secrets.token_urlsafe(18)
    store = Store(path=args.store or default_store_path(), passphrase=args.passphrase)
    handler = make_handler(store, token, allow_embed=getattr(args, "allow_embed", False))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    host, port = server.server_address[:2]
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"flcodes {__version__} on http://{shown_host}:{port}/?token={token}", flush=True)
    print("secrets stay in this process; the browser only gets codes and ids", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
    finally:
        server.server_close()
    return 0


def make_handler(store: Store, token: str, allow_embed: bool = False):
    """Build the request handler bound to ``store`` and ``token``.

    ``allow_embed`` drops the framing restriction so the local page can be shown
    inside a preview proxy; it is off by default.
    """
    failures = {"count": 0, "since": 0.0}
    csp = EMBEDDABLE_CSP if allow_embed else CSP

    class Handler(BaseHTTPRequestHandler):
        server_version = "flcodes/" + __version__
        protocol_version = "HTTP/1.1"

        # ------------------------------------------------------------ helpers
        def log_message(self, fmt, *args):  # keep the token out of logs
            message = fmt % args
            if token:
                message = message.replace(token, "<token>")
            print(f"{self.address_string()} {message}", flush=True)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if not allow_embed:
                self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Content-Security-Policy", csp)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, document: dict) -> None:
            self._send(status, json.dumps(document).encode("utf-8"), "application/json")

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def _auth_ok(self) -> bool:
            supplied = self.headers.get("X-Token", "")
            if not supplied:
                query = parse_qs(urlparse(self.path).query)
                supplied = (query.get("token") or [""])[0]
            if not supplied or not token:
                return False
            return hmac.compare_digest(supplied, token)

        def _guard(self) -> bool:
            now = time.time()
            if now - failures["since"] > FAILED_AUTH_WINDOW:
                failures["count"] = 0
                failures["since"] = now
            if failures["count"] >= FAILED_AUTH_LIMIT:
                self._error(429, "too many failed attempts, wait a minute")
                return False
            if not self._auth_ok():
                failures["count"] += 1
                self._error(401, "missing or invalid token")
                return False
            return True

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body too large")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict):
                raise ValueError("body must be a JSON object")
            return document

        def _seed(self, seed_id: str = ""):
            payload = store.load()
            seeds = payload.get("seeds", [])
            if not seeds:
                raise StoreError("no stored key")
            if seed_id:
                for seed in seeds:
                    if seed["id"] == seed_id:
                        return seed
                raise StoreError("unknown key id")
            active_id = payload.get("active_id")
            for seed in seeds:
                if seed["id"] == active_id:
                    return seed
            return seeds[0]

        # -------------------------------------------------------------- routes
        def do_HEAD(self):  # noqa: N802 - http.server API
            """Headers only, for health checks and preview proxies."""
            route = urlparse(self.path).path
            if route not in ("/", "/index.html", "/api/health"):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8" if route != "/api/health" else "application/json",
            )
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if not allow_embed:
                self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Content-Security-Policy", csp)
            self.end_headers()

        def do_GET(self):  # noqa: N802 - http.server API
            try:
                self._handle_get()
            except Exception as exc:  # never leak a traceback to the client
                self._error(500, f"internal error: {type(exc).__name__}")

        def do_POST(self):  # noqa: N802 - http.server API
            try:
                self._handle_post()
            except Exception as exc:
                self._error(500, f"internal error: {type(exc).__name__}")

        def _handle_get(self):
            route = urlparse(self.path).path
            if route in ("/", "/index.html"):
                page = (WEB_DIR / "index.html").read_bytes()
                self._send(200, page, "text/html; charset=utf-8")
                return
            if route == "/api/health":
                self._json(200, {"ok": True, "version": __version__})
                return
            if not self._guard():
                return
            if route == "/api/keys":
                payload = store.load()
                active_id = payload.get("active_id")
                keys = [
                    {
                        "id": seed["id"],
                        "label": seed["label"],
                        "kind": seed["kind"],
                        "masked": secrets_mod.mask_secret(seed["secret"]),
                        "validity": seed.get("validity"),
                        "active": seed["id"] == active_id,
                    }
                    for seed in payload.get("seeds", [])
                ]
                self._json(200, {"keys": keys})
                return
            if route == "/api/code":
                try:
                    seed = self._seed((parse_qs(urlparse(self.path).query).get("id") or [""])[0])
                except StoreError as exc:
                    self._error(404, str(exc))
                    return
                try:
                    validity = seed.get("validity")
                    code = codes_mod.generate_code(seed["secret"], validity=validity or
                                                   codes_mod.CODE_VALIDITY_SECONDS)
                except ValueError as exc:
                    self._error(400, str(exc))
                    return
                body = {"label": seed["label"], "kind": seed["kind"]}
                body.update(code.as_dict())
                self._json(200, body)
                return
            self._error(404, "not found")

        def _handle_post(self):
            route = urlparse(self.path).path
            if not self._guard():
                return
            try:
                body = self._body()
            except (ValueError, json.JSONDecodeError) as exc:
                self._error(400, str(exc))
                return
            if route == "/api/keys":
                secret = secrets_mod.normalize_secret(str(body.get("secret", "")))
                if not secret:
                    self._error(400, "missing secret")
                    return
                label = str(body.get("label") or "web")
                validity = body.get("validity")
                if validity is not None:
                    try:
                        validity = codes_mod.check_validity(validity)
                    except ValueError as exc:
                        self._error(400, str(exc))
                        return
                record = store.add_seed(
                    secret=secret,
                    label=label,
                    kind=secrets_mod.classify_secret(secret),
                    source="web",
                    validity=validity,
                )
                self._json(200, {"id": record["id"], "label": record["label"]})
                return
            if route == "/api/select":
                try:
                    store.set_active(str(body.get("id", "")))
                except StoreError as exc:
                    self._error(404, str(exc))
                    return
                self._json(200, {"ok": True})
                return
            if route == "/api/generate":
                try:
                    seed = self._seed(str(body.get("id", "")))
                except StoreError as exc:
                    self._error(404, str(exc))
                    return
                try:
                    timestamp = codes_mod.parse_timestamp(
                        str(body.get("timestamp", "")) or "0"
                    ) if body.get("timestamp") not in (None, "") else time.time()
                except ValueError as exc:
                    self._error(400, str(exc))
                    return
                count = body.get("count", 1)
                if isinstance(count, bool) or not isinstance(count, int):
                    self._error(400, "count must be an integer")
                    return
                if count < 1 or count > 240:
                    self._error(400, "count must be between 1 and 240")
                    return
                encoding = str(body.get("encoding", "auto"))
                if encoding not in ("auto", "raw", "base32"):
                    self._error(400, "invalid encoding")
                    return
                try:
                    validity = codes_mod.check_validity(
                        body.get("validity") or seed.get("validity")
                        or codes_mod.CODE_VALIDITY_SECONDS
                    )
                except ValueError as exc:
                    self._error(400, str(exc))
                    return
                rows = []
                for index in range(count):
                    code = codes_mod.generate_code(
                        seed["secret"],
                        timestamp + index * validity,
                        encoding=encoding,
                        validity=validity,
                    )
                    rows.append(report.code_record(code, label=seed["label"], seed_id=seed["id"]))
                self._json(200, {"rows": rows})
                return
            self._error(404, "not found")

    return Handler
