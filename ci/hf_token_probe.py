#!/usr/bin/env python3
"""Probe a Hugging Face token that lives in a GitHub Actions secret.

Design rule: this script runs on a PUBLIC repository, so everything it prints
ends up in publicly readable workflow logs. It therefore never prints the token
and never prints identity material (username, e-mail, org names, repo names).
Only formats, counts, enum values and HTTP status codes are reported.

The token is read from the environment variable named by --env (default
HF_TOKEN_VALUE). GitHub masks registered secret strings in logs regardless, but
we do not rely on that: nothing sensitive is ever handed to stdout.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HF = "https://huggingface.co"
UA = "ci/hf-token-probe (github actions)"

# Repositories used to probe gated access. Only the HTTP status is reported, so
# this list reveals nothing about the account.
GATED_PROBES = [
    ("model", "meta-llama/Llama-3.1-8B"),
    ("model", "google/gemma-3-4b-it"),
    ("model", "mistralai/Mistral-Nemo-Instruct-2407"),
    ("dataset", "allenai/c4"),
]


def classify(token: str) -> str:
    """Describe the token format without revealing it."""
    if token.startswith("hf_pat_"):
        return "fine-grained PAT (hf_pat_...)"
    if token.startswith("hf_rep_"):
        return "repository-scoped token (hf_rep_...)"
    if token.startswith("hf_api_"):
        return "api token (hf_api_...)"
    if token.startswith("hf_"):
        return "classic token (hf_...)"
    return "string that does not look like an HF token"


def request(path: str, token: str | None, timeout: int = 30) -> tuple[int, object]:
    """GET a HF endpoint. Returns (status, parsed_json_or_text)."""
    url = f"{HF}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            body = raw.decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body[:200]
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b""
        if exc.headers and exc.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        body = raw.decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body[:200]
        return exc.code, payload
    except Exception as exc:  # network egress blocked, DNS, TLS, timeout...
        return -1, f"{type(exc).__name__}: {exc}"


def say(*args: object) -> None:
    print(*args, flush=True)


def bullet(label: str, value: object) -> None:
    say(f"  - {label}: {value}")


def report_whoami(status: int, data: object) -> dict:
    """Print the non-identity part of whoami-v2."""
    say("\n[2] Authenticated identity check  (GET /api/whoami-v2)")
    bullet("HTTP status", status)
    if status == 401:
        say("  VERDICT: token REJECTED (401). It is revoked, expired or mistyped.")
        return {}
    if status == 403:
        say("  VERDICT: token present but FORBIDDEN (403).")
        return {}
    if status != 200 or not isinstance(data, dict):
        say(f"  VERDICT: could not validate. Response head: {str(data)[:160]!r}")
        return {}

    say("  VERDICT: token ACCEPTED (200).")
    bullet("account type", data.get("type", "?"))
    bullet("plan", data.get("plan", "?"))
    bullet("isPro", data.get("isPro", "?"))
    bullet("isPaid", data.get("isPaid", "?"))
    bullet("periodEnd", data.get("periodEnd", "?"))
    bullet("canPay", data.get("canPay", "?"))

    orgs = data.get("orgs") or []
    bullet("orgs (count only, names withheld)", len(orgs))
    for idx, org in enumerate(orgs, 1):
        if isinstance(org, dict):
            say(f"      org[{idx}] type={org.get('type', '?')} "
                f"isEnterprise={org.get('isEnterprise', '?')} "
                f"role={org.get('role', '?')}")

    auth = data.get("auth") or {}
    if isinstance(auth, dict):
        bullet("auth.type", auth.get("type", "?"))
        access = auth.get("accessToken") or {}
        if isinstance(access, dict):
            bullet("token role", access.get("role", "?"))
            bullet("token type", access.get("type", "?"))
            # Keys only: shows what the API told us without printing values.
            bullet("extra keys under accessToken", sorted(k for k in access if k not in ("role", "type")))
        bullet("auth keys", sorted(auth.keys()))
    bullet("whoami top-level keys", sorted(data.keys()))
    return data


def report_owned(name: str, token: str) -> None:
    """Count the account's own repos. Names are withheld, only shapes are shown."""
    say("\n[3] What the token can see on its own account")
    if not name:
        say("  skipped: no validated account name.")
        return
    for kind in ("models", "datasets", "spaces"):
        q = urllib.parse.urlencode({"author": name, "full": "true", "limit": "1000"})
        status, data = request(f"/api/{kind}?{q}", token)
        if status != 200 or not isinstance(data, list):
            bullet(kind, f"query failed (HTTP {status})")
            continue
        private = sum(1 for d in data if isinstance(d, dict) and d.get("private"))
        gated = sum(1 for d in data if isinstance(d, dict) and d.get("gated"))
        downloads = sum(int(d.get("downloads") or 0) for d in data if isinstance(d, dict))
        bullet(kind, f"{len(data)} total | {private} private | {gated} gated | {downloads} downloads")
        for idx, item in enumerate(data[:12], 1):
            if not isinstance(item, dict):
                continue
            # Shape only: library/pipeline/tags, never the repo name.
            say(f"      {kind[:-1]}[{idx}] private={bool(item.get('private'))} "
                f"gated={item.get('gated')} library={item.get('library_name')} "
                f"pipeline={item.get('pipeline_tag')} "
                f"downloads={item.get('downloads')} likes={item.get('likes')}")


