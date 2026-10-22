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

from . import (
    __version__,
    abe as abe_mod,
    apk as apk_mod,
    codes as codes_mod,
    device as device_mod,
    endpoints as endpoints_mod,
    rea,
    report,
    secrets as secrets_mod,
    verify as verify_mod,
)
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
    """Return ``(secret, label, seed_id, validity)`` for the CLI arguments."""
    validity = getattr(args, "validity", None)
    if getattr(args, "secret", None):
        secret = secrets_mod.normalize_secret(args.secret)
        return secret, args.label or "cli", "", validity
    payload = store.load()
    seeds = payload.get("seeds", [])
    if not seeds:
        raise StoreError("no stored key: run `flcodes rea ... --save` or `flcodes keys add`")
    if getattr(args, "id", None):
        matches = [seed for seed in seeds if seed["id"] == args.id]
        if not matches:
            raise StoreError(f"unknown seed id: {args.id}")
    elif getattr(args, "label", None):
        matches = [seed for seed in seeds if seed["label"] == args.label]
        if not matches:
            raise StoreError(f"unknown label: {args.label}")
    else:
        active = store.active_seed()
        matches = [active] if active else []
    seed = matches[0]
    return (
        seed["secret"],
        seed["label"],
        seed["id"],
        validity or seed.get("validity"),
    )


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

    return _finish_harvest(args, harvest, args.source)


def _finish_harvest(args, harvest, source_label: str) -> int:
    """Print, optionally save and report one acquisition result."""
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
        for index, candidate in enumerate(chosen):
            if candidate is None:
                continue
            # keep labels distinguishable when several candidates are saved
            if args.label and len(chosen) > 1:
                label = f"{args.label}-{index + 1}"
            else:
                label = args.label or f"{candidate.kind}-{_now_iso()}"
            record = store.add_seed(
                secret=candidate.secret,
                label=label,
                kind=candidate.kind,
                source=candidate.source,
                notes=candidate.context[:200],
                validity=(candidate.extra or {}).get("validity"),
                drift=(candidate.extra or {}).get("drift"),
            )
            saved.append(record)
            extra = ""
            if record.get("validity"):
                extra = f" ttl={record['validity']}s"
            _print(f"saved: id={record['id']} kind={record['kind']}{extra} file={store.path}")
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
            extra={"source": source_label, "command": "rea"},
        )
        path = _out_dir(args) / f"rea-{source_label}-{_now_iso()}.json"
        report.write_json(document, path)
        _print(f"report: {path} (secrets masked)")
    return EXIT_OK if harvest.candidates or not args.save else EXIT_ERROR


