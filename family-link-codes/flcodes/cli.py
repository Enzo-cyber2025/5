"""Command line interface for flcodes."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import signal
import sys
import time
from pathlib import Path

from . import __version__, codes as codes_mod, rea, report, secrets as secrets_mod
from .store import Store, StoreError, default_store_path

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------- output
def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _out_dir(args) -> Path:
    return report.default_output_dir(getattr(args, "out_dir", None))


def _print(message: str = "", file=None) -> None:
    print(message, file=file or sys.stdout, flush=True)


def _remaining(code, moment: float) -> int:
    """Seconds left in the window counted from ``moment`` (not from now)."""
    return max(0, int(code.valid_to - moment))


def _human_window(code) -> str:
    start = _dt.datetime.fromtimestamp(code.valid_from).astimezone()
    end = _dt.datetime.fromtimestamp(code.valid_to).astimezone()
    return f"{start:%H:%M}–{end:%H:%M}"


# ---------------------------------------------------------------------- store
def _open_store(args, passphrase: str | None = None) -> Store:
    return Store(
        path=getattr(args, "store", None) or default_store_path(),
        passphrase=passphrase or getattr(args, "passphrase", None),
    )


def _store_summary(store: Store) -> dict:
    seeds = store.list_seeds()
    return {
        "path": str(store.path),
        "count": len(seeds),
        "seeds": [
            {
                "id": seed["id"],
                "label": seed["label"],
                "kind": seed["kind"],
                "masked": seed["masked"],
                "created_at": seed["created_at"],
            }
            for seed in seeds
        ],
    }


def _resolve_secret(args, store: Store) -> tuple:
    """Return ``(secret, label, seed_id)`` from the CLI arguments or the store."""
    if getattr(args, "secret", None):
        secret = secrets_mod.normalize_secret(args.secret)
        return secret, args.label or "cli", ""
    payload = store.load()
    seeds = payload.get("seeds", [])
    if not seeds:
        raise StoreError("no stored key: run `flcodes rea ... --save` or `flcodes keys add`")
    if getattr(args, "id", None):
        for seed in seeds:
            if seed["id"] == args.id:
                return seed["secret"], seed["label"], seed["id"]
        raise StoreError(f"unknown seed id: {args.id}")
    if getattr(args, "label", None):
        for seed in seeds:
            if seed["label"] == args.label:
                return seed["secret"], seed["label"], seed["id"]
        raise StoreError(f"unknown label: {args.label}")
    active = store.active_seed()
    return active["secret"], active["label"], active["id"]


# ------------------------------------------------------------------- commands
def cmd_rea(args) -> int:
    harvest = None
    if args.source == "api":
        harvest = rea.harvest_api(
            sapisid=args.sapisid or "",
            cookie_header=args.cookie or "",
            endpoints=[args.url] if args.url else None,
            timeout=args.timeout,
        )
    elif args.source == "har":
        harvest = rea.harvest_har(args.path)
    elif args.source == "paste":
        if args.path:
            text = Path(args.path).read_text(encoding="utf-8", errors="replace")
        else:
            text = sys.stdin.read()
        harvest = rea.harvest_text(text, source="paste")
    elif args.source == "scan":
        harvest = rea.harvest_files(args.paths)
    elif args.source == "adb":
        harvest = rea.harvest_adb(serial=args.serial or "", timeout=args.timeout)
    else:  # pragma: no cover - argparse validates the choices
        raise SystemExit(EXIT_USAGE)

    for candidate in harvest.candidates:
        _print(
            f"[{candidate.kind}] {candidate.masked}  <- {candidate.source}"
            + (f"  ({candidate.context[:80]})" if candidate.context else "")
        )
    for note in harvest.notes:
        _print(f"note: {note}")

    saved = []
    store_summary = {}
    if args.save or args.save_all:
        store = _open_store(args)
        chosen = harvest.candidates if args.save_all else ([harvest.best] if harvest.best else [])
        for candidate in chosen:
            if candidate is None:
                continue
            record = store.add_seed(
                secret=candidate.secret,
                label=args.label or f"{candidate.kind}-{_now_iso()}",
                kind=candidate.kind,
                source=candidate.source,
                notes=candidate.context[:200],
            )
            saved.append(record)
            _print(f"saved: id={record['id']} kind={record['kind']} file={store.path}")
        store_summary = _store_summary(store)
        if not chosen:
            _print("nothing to save: no candidate found")

    if not harvest.candidates:
        _print("no shared secret found")

    if not args.no_report:
        document = report.harvest_report(
            harvest,
            store_summary=store_summary,
            generated=[
                {"id": record["id"], "label": record["label"], "kind": record["kind"]}
                for record in saved
            ],
            extra={"source": args.source, "command": "rea"},
        )
        path = _out_dir(args) / f"rea-{args.source}-{_now_iso()}.json"
        report.write_json(document, path)
        _print(f"report: {path} (secrets masked)")
    return EXIT_OK if harvest.candidates or not args.save else EXIT_ERROR


def cmd_keys(args) -> int:
    store = _open_store(args)
    if args.action == "list":
        for seed in store.list_seeds():
            active = "*" if store.load().get("active_id") == seed["id"] else "-"
            _print(
                f"{active} {seed['id']:<12} {seed['kind']:<10} {seed['masked']:<26} {seed['label']}"
            )
        if not store.list_seeds():
            _print("store is empty")
        return EXIT_OK
    if args.action == "show":
        seed = store.get_seed(args.id) if args.id else store.active_seed()
        if not seed:
            raise StoreError("seed not found")
        if not args.reveal:
            seed["secret"] = secrets_mod.mask_secret(seed["secret"])
        _print(json.dumps(seed, indent=2))
        return EXIT_OK
    if args.action == "add":
        secret = args.secret
        if not secret:
            secret = sys.stdin.readline().strip()
        secret = secrets_mod.normalize_secret(secret)
        if not args.force:
            warnings = _validate_secret(secret)
            for warning in warnings:
                _print(f"warning: {warning}")
            if warnings and not args.allow_unknown:
                _print("refusing to store an unvalidated secret (use --allow-unknown to force)")
                return EXIT_ERROR
        record = store.add_seed(
            secret=secret,
            label=args.label or "manual",
            kind=args.kind or secrets_mod.classify_secret(secret),
            source="cli",
        )
        _print(f"saved: id={record['id']} kind={record['kind']} file={store.path}")
        return EXIT_OK
    if args.action == "rm":
        if store.remove_seed(args.id):
            _print(f"removed {args.id}")
            return EXIT_OK
        raise StoreError(f"unknown seed id: {args.id}")
    if args.action == "use":
        store.set_active(args.id)
        _print(f"active seed: {args.id}")
        return EXIT_OK
    if args.action == "export":
        document = store.export(reveal=args.reveal)
        if args.path:
            report.write_json(document, args.path)
            _print(f"exported to {args.path} (secrets {'included' if args.reveal else 'masked'})")
        else:
            _print(json.dumps(document, indent=2))
        return EXIT_OK
    if args.action == "import":
        document = json.loads(Path(args.path).read_text(encoding="utf-8"))
        imported = store.import_seeds(document, overwrite=args.overwrite)
        _print(f"imported {len(imported)} seed(s)")
        return EXIT_OK
    raise SystemExit(EXIT_USAGE)


def _validate_secret(secret: str) -> list:
    """Return warnings about a secret (empty list means it looks right)."""
    warnings = []
    if not secret:
        warnings.append("empty secret")
        return warnings
    if len(secret) < 12:
        warnings.append(f"secret is unusually short ({len(secret)} chars)")
    if secret.startswith("AL") or secret.lower().startswith("al"):
        warnings.append("secret starts with AL: the Chromebook secret, not the Android one")
    if not secret.startswith("AI"):
        warnings.append("secret does not start with AI")
    if any(char.isspace() for char in secret):
        warnings.append("secret contains whitespace")
    return warnings


def cmd_gen(args) -> int:
    store = _open_store(args)
    secret, label, seed_id = _resolve_secret(args, store)
    encoding = args.encoding
    offset = args.tz_offset_minutes or 0

    if args.day:
        day = _dt.date.fromisoformat(args.day)
        pairs = codes_mod.codes_for_day(
            secret,
            day,
            offset_minutes=offset,
            encoding=encoding,
        )
        records = [
            report.code_record(code, label=label, seed_id=seed_id)
            for _moment, code in pairs
        ]
        for moment, code in pairs:
            _print(f"{moment.astimezone():%Y-%m-%d %H:%M %Z}  {code.code}")
    else:
        timestamp = codes_mod.parse_timestamp(args.time) if args.time else time.time()
        count = max(1, args.count)
        records = []
        for index in range(count):
            moment = timestamp + index * codes_mod.CODE_VALIDITY_SECONDS
            code = codes_mod.generate_code(
                secret, moment, offset_minutes=offset, encoding=encoding
            )
            records.append(report.code_record(code, label=label, seed_id=seed_id))
            if args.json:
                pass
            elif count > 1 or args.verbose:
                _print(f"{_human_window(code)}  {code.code}  (label={label})")
            else:
                _print(code.code)
        first = codes_mod.generate_code(secret, timestamp, offset_minutes=offset, encoding=encoding)
        _print(
            f"valid {_human_window(first)} · {_remaining(first, timestamp)}s remaining",
            file=sys.stderr,
        )

    if args.json:
        _print(json.dumps(records if len(records) > 1 else records[0], indent=2))
    if args.out:
        path = report.save_codes(records, args.out, fmt=args.format, append=args.append)
        _print(f"saved {len(records)} code(s) to {path}", file=sys.stderr)
    return EXIT_OK


def cmd_stream(args) -> int:
    store = _open_store(args)
    secret, label, _seed_id = _resolve_secret(args, store)
    offset = args.tz_offset_minutes or 0
    _print(f"streaming codes for {label} (Ctrl+C to stop)")
    stop = {"flag": False}

    def _handle(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    last_window = None
    while not stop["flag"]:
        now = time.time()
        code = codes_mod.generate_code(secret, now, offset_minutes=offset, encoding=args.encoding)
        if code.counter != last_window:
            stamp = _dt.datetime.now().strftime("%H:%M:%S")
            _print(f"{stamp}  {code.code}  valid until {_human_window(code).split('–')[1]}")
            last_window = code.counter
            if args.out:
                report.save_codes(
                    [report.code_record(code, label=label)],
                    args.out,
                    fmt=args.format,
                    append=True,
                )
        time.sleep(min(2.0, max(0.5, code.seconds_remaining)))
    return EXIT_OK


def cmd_serve(args) -> int:
    from .server import serve

    return serve(args)


def cmd_audit(args) -> int:
    """Self checks: known-answer vectors, store integrity, file permissions."""
    failures = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        _print(f"[{'ok' if condition else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(name)

    # TOTP determinism and hour anchoring
    secret = "AItest-only-secret-value.0"
    hour = 1_700_002_800  # exact hour boundary
    first = codes_mod.generate_code(secret, hour)
    second = codes_mod.generate_code(secret, hour + 3599)
    check("code is stable inside the hour", first.code == second.code)
    third = codes_mod.generate_code(secret, hour + 3600)
    check("code changes on the hour", first.code != third.code)
    check("code is six digits", len(first.code) == 6 and first.code.isdigit())
    check(
        "window is one hour",
        first.valid_to - first.valid_from == codes_mod.CODE_VALIDITY_SECONDS,
    )

    # Crypto known answer (RFC 8439 2.8.2)
    key = bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you only "
        b"one tip for the future, sunscreen would be it."
    )
    from .crypto import aead_encrypt

    sealed = aead_encrypt(key, nonce, plaintext, aad)
    check(
        "ChaCha20-Poly1305 RFC 8439 vector",
        sealed[-16:].hex() == "1ae10b594f09e26a7e902ecbd0600691",
    )

    # Store readability and permissions
    store = _open_store(args)
    if store.path.exists():
        try:
            summary = _store_summary(store)
            check("store decrypts", True, f"{summary['count']} seed(s)")
        except StoreError as exc:
            check("store decrypts", False, str(exc))
        mode = store.path.stat().st_mode & 0o777
        check("store permissions are 0600", mode == 0o600, oct(mode))
    else:
        _print(f"[skip] no store at {store.path}")

    # Clock sanity: the code must be reproducible with a second call
    now = time.time()
    check(
        "clock consistent between calls",
        codes_mod.generate_code(secret, now).code == codes_mod.generate_code(secret, now).code,
    )
    _print()
    if failures:
        _print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return EXIT_ERROR
    _print("all checks passed")
    return EXIT_OK


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flcodes",
        description=(
            "Family Link parent access code generator for authorised security "
            "testing (REA: find the offline code key, save it, generate codes)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"flcodes {__version__}")
    parser.add_argument("--store", help="store file (default: ~/.config/flcodes/store.json)")
    parser.add_argument(
        "--passphrase",
        help="store passphrase (prefer FLCODES_PASSPHRASE or the interactive prompt)",
    )
    parser.add_argument("--out-dir", help="directory for reports and exports")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    rea_parser = sub.add_parser("rea", help="find the offline code key and save it")
    rea_sub = rea_parser.add_subparsers(dest="source", required=True)

    def common_rea(name: str, help_text: str) -> argparse.ArgumentParser:
        child = rea_sub.add_parser(name, help=help_text)
        child.add_argument("--save", action="store_true", help="save the best candidate")
        child.add_argument("--save-all", action="store_true", help="save every candidate")
        child.add_argument("--label", help="label for the saved key")
        child.add_argument("--no-report", action="store_true", help="do not write a report")
        child.add_argument("--timeout", type=float, default=20.0)
        return child

    api_parser = common_rea("api", "fetch the app config with a parent session")
    api_parser.add_argument("--sapisid", help="SAPISID cookie value of the parent session")
    api_parser.add_argument("--cookie-file", help="cookies.txt file (SAPISID is read from it)")
    api_parser.add_argument("--cookie", help="extra cookie header")
    api_parser.add_argument("--url", help="override the endpoint to query")

    har_parser = common_rea("har", "read a browser HAR capture")
    har_parser.add_argument("path")

    paste_parser = common_rea("paste", "read pasted text (stdin or a file)")
    paste_parser.add_argument("path", nargs="?")

    scan_parser = common_rea("scan", "scan files or directories")
    scan_parser.add_argument("paths", nargs="+")

    adb_parser = common_rea("adb", "read app data from a connected device")
    adb_parser.add_argument("--serial")

    keys_parser = sub.add_parser("keys", help="manage the encrypted key store")
    keys_sub = keys_parser.add_subparsers(dest="action", required=True)
    keys_sub.add_parser("list", help="list stored keys (masked)")
    show_parser = keys_sub.add_parser("show", help="show one key")
    show_parser.add_argument("id", nargs="?")
    show_parser.add_argument("--reveal", action="store_true", help="print the secret")
    add_parser = keys_sub.add_parser("add", help="store a secret")
    add_parser.add_argument("secret", nargs="?")
    add_parser.add_argument("--label")
    add_parser.add_argument("--kind", choices=("android", "chromebook", "unknown"))
    add_parser.add_argument("--allow-unknown", action="store_true")
    add_parser.add_argument("--force", action="store_true")
    rm_parser = keys_sub.add_parser("rm", help="delete a key")
    rm_parser.add_argument("id")
    use_parser = keys_sub.add_parser("use", help="set the active key")
    use_parser.add_argument("id")
    export_parser = keys_sub.add_parser("export", help="export the store")
    export_parser.add_argument("path", nargs="?")
    export_parser.add_argument("--reveal", action="store_true")
    import_parser = keys_sub.add_parser("import", help="import an exported store")
    import_parser.add_argument("path")
    import_parser.add_argument("--overwrite", action="store_true")

    gen_parser = sub.add_parser("gen", help="generate codes")
    gen_parser.add_argument("--id", help="stored key id")
    gen_parser.add_argument("--label", help="stored key label")
    gen_parser.add_argument("--secret", help="use a secret directly (not stored)")
    gen_parser.add_argument(
        "--encoding",
        choices=("auto", "raw", "base32"),
        default="auto",
        help="secret interpretation (default: auto)",
    )
    gen_parser.add_argument("--time", help="epoch or ISO-8601 timestamp (default: now)")
    gen_parser.add_argument("--day", help="generate every hour of YYYY-MM-DD")
    gen_parser.add_argument("--count", type=int, default=1, help="number of hours")
    gen_parser.add_argument("--tz-offset-minutes", type=int, default=0)
    gen_parser.add_argument("--json", action="store_true", help="print JSON records")
    gen_parser.add_argument("--out", help="save codes to a file")
    gen_parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="auto")
    gen_parser.add_argument("--append", action="store_true", default=True)

    stream_parser = sub.add_parser("stream", help="live code with the hourly rollover")
    stream_parser.add_argument("--encoding", choices=("auto", "raw", "base32"), default="auto")
    stream_parser.add_argument("--tz-offset-minutes", type=int, default=0)
    stream_parser.add_argument("--out", help="save every new code to a file")
    stream_parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="csv")

    serve_parser = sub.add_parser("serve", help="local web UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--token", help="access token (generated when omitted)")
    serve_parser.add_argument(
        "--allow-embed",
        action="store_true",
        help="allow framing the page (needed only behind a preview proxy)",
    )

    sub.add_parser("audit", help="run the built-in self checks")
    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cookie_file", None):
        args.sapisid = rea.harvest_cookie_file(args.cookie_file)
    handlers = {
        "rea": cmd_rea,
        "keys": cmd_keys,
        "gen": cmd_gen,
        "stream": cmd_stream,
        "serve": cmd_serve,
        "audit": cmd_audit,
    }
    try:
        return handlers[args.command](args)
    except (StoreError, ValueError, RuntimeError, OSError) as exc:
        _print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