def report_gated(token: str) -> None:
    """Probe a few well-known gated repos. Only status codes are printed."""
    say("\n[4] Gated-repo access probe (status codes only)")
    for kind, repo in GATED_PROBES:
        status, _ = request(f"/api/{kind}s/{urllib.parse.quote(repo)}", token)
        meaning = {
            200: "ACCESS GRANTED",
            401: "not authenticated / gate not accepted",
            403: "gate requested but NOT granted for this account",
            404: "hidden from this account (treated as not granted)",
            -1: "request never reached huggingface.co",
        }.get(status, f"unexpected status {status}")
        bullet(f"{kind} {repo}", f"HTTP {status} -> {meaning}")


def report_write(token: str, name: str) -> None:
    """Non-destructive write-scope probe.

    We deliberately do NOT create, edit or delete anything on the Hub. The role
    reported by whoami-v2 is authoritative enough, and we only confirm that the
    token can read the account's own namespace listing.
    """
    say("\n[5] Write capability")
    say("  No write operation was attempted (nothing created, changed or deleted).")
    status, _ = request("/api/whoami-v2", token)
    bullet("whoami re-check", f"HTTP {status}")
    if name:
        status, _ = request(f"/api/models?author={urllib.parse.quote(name)}&limit=1", token)
        bullet("namespace listing readable", f"HTTP {status}")
    say("  Read the 'token role' line in section [2]: 'write' or 'fineGrained' means")
    say("  uploads/deletes are possible with this token; 'read' means download only.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="HF_TOKEN_VALUE")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    token = (os.environ.get(args.env) or "").strip()
    label = args.label or args.env

    say("=" * 72)
    say("Hugging Face secret probe - no token material is printed")
    say("=" * 72)
    say(f"\n[1] Secret under test: {label}")
    if not token:
        say("  RESULT: secret is EMPTY / not defined for this ref.")
        say("  Nothing further to test.")
        return 0
    bullet("length", len(token))
    bullet("format", classify(token))
    bullet("charset ok", token.replace("_", "").isalnum())

    status, data = request("/api/whoami-v2", token)
    who = report_whoami(status, data)
    if status == -1:
        say("\n  The runner could not reach huggingface.co at all - this is a network")
        say("  egress problem, not a token problem. Nothing can be concluded yet.")
        return 1
    if status != 200 or not isinstance(who, dict) or not who:
        return 1

    account = str(who.get("name") or "")
    report_owned(account, token)
    report_gated(token)
    report_write(token, account)

    say("\n" + "=" * 72)
    say("SUMMARY")
    say("=" * 72)
    say(f"  token valid      : yes (HTTP 200 on whoami-v2)")
    say(f"  token format     : {classify(token)}")
    say(f"  account type     : {who.get('type')}")
    say(f"  plan             : {who.get('plan')}")
    say(f"  orgs             : {len(who.get('orgs') or [])}")
    say("  identity, org names and repo names are intentionally NOT printed:")
    say("  this repository is public, so its workflow logs are public too.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