def cmd_keys(args) -> int:
    store = _open_store(args)
    if args.action == "list":
        for seed in store.list_seeds():
            active = "*" if store.load().get("active_id") == seed["id"] else "-"
            ttl = f"{seed['validity']}s" if seed.get("validity") else "auto"
            _print(
                f"{active} {seed['id']:<12} {seed['kind']:<10} {ttl:<6} "
                f"{seed['masked']:<26} {seed['label']}"
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
            validity=args.validity,
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
    secret, label, seed_id, validity = _resolve_secret(args, store)
    if validity is None:
        _print(
            f"note: ttl {codes_mod.CODE_VALIDITY_SECONDS}s is a fallback, the key "
            "carries no TTL; confirm with `flcodes verify --code ...`.",
            file=sys.stderr,
        )
    encoding = args.encoding
    offset = args.tz_offset_minutes or 0
    validity = codes_mod.check_validity(validity or codes_mod.CODE_VALIDITY_SECONDS)

    if args.day:
        day = _dt.date.fromisoformat(args.day)
        pairs = codes_mod.codes_for_day(
            secret,
            day,
            offset_minutes=offset,
            encoding=encoding,
            validity=validity,
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
            moment = timestamp + index * validity
            code = codes_mod.generate_code(
                secret, moment, offset_minutes=offset, encoding=encoding, validity=validity
            )
            records.append(report.code_record(code, label=label, seed_id=seed_id))
            if args.json:
                pass
            elif count > 1 or args.verbose:
                _print(f"{_human_window(code)}  {code.code}  (label={label})")
            else:
                _print(code.code)
        first = codes_mod.generate_code(
            secret, timestamp, offset_minutes=offset, encoding=encoding, validity=validity
        )
        _print(
            f"valid {_human_window(first)} · {_remaining(first, timestamp)}s remaining "
            f"· ttl {validity}s",
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
    secret, label, _seed_id, validity = _resolve_secret(args, store)
    offset = args.tz_offset_minutes or 0
    validity = codes_mod.check_validity(validity or codes_mod.CODE_VALIDITY_SECONDS)
    _print(f"streaming codes for {label} (Ctrl+C to stop)")
    stop = {"flag": False}

    def _handle(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    last_window = None
    while not stop["flag"]:
        now = time.time()
        code = codes_mod.generate_code(
            secret, now, offset_minutes=offset, encoding=args.encoding, validity=validity
        )
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


def cmd_paths(args) -> int:
    """List, discover or check the endpoints that deliver the app config."""
    if args.action == "list":
        for endpoint in endpoints_mod.known_endpoints():
            _print(f"[{endpoint.kind}] {endpoint.url}")
            _print(f"    {endpoint.why}")
        _print()
        _print("discover the real paths from your own capture:")
        _print("  flcodes paths discover --file ~/Downloads/familylink.har")
        _print("  flcodes paths check --sapisid <cookie> --url <endpoint>")
        return EXIT_OK

    if args.action == "discover":
        text = ""
        if args.file:
            text = (
                Path(args.file).read_text(encoding="utf-8", errors="replace")
                if args.file != "-"
                else sys.stdin.read()
            )
        else:
            text = sys.stdin.read()
        found = endpoints_mod.discover(text, source=args.file or "stdin")
        if not found:
            _print("no endpoint candidate found in the input")
            return EXIT_ERROR
        for endpoint in found:
            _print(f"[{endpoint.kind}] score={endpoint.score} {endpoint.url}")
            _print(f"    {endpoint.why}")
        configs = [endpoint for endpoint in found if endpoint.kind == "app-config"]
        if configs:
            _print()
            _print("most promising (app config):")
            for endpoint in configs[:3]:
                _print(f"  flcodes rea api --url '{endpoint.url}' --cookie-file cookies.txt --save")
        if not args.no_report:
            document = {
                "tool": "flcodes",
                "command": "paths discover",
                "source": args.file or "stdin",
                "endpoints": [endpoint.as_dict() for endpoint in found],
            }
            path = _out_dir(args) / f"paths-{_now_iso()}.json"
            report.write_json(document, path)
            _print(f"report: {path}")
        return EXIT_OK

    if args.action == "check":
        targets = args.url or [entry["url"] for entry in endpoints_mod.KNOWN_ENDPOINTS]
        sapisid = args.sapisid or ""
        if getattr(args, "cookie_file", None):
            sapisid = rea.harvest_cookie_file(args.cookie_file)
        if not sapisid and not args.cookie:
            _print(
                "warning: no session given (--sapisid/--cookie-file); "
                "endpoints will answer 401/403",
                file=sys.stderr,
            )
        ok = False
        for url in targets:
            result = endpoints_mod.check(
                url, sapisid=sapisid, cookie=args.cookie or "", timeout=args.timeout
            )
            line = f"[{result.get('status') or '---'}] {url}"
            if result.get("bytes"):
                line += f" ({result['bytes']} bytes"
                if result.get("secrets"):
                    line += f", {result['secrets']} secret(s) {result.get('kinds')}"
                elif result.get("encrypted_hint"):
                    line += f", encrypted secret field '{result['encrypted_hint']}'"
                line += ")"
            if result.get("error"):
                line += f" - {result['error']}"
            _print(line)
            for extra in result.get("paths", [])[:5]:
                _print(f"    path in body: {extra}")
            if result.get("status") == 200:
                ok = True
        return EXIT_OK if ok else EXIT_ERROR

    raise SystemExit(EXIT_USAGE)


def cmd_abe(args) -> int:
    """Inspect, extract or scan an ``adb backup`` container (no root needed)."""
    path = Path(args.file)
    if not path.is_file():
        _print(f"no such file: {path}", file=sys.stderr)
        return EXIT_ERROR
    if not abe_mod.is_android_backup(path):
        _print(f"{path} is not an Android backup (missing 'ANDROID BACKUP' magic)", file=sys.stderr)
        return EXIT_ERROR
    try:
        header = abe_mod.parse_header(path)
    except abe_mod.BackupError as exc:
        _print(f"bad header: {exc}", file=sys.stderr)
        return EXIT_ERROR
    _print(
        f"version {header.version} · compressed={header.compressed} · "
        f"encryption={header.encryption} · payload at {header.payload_offset}"
    )

    if args.action == "info":
        try:
            apps = abe_mod.list_apps(path, password=args.password)
        except abe_mod.BackupError as exc:
            _print(f"cannot list: {exc}", file=sys.stderr)
            return EXIT_ERROR
        _print(f"apps: {', '.join(apps) if apps else '(none)'}")
        if args.json:
            _print(json.dumps({"header": header.as_dict(), "apps": apps}, indent=2))
        return EXIT_OK

    if args.action == "extract":
        try:
            result = abe_mod.extract(path, args.out, password=args.password, only=args.only)
        except abe_mod.BackupError as exc:
            _print(f"extract failed: {exc}", file=sys.stderr)
            return EXIT_ERROR
        _print(
            f"extracted {len(result.members)} file(s) from {len(result.apps)} app(s) "
            f"into {args.out}"
        )
        for app in result.apps:
            _print(f"  app: {app}")
        for note in result.notes:
            _print(f"note: {note}")
        return EXIT_OK if result.members else EXIT_ERROR

    import tempfile

    with tempfile.TemporaryDirectory(prefix="flcodes-abe-") as temporary:
        try:
            result = abe_mod.extract(path, temporary, password=args.password, only=args.only)
        except abe_mod.BackupError as exc:
            _print(f"extract failed: {exc}", file=sys.stderr)
            return EXIT_ERROR
        _print(
            f"extracted {len(result.members)} file(s) from "
            f"{', '.join(result.apps) if result.apps else 'no app'}"
        )
        harvest = rea.harvest_files([temporary], source_label="adb backup")
        harvest.notes[:0] = [f"backup: {note}" for note in result.notes]
    return _finish_harvest(args, harvest, "backup")


def cmd_apk(args) -> int:
    """Unpack an APK and point at where the app keeps the secret (static REA)."""
    try:
        report_doc = apk_mod.scan_apk(args.file)
    except (OSError, ValueError) as exc:
        _print(f"cannot scan: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        _print(json.dumps(report_doc.as_dict(), indent=2, ensure_ascii=False))
        return EXIT_OK
    _print(f"apk: {report_doc.path} ({report_doc.entries} entries)")
    if report_doc.package_guess:
        _print(f"package (guess): {report_doc.package_guess}")
    _print(f"scanned: {', '.join(report_doc.scanned[:8])}"
           + (" …" if len(report_doc.scanned) > 8 else ""))
    for label, values in apk_mod.ordered_findings(report_doc):
        limit = 6 if label == "url" else 15
        _print()
        _print(f"{label}:")
        for value in values[:limit]:
            _print(f"  {value}")
        if len(values) > limit:
            _print(f"  … {len(values) - limit} more")
    endpoints = apk_mod.interesting_endpoints(report_doc)
    if endpoints:
        _print()
        _print("config endpoints seen in the apk:")
        for endpoint in endpoints[:8]:
            _print(f"  [{endpoint['kind']}] {endpoint['url']}")
    if report_doc.native_libs:
        abis = sorted({lib.split("/")[1] for lib in report_doc.native_libs if lib.count("/") > 1})
        _print()
        _print(f"native libs: {len(report_doc.native_libs)} ({', '.join(abis)})")
    if report_doc.allow_backup is not None:
        _print(f"allowBackup mentioned: {report_doc.allow_backup}")
    for note in report_doc.notes:
        _print(f"note: {note}")
    _print()
    _print("next:")
    _print("  adb backup -f familylink.ab com.google.android.apps.familylink   # confirm on the phone")
    _print("  flcodes abe scan familylink.ab --save --label parent")
    return EXIT_OK


def cmd_device(args) -> int:
    """No-root device workflow: inspect, pull the APK, take an adb backup."""
    try:
        device_mod.adb_path()
    except RuntimeError as exc:
        _print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    serial = getattr(args, "serial", "") or ""

    if args.action == "info":
        info = device_mod.info(serial=serial)
        for key, value in info.props.items():
            _print(f"{key}: {value}")
        _print(f"family link packages: {', '.join(info.packages) or '(none)'}")
        for path in info.apk_paths:
            _print(f"  apk: {path}")
        for note in info.notes:
            _print(f"note: {note}")
        if args.json:
            _print(json.dumps(info.as_dict(), indent=2))
        return EXIT_OK if info.packages else EXIT_ERROR

    if args.action == "apk":
        info = device_mod.info(serial=serial)
        package = args.package or (info.packages[0] if info.packages else "")
        if not package:
            _print("Family Link not found on this device", file=sys.stderr)
            return EXIT_ERROR
        paths = [
            line.split(":", 1)[1]
            for line in device_mod.run(
                ["shell", "pm", "path", package], serial=serial
            ).stdout.decode("utf-8", "replace").splitlines()
            if line.startswith("package:")
        ]
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        pulled = []
        for remote in paths:
            local = out_dir / Path(remote).name
            completed = device_mod.run(["pull", remote, str(local)], serial=serial)
            if completed.returncode == 0 and local.exists():
                pulled.append(str(local))
                _print(f"pulled {remote} -> {local}")
            else:
                _print(f"failed: {remote}", file=sys.stderr)
        if not pulled:
            return EXIT_ERROR
        _print()
        _print("now scan it (no root, no install):")
        for local in pulled[:1]:
            _print(f"  flcodes apk scan '{local}'")
        return EXIT_OK

    if args.action == "backup":
        package = args.package or device_mod.FAMILY_LINK_PACKAGES[0]
        _print("the phone will ask for confirmation — accept it on the device")
        result = device_mod.backup(
            package, args.out, serial=serial, include_apk=args.with_apk,
            timeout=args.timeout,
        )
        _print(f"adb backup: {result['bytes']} bytes in {result['seconds']}s")
        if not result["ok"]:
            _print(f"failed: {result.get('reason')}", file=sys.stderr)
            if result.get("stderr"):
                _print(result["stderr"], file=sys.stderr)
            return EXIT_ERROR
        _print(f"header: {result.get('header')}")
        if args.scan:
            args.file = args.out
            args.only = package
            args.save_all = False
            return cmd_abe(args)
        return EXIT_OK

    raise SystemExit(EXIT_USAGE)


def cmd_verify(args) -> int:
    """Check generated codes against codes Google actually produced."""
    observations = []
    if args.file:
        text = (
            Path(args.file).read_text(encoding="utf-8", errors="replace")
            if args.file != "-"
            else sys.stdin.read()
        )
        observations = verify_mod.parse_observations(text)
    if args.code:
        if args.at:
            timestamp = codes_mod.parse_timestamp(args.at)
        else:
            timestamp = time.time() - max(0, args.minutes) * 60
        observations.append(verify_mod.Observation(args.code, timestamp, note="cli"))
    if not observations:
        _print("error: no observation given (use --code/--at or --file)", file=sys.stderr)
        return EXIT_USAGE

    store = _open_store(args)
    if args.secret:
        keys = [{"secret": secrets_mod.normalize_secret(args.secret), "label": "cli", "id": ""}]
    else:
        seeds = store.load().get("seeds", [])
        if not seeds:
            raise StoreError("no stored key: run `flcodes rea ... --save` first")
        if args.id:
            seeds = [seed for seed in seeds if seed["id"] == args.id]
            if not seeds:
                raise StoreError(f"unknown seed id: {args.id}")
        keys = [
            {
                "secret": seed["secret"],
                "label": seed["label"],
                "id": seed["id"],
                "validity": seed.get("validity"),
                "drift": seed.get("drift"),
            }
            for seed in seeds
        ]

    verifications = verify_mod.verify_keys(
        keys,
        observations,
        tolerance_hours=args.tolerance_hours,
        encoding=args.encoding,
        drift=args.drift,
        discover=not args.no_discover,
    )
    # with --json the machine readable document is the only thing on stdout
    human = sys.stderr if args.json else sys.stdout

    for verification in verifications:
        state = "CONFIRMADO" if verification.confirmed else "não confirmado"
        ttl = f", ttl {verification.validity}s"
        if verification.validity_discovered:
            ttl += " (descoberto)"
        if verification.ambiguous:
            options = ", ".join(f"{value}s" for value in verification.validity_candidates)
            ttl += f" (ambíguo: {options}; use --validity)"
        _print(
            f"key {verification.label} ({verification.seed_id or 'sem id'}): "
            f"{verification.matched}/{verification.total} - {state}{ttl}",
            file=human,
        )
        for result in verification.results if (verification.matched or args.verbose) else []:
            marker = "ok  " if result.matched else "fail"
            drift = (
                f" (deslocamento de {result.delta_hours:+d}h)"
                if result.matched and result.delta_hours
                else ""
            )
            _print(
                f"  [{marker}] observado {result.observation.code} em "
                f"{_human_window_ts(result.observation.timestamp)} -> "
                f"gerado {result.expected}{drift}",
                file=human,
            )

    confirmed = [v for v in verifications if v.confirmed]
    _print(file=human)
    if confirmed:
        _print(
            "confirmado: a chave "
            f"{confirmed[0].label} reproduz todos os códigos observados "
            "(mesma chave, mesmo algoritmo e mesma janela de hora).",
            file=human,
        )
    else:
        _print(
            "não confirmado: nenhuma chave reproduziu o código observado. "
            "Confira o horário da observação, o fuso e tente --tolerance-hours 1.",
            file=human,
        )

    if args.json:
        _print(
            json.dumps(
                verify_mod.report_document(verifications, observations, args.tolerance_hours),
                indent=2,
            )
        )
    if not args.no_report:
        document = verify_mod.report_document(
            verifications, observations, args.tolerance_hours
        )
        path = _out_dir(args) / f"verify-{_now_iso()}.json"
        report.write_json(document, path)
        _print(f"report: {path} (sem segredo)", file=human)
    return EXIT_OK if confirmed else EXIT_ERROR


def _human_window_ts(timestamp: float) -> str:
    moment = _dt.datetime.fromtimestamp(timestamp).astimezone()
    return moment.strftime("%Y-%m-%d %H:%M %Z")


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

    # TOTP determinism and window anchoring
    secret = "AItest-only-secret-value.0"
    hour = 1_700_002_800  # exact hour boundary
    ttl = codes_mod.CODE_VALIDITY_SECONDS
    first = codes_mod.generate_code(secret, hour)
    second = codes_mod.generate_code(secret, hour + ttl - 1)
    check("code is stable inside a window", first.code == second.code)
    third = codes_mod.generate_code(secret, hour + ttl)
    check("code changes on the boundary", first.code != third.code)
    check("code is six digits", len(first.code) == 6 and first.code.isdigit())
    check(
        "window equals the configured ttl",
        first.valid_to - first.valid_from == codes_mod.CODE_VALIDITY_SECONDS,
    )
    ten = codes_mod.generate_code(secret, hour, validity=600)
    check(
        "a different ttl gives a different window",
        (ten.valid_to - ten.valid_from, ten.code) != (3600, first.code),
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
    add_parser.add_argument("--validity", type=int, help="code validity (TTL) in seconds")
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
    gen_parser.add_argument(
        "--validity",
        type=int,
        help="code validity (TTL) in seconds, 60..3600 (default: from the key or 3600)",
    )
    gen_parser.add_argument("--json", action="store_true", help="print JSON records")
    gen_parser.add_argument("--out", help="save codes to a file")
    gen_parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="auto")
    gen_parser.add_argument("--append", action="store_true", default=True)

    stream_parser = sub.add_parser("stream", help="live code with the hourly rollover")
    stream_parser.add_argument("--encoding", choices=("auto", "raw", "base32"), default="auto")
    stream_parser.add_argument("--tz-offset-minutes", type=int, default=0)
    stream_parser.add_argument("--validity", type=int, help="code validity (TTL) in seconds")
    stream_parser.add_argument("--out", help="save every new code to a file")
    stream_parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="csv")

    paths_parser = sub.add_parser(
        "paths", help="list, discover or check the app config endpoints"
    )
    paths_sub = paths_parser.add_subparsers(dest="action", required=True)
    paths_sub.add_parser("list", help="show the known endpoints and their provenance")
    discover_parser = paths_sub.add_parser("discover", help="find endpoints in a capture")
    discover_parser.add_argument("--file", help="HAR/HTML/logcat/JS, '-' for stdin")
    discover_parser.add_argument("--no-report", action="store_true")
    check_parser = paths_sub.add_parser("check", help="request the endpoints and report")
    check_parser.add_argument("--url", action="append", help="endpoint to check (repeatable)")
    check_parser.add_argument("--sapisid", help="SAPISID cookie of the parent session")
    check_parser.add_argument("--cookie-file", help="cookies.txt with SAPISID")
    check_parser.add_argument("--cookie", help="extra cookie header")
    check_parser.add_argument("--timeout", type=float, default=15.0)

    verify_parser = sub.add_parser(
        "verify", help="compare generated codes with codes Google produced"
    )
    verify_parser.add_argument("--code", help="observed six digit code")
    verify_parser.add_argument("--at", help="when the code was observed (ISO or epoch)")
    verify_parser.add_argument(
        "--minutes",
        type=float,
        default=0.0,
        help="the code was observed this many minutes ago (default: now)",
    )
    verify_parser.add_argument(
        "--file", help="CSV (timestamp,code) or JSON observations, '-' for stdin"
    )
    verify_parser.add_argument(
        "--tolerance-hours",
        type=int,
        default=0,
        help="accept a match one hour before/after (clock skew)",
    )
    verify_parser.add_argument("--encoding", choices=("auto", "raw", "base32"), default="auto")
    verify_parser.add_argument(
        "--validity",
        type=int,
        help="code validity (TTL) in seconds; auto-detected when the code does not match",
    )
    verify_parser.add_argument(
        "--drift",
        type=int,
        default=0,
        help="clock drift tolerance in seconds (Chromium allows up to 1800)",
    )
    verify_parser.add_argument(
        "--no-discover",
        action="store_true",
        help="do not try to discover the code validity",
    )
    verify_parser.add_argument("--id", help="only verify this stored key")
    verify_parser.add_argument("--secret", help="verify a secret directly")
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.add_argument("-v", "--verbose", action="store_true", help="detail every key")
    verify_parser.add_argument("--no-report", action="store_true")

    serve_parser = sub.add_parser("serve", help="local web UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--token", help="access token (generated when omitted)")
    serve_parser.add_argument(
        "--allow-embed",
        action="store_true",
        help="allow framing the page (needed only behind a preview proxy)",
    )

    abe_parser = sub.add_parser(
        "abe", help="Android backups (the no-root way into the app's private files)"
    )
    abe_sub = abe_parser.add_subparsers(dest="action", required=True)
    abe_info = abe_sub.add_parser("info", help="header + packages inside the backup")
    abe_info.add_argument("file")
    abe_info.add_argument("--password", help="backup password (only when encrypted)")
    abe_info.add_argument("--json", action="store_true")
    abe_extract = abe_sub.add_parser("extract", help="extract the tar payload")
    abe_extract.add_argument("file")
    abe_extract.add_argument("--out", required=True, help="destination directory")
    abe_extract.add_argument("--password")
    abe_extract.add_argument("--only", help="keep a single package")
    abe_scan = abe_sub.add_parser("scan", help="extract in a temp dir and hunt for the key")
    abe_scan.add_argument("file")
    abe_scan.add_argument("--password")
    abe_scan.add_argument("--only", help="keep a single package")
    abe_scan.add_argument("--save", action="store_true", help="save the best candidate")
    abe_scan.add_argument("--save-all", action="store_true")
    abe_scan.add_argument("--label")
    abe_scan.add_argument("--no-report", action="store_true")
    abe_scan.add_argument("--out-dir")

    apk_parser = sub.add_parser(
        "apk", help="unpack an APK and point at where the app keeps the secret"
    )
    apk_sub = apk_parser.add_subparsers(dest="action", required=True)
    apk_scan = apk_sub.add_parser("scan", help="static scan: private dirs, field names, endpoints")
    apk_scan.add_argument("file")
    apk_scan.add_argument("--json", action="store_true")

    device_parser = sub.add_parser(
        "device", help="no-root device workflow over adb (info, apk, backup)"
    )
    device_sub = device_parser.add_subparsers(dest="action", required=True)
    for name, help_text in (
        ("info", "properties, connected device and the Family Link packages"),
        ("apk", "pull the installed APK splits (world readable) without root"),
        ("backup", "run adb backup for the app and optionally scan it"),
    ):
        child = device_sub.add_parser(name, help=help_text)
        child.add_argument("--serial", help="adb serial (when several devices are attached)")
        child.add_argument("--json", action="store_true")
        if name == "apk":
            child.add_argument("--package")
            child.add_argument("--out", default="out/apk")
        if name == "backup":
            child.add_argument("--package", default="com.google.android.apps.familylink")
            child.add_argument("--out", default="out/familylink.ab")
            child.add_argument("--with-apk", action="store_true")
            child.add_argument("--timeout", type=float, default=600.0)
            child.add_argument("--scan", action="store_true", help="scan the backup afterwards")
            child.add_argument("--save", action="store_true")
            child.add_argument("--save-all", action="store_true")
            child.add_argument("--label")
            child.add_argument("--no-report", action="store_true")
            child.add_argument("--password")
            child.add_argument("--out-dir")

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
        "verify": cmd_verify,
        "paths": cmd_paths,
        "abe": cmd_abe,
        "apk": cmd_apk,
        "device": cmd_device,
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
