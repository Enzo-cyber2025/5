#!/usr/bin/env python3
"""Probe a Hugging Face token that lives in a GitHub Actions secret or variable.

Design rule: this runs on a PUBLIC repository, so everything printed here ends up
in publicly readable logs and commits. The script therefore never prints a token
and never prints identity material (account name, e-mail, org names, repo names).
Only secret/variable NAMES, formats, lengths, enum values, counts and HTTP status
codes are reported.

Two ways to feed it:

* --inventory        read the JSON of ``toJSON(secrets)`` / ``toJSON(vars)`` from
                     the environment. Finds a token under any name, but GitHub
                     holds such a run for manual approval.
* --named-inventory  read the values of individually referenced secrets listed in
                     SECRET_NAMES / VAR_NAMES, mapped positionally onto the
                     S01..Snn and V01..Vnn environment variables of the job.

Only values that already look like HF tokens (``hf_`` prefix) are ever sent to
huggingface.co, so unrelated credentials are not handed to a third party.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

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

HF_NAME_RE = r"(?i)(^|_)(hf|hugging|hub|llama|gemma|transformer)s?(_|$)"

# Targets the owner asked about by name. Probed both anonymously (public
# discovery, needs no token) and authenticated (what the token can reach).
DEFAULT_TARGETS = ["sla1"]
TARGETS: list[str] = list(DEFAULT_TARGETS)

# Set by --reveal-names for PRIVATE local runs only. Never enable it in CI on
# this repository: the logs and commits of a public repo are public.
REVEAL = False


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


def request(path: str, token: str | None, timeout: int = 30,
            absolute: bool = False, nbytes: int = 0,
            byte_range: tuple[int, int] | None = None, as_bytes: bool = False
            ) -> tuple[int, object]:
    """GET a HF endpoint. Returns (status, parsed_json_or_text).

    absolute=True allows the sibling datasets-server host. nbytes>0 sends a Range
    header so a file-access probe costs one byte instead of a whole weight file.
    """
    url = path if absolute else f"{HF}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    if nbytes:
        req.add_header("Range", f"bytes=0-{nbytes - 1}")
    elif byte_range:
        req.add_header("Range", f"bytes={byte_range[0]}-{byte_range[1]}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                payload = gzip.GzipFile(fileobj=io.BytesIO(payload)).read()
            if as_bytes:
                return resp.status, payload
            body = payload.decode("utf-8", "replace")
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
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": body[:120]}
        return exc.code, parsed
    except Exception as exc:  # blocked egress, DNS, TLS, timeout...
        return -1, f"{type(exc).__name__}: {exc}"


SAFE_ERROR_HINTS = (
    ("invalid username or password", "invalid-credentials"),
    ("invalid credentials", "invalid-credentials"),
    ("not authenticated", "not-authenticated"),
    ("must be logged in", "login-required"),
    ("unauthorized", "unauthorized"),
    ("forbidden", "forbidden"),
    ("gated", "gated"),
    ("not found", "not-found"),
    ("rate limit", "rate-limited"),
    ("internal server error", "server-error"),
    ("bad request", "bad-request"),
)


def classify_error(data: object) -> str:
    """Reduce an API error body to a fixed label instead of echoing it.

    Printing the server's own message is a leak vector: an error string can carry
    the account name or other identity data, and this repository's logs are public.
    A closed vocabulary of labels keeps the diagnostics without the exposure.
    """
    msg = ""
    if isinstance(data, dict):
        for key in ("error", "message", "error_description"):
            value = data.get(key)
            if isinstance(value, str) and value:
                msg = value
                break
    elif isinstance(data, str):
        msg = data
    if not msg:
        return "<no error message>"
    low = msg.lower()
    for needle, label in SAFE_ERROR_HINTS:
        if needle in low:
            return f"{label} ({len(msg)} chars)"
    return f"<unrecognised error message withheld, {len(msg)} chars>"


def say(*args: object) -> None:
    print(*args, flush=True)


def bullet(label: str, value: object) -> None:
    say(f"  - {label}: {value}")


def report_whoami(status: int, data: object) -> dict:
    """Print the non-identity part of whoami-v2."""
    say("\n[2] Authenticated identity check  (GET /api/whoami-v2)")
    bullet("HTTP status", status)
    if status == 401:
        say("  VERDICT: token REJECTED (401). Revoked, expired, or not a valid token.")
        return {}
    if status == 403:
        say("  VERDICT: token present but FORBIDDEN (403).")
        return {}
    if status != 200 or not isinstance(data, dict):
        say(f"  VERDICT: could not validate (HTTP {status}). "
            f"error={classify_error(data)}")
        say("  Neither the response body nor the server's own error text is printed:")
        say("  both can carry the account name, and these logs are public.")
        return {}

    say("  VERDICT: token ACCEPTED (200).")
    if REVEAL:
        bullet("account name", data.get("name", "?"))
        bullet("fullname", data.get("fullname", "?"))
        bullet("email", data.get("email", "<not exposed>"))
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
            label = org.get("name", "?") if REVEAL else "<name withheld>"
            say(f"      org[{idx}] name={label} type={org.get('type', '?')} "
                f"isEnterprise={org.get('isEnterprise', '?')}")

    auth = data.get("auth") or {}
    if isinstance(auth, dict):
        bullet("auth.type", auth.get("type", "?"))
        access = auth.get("accessToken") or {}
        if isinstance(access, dict):
            bullet("token role", access.get("role", "?"))
            bullet("token type", access.get("type", "?"))
            bullet("extra keys under accessToken",
                   sorted(k for k in access if k not in ("role", "type")))
            bullet("token createdAt", access.get("createdAt", "?"))
            bullet("token displayName",
                   access.get("displayName") if REVEAL else "<withheld: user-chosen label>")
            fg = access.get("fineGrained")
            if isinstance(fg, dict):
                say("  fine-grained permission set (what this token may actually do):")
                for scope in sorted(fg):
                    val = fg[scope]
                    if isinstance(val, list):
                        # Scoped repo ids would name private repos: count them only.
                        say(f"      {scope}: {len(val)} item(s) "
                            f"{'-> ' + ', '.join(map(str, val[:20])) if REVEAL else '(ids withheld)'}")
                    elif isinstance(val, dict):
                        say(f"      {scope}: {json.dumps(val, sort_keys=True)[:300]}")
                    else:
                        say(f"      {scope}: {val}")
            elif fg is not None:
                bullet("fineGrained", str(fg)[:200])
        bullet("auth keys", sorted(auth.keys()))
    bullet("whoami top-level keys", sorted(data.keys()))
    return data


def report_owned(name: str, token: str) -> None:
    """Count the account's own repos. Names withheld, only shapes are shown."""
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
            # Shape only by default: library/pipeline/tags, never the repo name.
            rid = f" id={item.get('id')}" if REVEAL else ""
            say(f"      {kind[:-1]}[{idx}]{rid} private={bool(item.get('private'))} "
                f"gated={item.get('gated')} library={item.get('library_name')} "
                f"pipeline={item.get('pipeline_tag')} "
                f"downloads={item.get('downloads')} likes={item.get('likes')}")


def pick_file(meta: object) -> str:
    """Choose the cheapest file that proves gate access."""
    siblings = (meta or {}).get("siblings") if isinstance(meta, dict) else None
    names = [x.get("rfilename") for x in (siblings or [])
             if isinstance(x, dict) and x.get("rfilename")]
    for preferred in ("config.json", "README.md", "dataset_infos.json",
                      ".gitattributes", "tokenizer_config.json"):
        if preferred in names:
            return preferred
    return names[0] if names else ""


def report_gated(token: str) -> None:
    """Probe gated repos by fetching a FILE, not its metadata.

    Metadata endpoints answer 200 anonymously even for gated repos, so they prove
    nothing. Each probe therefore fetches one byte of a real file twice - once
    anonymously and once authenticated - and the difference is the verdict.
    """
    say("\n[4] Gated-repo access probe (file fetch, anonymous vs authenticated)")
    say("  Metadata is public even for gated repos, so only a FILE fetch proves access.")
    for kind, repo in GATED_PROBES:
        plural = f"{kind}s"
        status, meta = request(f"/api/{plural}/{urllib.parse.quote(repo)}", token)
        gate = meta.get("gated") if isinstance(meta, dict) else "?"
        fname = pick_file(meta)
        if not fname:
            bullet(repo, f"metadata HTTP {status} gated={gate} | no file listed to probe")
            continue
        path = f"/{repo}/resolve/main/{urllib.parse.quote(fname)}"
        anon, _ = request(path, None, nbytes=1)
        auth, _ = request(path, token, nbytes=1)
        if gate in (False, "false", None) and anon == 200:
            verdict = "NOT actually gated - open to everyone, proves nothing"
        elif auth == 200 and anon != 200:
            verdict = "ACCESS GRANTED - the token passes the gate"
        elif auth == 200 and anon == 200:
            verdict = "open file, gate not enforced on it"
        elif auth in (401, 403):
            verdict = "DENIED - gate not approved for this account"
        else:
            verdict = "inconclusive"
        bullet(repo, f"gated={gate} | file anon HTTP {anon} vs auth HTTP {auth} -> {verdict}")


def report_write(token: str, name: str) -> None:
    """Non-destructive write-scope probe: nothing is created, changed or deleted."""
    say("\n[5] Write capability")
    say("  No write operation was attempted (nothing created, changed or deleted).")
    status, _ = request("/api/whoami-v2", token)
    bullet("whoami re-check", f"HTTP {status}")
    if name:
        status, _ = request(f"/api/models?author={urllib.parse.quote(name)}&limit=1", token)
        bullet("namespace listing readable", f"HTTP {status}")
    say("  Read the 'token role' line in section [2]: 'write' or 'fineGrained' means")
    say("  uploads/deletes are possible with this token; 'read' means download only.")


def inventory(secrets: dict, variables: dict, source: str) -> list[tuple[str, str, str]]:
    """List what is visible and pick out HF-looking candidates.

    Returns [(kind, name, value)] for candidates worth authenticating.
    """
    notes: list[str] = []
    candidates: list[tuple[str, str, str]] = []

    say("=" * 72)
    say(f"Inventory of secrets/variables ({source})")
    say("=" * 72)

    # Control: proves the secrets context actually resolves in this job, so an
    # all-empty inventory cannot be a false negative. GITHUB_TOKEN is always
    # injected; only its presence and length are reported, never its value.
    ctrl = os.environ.get("CTRL_GITHUB_TOKEN")
    if ctrl is None:
        say("control: not run (CTRL_GITHUB_TOKEN not provided)")
    elif ctrl:
        say(f"control: secrets.GITHUB_TOKEN visible to this job : YES (length={len(ctrl)})")
        say("         -> the secrets context resolves here, so 'not set' below is a")
        say("            real absence, not a permission or ref quirk.")
    else:
        say("control: secrets.GITHUB_TOKEN visible to this job : NO")
        say("         -> the secrets context is NOT resolving in this job, so an")
        say("            empty inventory below would be INCONCLUSIVE.")
    say("")

    if secrets:
        present = {k: v for k, v in secrets.items() if str(v)}
        notes.append(f"names probed as secrets : {len(secrets)}")
        notes.append(f"of those, actually set  : {len(present)}")
        for name in sorted(secrets):
            value = str(secrets[name] or "")
            if not value:
                notes.append(f"  secret {name:<30} not set")
                continue
            looks_hf = value.startswith("hf_")
            hints = bool(re.search(HF_NAME_RE, name))
            notes.append(f"  secret {name:<30} SET length={len(value):<3} "
                         f"hf_prefix={'yes' if looks_hf else 'no'} "
                         f"name_hints_hf={'yes' if hints else 'no'}")
            if looks_hf or (hints and 20 <= len(value) <= 80):
                candidates.append(("secret", name, value))
    else:
        notes.append("no secret names were probed")

    if variables:
        present_v = {k: v for k, v in variables.items() if str(v)}
        notes.append(f"names probed as variables: {len(variables)}")
        notes.append(f"of those, actually set   : {len(present_v)}")
        for name in sorted(variables):
            value = str(variables[name] or "")
            if not value:
                notes.append(f"  var    {name:<30} not set")
                continue
            looks_hf = value.startswith("hf_")
            notes.append(f"  var    {name:<30} SET length={len(value):<3} "
                         f"hf_prefix={'yes' if looks_hf else 'no'}")
            if looks_hf:
                notes.append(f"  WARNING: {name} holds an HF-looking token as a VARIABLE,"
                             " not a secret - variables are readable by anyone with repo"
                             " access and are not masked in logs.")
                candidates.append(("variable", name, value))
    else:
        notes.append("no variable names were probed")

    for line in notes:
        say(line)
    say("")
    return candidates


def named_inventory() -> tuple[dict, dict]:
    """Read individually referenced secrets/variables from the job environment.

    SECRET_NAMES / VAR_NAMES list the real names in order; the job maps them
    positionally onto S001..Snnn and V001..Vnnn (three digits, so the sweep can
    grow past 99 names without changing this contract).
    """
    secret_names = os.environ.get("SECRET_NAMES", "").split()
    var_names = os.environ.get("VAR_NAMES", "").split()
    secrets = {n: os.environ.get(f"S{i:03d}", "") for i, n in enumerate(secret_names, 1)}
    variables = {n: os.environ.get(f"V{i:03d}", "") for i, n in enumerate(var_names, 1)}
    return secrets, variables


def context_inventory() -> tuple[dict, dict]:
    """Read the toJSON(secrets) / toJSON(vars) blobs from the environment."""
    def load(blob: str) -> dict:
        if not blob.strip():
            return {}
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    return load(os.environ.get("SECRETS_JSON", "")), load(os.environ.get("VARS_JSON", ""))


def report_target(token: str | None, target: str, me: str = "") -> None:
    """Look for a Hub resource named `target`.

    Runs anonymously too, so public discovery does not depend on a token. Ids of
    PUBLIC matches are printed - they are world-readable by definition, so naming
    them leaks nothing. Ids of PRIVATE matches are withheld: a private id would
    expose its owner namespace in this public repo's logs.
    """
    say(f"\n[7] Named target probe: '{target}'")
    say(f"  mode: {'authenticated' if token else 'ANONYMOUS - no token available'}")
    if not target:
        say("  skipped: empty target")
        return

    quoted = urllib.parse.quote(target)
    for kind in ("models", "datasets", "spaces"):
        q = urllib.parse.urlencode({"search": target, "limit": "50", "full": "true"})
        status, data = request(f"/api/{kind}?{q}", token)
        if status != 200 or not isinstance(data, list):
            bullet(f"{kind} search", f"HTTP {status}")
            continue
        exact = [d for d in data if isinstance(d, dict)
                 and str(d.get("id", "")).split("/")[-1].lower() == target.lower()]
        public = [d for d in data if isinstance(d, dict) and not d.get("private")]
        private = [d for d in data if isinstance(d, dict) and d.get("private")]
        bullet(f"{kind} search", f"HTTP {status} | {len(data)} hits | "
               f"{len(exact)} exact name match | {len(public)} public | {len(private)} private")
        for item in public[:15]:
            say(f"      public: {item.get('id')} downloads={item.get('downloads')} "
                f"likes={item.get('likes')} gated={item.get('gated')} "
                f"pipeline={item.get('pipeline_tag')}")
        if private:
            say(f"      {len(private)} private hit(s): ids WITHHELD (a private id would"
                " reveal its owner namespace in these public logs)")

        # Is `target` itself a namespace (user or org) owning repos?
        q2 = urllib.parse.urlencode({"author": target, "limit": "50", "full": "true"})
        status2, data2 = request(f"/api/{kind}?{q2}", token)
        if status2 == 200 and isinstance(data2, list):
            bullet(f"namespace '{target}' owns {kind}", len(data2))
            for item in data2[:15]:
                if not isinstance(item, dict):
                    continue
                shown = item.get("id") if not item.get("private") else "<private id withheld>"
                say(f"      {shown} downloads={item.get('downloads')} "
                    f"gated={item.get('gated')}")
        else:
            bullet(f"namespace '{target}' owns {kind}", f"HTTP {status2}")

        # Bare id (no namespace) - HF rejects these, but the status is informative.
        status3, _ = request(f"/api/{kind}/{quoted}", token)
        bullet(f"GET /api/{kind}/{target}", f"HTTP {status3}")

    # Does the account itself own anything named like the target?
    if me:
        for kind in ("models", "datasets", "spaces"):
            q = urllib.parse.urlencode({"author": me, "search": target,
                                        "limit": "50", "full": "true"})
            status, data = request(f"/api/{kind}?{q}", token)
            if status == 200 and isinstance(data, list):
                shown = [d.get("id") for d in data
                         if isinstance(d, dict) and not d.get("private")]
                hidden = sum(1 for d in data if isinstance(d, dict) and d.get("private"))
                bullet(f"own {kind} matching '{target}'",
                       f"{len(data)} ({len(shown)} public, {hidden} private)")
                for sid in shown[:15]:
                    say(f"      {sid}")
            else:
                bullet(f"own {kind} matching '{target}'", f"HTTP {status}")


def report_owned_deep(token: str, name: str, kind: str = "datasets") -> None:
    """Structural description of every repo the account owns.

    Answers 'check all the datasets' without naming them: ids of private repos
    stay withheld because this repository, and therefore its logs, are public.
    """
    if not name:
        return
    say(f"\n[9] Every owned {kind} (structure only, ids withheld)")
    q = urllib.parse.urlencode({"author": name, "full": "true", "limit": "1000"})
    status, data = request(f"/api/{kind}?{q}", token)
    if status != 200 or not isinstance(data, list) or not data:
        say(f"  nothing to describe (HTTP {status})")
        return
    for idx, item in enumerate(data, 1):
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or "")
        label = rid if (REVEAL or not item.get("private")) else "<private id withheld>"
        say(f"  {kind[:-1]}[{idx}] {label}")
        enc = urllib.parse.quote(rid)
        st, tree = request(f"/api/{kind}/{enc}/tree/main?recursive=true&expand=true", token)
        if st == 200 and isinstance(tree, list):
            files = [t for t in tree if isinstance(t, dict) and t.get("type") == "file"]
            dirs = [t for t in tree if isinstance(t, dict) and t.get("type") == "directory"]
            exts: dict[str, int] = {}
            total = biggest = 0
            for f in files:
                pname = str(f.get("path") or "")
                ext = pname.rsplit(".", 1)[-1].lower() if "." in pname else "<no ext>"
                exts[ext] = exts.get(ext, 0) + 1
                size = int(f.get("size") or 0)
                total += size
                biggest = max(biggest, size)
            say(f"      files={len(files)} dirs={len(dirs)} "
                f"total={total / 1e6:.2f} MB largest={biggest / 1e6:.2f} MB")
            say(f"      extensions={dict(sorted(exts.items(), key=lambda kv: -kv[1]))}")
            say(f"      private={bool(item.get('private'))} gated={item.get('gated')} "
                f"downloads={item.get('downloads')} likes={item.get('likes')}")
            say(f"      lastModified={item.get('lastModified')} sha={str(item.get('sha'))[:12]}")
            if REVEAL:
                for f in files[:60]:
                    say(f"        {f.get('path')} ({f.get('size')} bytes)")
        else:
            say(f"      tree not readable (HTTP {st})")


def report_target_deep(token: str | None, target: str, kind: str = "datasets") -> None:
    """Describe the CONTENTS of a matched repo, structurally.

    File names, column names and the repo id are withheld unless --reveal-names:
    on a public repo those would disclose what a private dataset actually holds.
    Counts, sizes, shapes and timestamps are reported instead.
    """
    say(f"\n[8] Deep probe of '{target}' ({kind}) - structure only")
    q = urllib.parse.urlencode({"search": target, "limit": "50", "full": "true"})
    status, data = request(f"/api/{kind}?{q}", token)
    if status != 200 or not isinstance(data, list):
        say(f"  could not locate it (HTTP {status})")
        return
    matches = [d for d in data if isinstance(d, dict)
               and str(d.get("id", "")).split("/")[-1].lower() == target.lower()]
    if not matches:
        say("  no exact name match to probe")
        return
    for m in matches:
        rid = str(m.get("id"))
        owner = rid.split("/")[0]
        say(f"  match: owner namespace {'=' + owner if REVEAL else 'WITHHELD (private repo)'}"
            f" | private={bool(m.get('private'))}")
        enc = urllib.parse.quote(rid)
        st, meta = request(f"/api/{kind}/{enc}", token)
        if st != 200 or not isinstance(meta, dict):
            bullet("metadata", f"HTTP {st}")
            continue
        bullet("metadata", f"HTTP {st}")
        bullet("private / gated / disabled",
               f"{meta.get('private')} / {meta.get('gated')} / {meta.get('disabled')}")
        bullet("lastModified", meta.get("lastModified"))
        bullet("commit sha", str(meta.get("sha"))[:12])
        bullet("downloads / likes", f"{meta.get('downloads')} / {meta.get('likes')}")
        bullet("tags", len(meta.get("tags") or []))
        card = meta.get("cardData")
        bullet("cardData", sorted(card.keys()) if isinstance(card, dict) else card)
        sibs = [x.get("rfilename") for x in (meta.get("siblings") or [])
                if isinstance(x, dict) and x.get("rfilename")]
        bullet("files declared in metadata", len(sibs))

        # Real tree with sizes.
        st, tree = request(f"/api/{kind}/{enc}/tree/main?recursive=true&expand=true", token)
        if st == 200 and isinstance(tree, list):
            files = [t for t in tree if isinstance(t, dict) and t.get("type") == "file"]
            dirs = [t for t in tree if isinstance(t, dict) and t.get("type") == "directory"]
            exts: dict[str, int] = {}
            total = 0
            biggest = 0
            for f in files:
                name = str(f.get("path") or "")
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else "<no ext>"
                exts[ext] = exts.get(ext, 0) + 1
                size = int(f.get("size") or 0)
                total += size
                biggest = max(biggest, size)
            bullet("tree", f"HTTP {st} | {len(files)} files | {len(dirs)} directories")
            bullet("extensions", dict(sorted(exts.items(), key=lambda kv: -kv[1])))
            bullet("total bytes", f"{total} ({total / 1e6:.2f} MB)")
            bullet("largest file", f"{biggest} ({biggest / 1e6:.2f} MB)")
            if REVEAL:
                for f in files[:40]:
                    say(f"      {f.get('path')} ({f.get('size')} bytes)")
        else:
            bullet("tree", f"HTTP {st} (not readable)")

        # Splits / rows / columns from the datasets-server sibling API.
        st, info = request(
            f"https://datasets-server.huggingface.co/info?dataset={enc}",
            token, absolute=True)
        if st == 200 and isinstance(info, dict):
            di = info.get("dataset_info")
            if isinstance(di, list):
                for conf in di:
                    cname = conf.get("config_name") if REVEAL else "<config name withheld>"
                    feats = conf.get("features") or []
                    splits = conf.get("splits") or []
                    bullet(f"datasets-server config {cname}",
                           f"{len(feats)} columns | {len(splits)} splits")
                    types: dict[str, int] = {}
                    for f in feats:
                        if isinstance(f, dict):
                            t = str(f.get("type"))[:40]
                            types[t] = types.get(t, 0) + 1
                    bullet("column types", types)
                    for sp in splits:
                        if isinstance(sp, dict):
                            sname = sp.get("name") if REVEAL else "<split name withheld>"
                            say(f"      split {sname}: rows={sp.get('num_examples') or sp.get('num_rows')}")
                    if REVEAL:
                        for f in feats[:60]:
                            if isinstance(f, dict):
                                say(f"      column: {f.get('name')} : {f.get('type')}")
            else:
                bullet("datasets-server info", f"HTTP {st} but unexpected shape")
        else:
            bullet("datasets-server info", f"HTTP {st}")

        st, size = request(
            f"https://datasets-server.huggingface.co/size?dataset={enc}",
            token, absolute=True)
        if st == 200 and isinstance(size, dict):
            ds = size.get("size", {})
            if isinstance(ds, dict):
                bullet("datasets-server size",
                       f"dataset={ds.get('dataset')} rows={ds.get('rows')} "
                       f"downloaded_size={ds.get('downloaded_size')} "
                       f"in_memory={ds.get('in_memory_size')}")
        else:
            bullet("datasets-server size", f"HTTP {st}")


PE_MACHINE = {
    0x014C: "x86 (i386)",
    0x8664: "x64 (AMD64)",
    0xAA64: "ARM64",
    0x01C4: "ARMNT (ARM32)",
    0x01C0: "ARM",
    0x0200: "IA64",
}


def parse_pe_head(buf: bytes) -> dict | None:
    """Read the PE header fields that settle the merge/port questions.

    Nothing here is decompilation: these are the same fields `file(1)` reports.
    The decisive one is the CLR data directory (index 14) - a non-zero RVA means
    a .NET assembly, which is the only kind of DLL any merge tool can fold into
    an EXE. Its absence means native code, loaded by name at run time.
    """
    if len(buf) < 64 or buf[:2] != b"MZ":
        return None
    e_lfanew = int.from_bytes(buf[0x3C:0x40], "little")
    if e_lfanew <= 0 or e_lfanew + 24 > len(buf):
        return None
    if buf[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return None
    coff = e_lfanew + 4
    machine = int.from_bytes(buf[coff:coff + 2], "little")
    sections = int.from_bytes(buf[coff + 2:coff + 4], "little")
    chars = int.from_bytes(buf[coff + 18:coff + 20], "little")
    opt = coff + 20
    magic = int.from_bytes(buf[opt:opt + 2], "little")
    pe32plus = magic == 0x20B
    base = opt + (112 if pe32plus else 96)          # start of data directories
    clr_rva = 0
    if base + 14 * 8 + 4 <= len(buf):
        clr_rva = int.from_bytes(buf[base + 14 * 8:base + 14 * 8 + 4], "little")
    subsystem = int.from_bytes(buf[opt + 68:opt + 70], "little") if opt + 70 <= len(buf) else 0
    return {
        "machine": PE_MACHINE.get(machine, f"0x{machine:04x}"),
        "format": "PE32+" if pe32plus else ("PE32" if magic == 0x10B else f"magic 0x{magic:x}"),
        "kind": "DLL" if chars & 0x2000 else "EXE",
        "dotnet": clr_rva != 0,
        "subsystem": {2: "GUI", 3: "console"}.get(subsystem, str(subsystem)),
        "sections": sections,
    }


def inflate_prefix(comp: bytes, method: int, need: int = 1400) -> bytes:
    """Recover the first bytes of a ZIP entry without downloading the entry."""
    if method == 0:
        return comp[:need * 2]
    if method != 8:
        return b""                                    # not deflate: not handled
    try:
        return zlib.decompressobj(-15).decompress(comp, need * 4)
    except zlib.error:
        return b""


def inspect_pe_entries(url: str, token: str, entries: list) -> None:
    """Fetch ~8 KB per PE entry and report its header. ~100 KB for a whole game."""
    if not entries:
        return
    say("  PE header inspection (local header + inflated prefix, ~8 KB each):")
    results = []
    for idx, (name, method, lho, usize) in enumerate(entries[:24], 1):
        label = name if REVEAL else f"<PE {idx}/{min(len(entries), 24)}, name withheld>"
        if lho == 0xFFFFFFFF:
            say(f"    - {label}: ZIP64 local offset unresolved, skipped")
            continue
        st, blk = request(url, token, byte_range=(lho, lho + 8191), as_bytes=True)
        if st not in (200, 206) or not isinstance(blk, bytes) or len(blk) < 30:
            say(f"    - {label}: HTTP {st}, header not read")
            continue
        if blk[:4] != b"PK\x03\x04":
            say(f"    - {label}: local file header not found")
            continue
        nlen = int.from_bytes(blk[26:28], "little")
        elen = int.from_bytes(blk[28:30], "little")
        head = inflate_prefix(blk[30 + nlen + elen:], method)
        info = parse_pe_head(head)
        if not info:
            say(f"    - {label}: method={method}, {len(head)} bytes inflated - "
                f"no PE signature")
            continue
        results.append(info)
        say(f"    - {label}: {info['kind']} {info['machine']} {info['format']} "
            f"subsystem={info['subsystem']} sections={info['sections']} -> "
            f"{'MANAGED (.NET)' if info['dotnet'] else 'NATIVE (no CLR directory)'}")
    if not results:
        return
    managed = [r for r in results if r["dotnet"]]
    bullet("inspected", f"{len(results)} PE file(s): {len(managed)} .NET, "
           f"{len(results) - len(managed)} native")
    bullet("machine types present", sorted({r["machine"] for r in results}))
    if not managed:
        say("  VERDICT (measured, not assumed):")
        say("    - No .NET assembly here. ILMerge, ILRepack, Costura and dotPeek all")
        say("      operate on .NET metadata. For native PE there is no tool that folds")
        say("      separate DLLs into one working EXE: the OS loader resolves each by")
        say("      name at run time, and the exports are not relocatable.")
    if not any("ARM64" in r["machine"] or "ARM" in r["machine"] for r in results):
        say("    - No ARM binary present. 'Recompile for ARM64' means recompiling")
        say("      SOURCE, and this archive contains binaries, not source.")


def inventory_remote_zip(url: str, token: str, size: int) -> None:
    """List a remote ZIP's contents by reading only its central directory.

    A ZIP stores its entry table at the END of the file, so the whole archive
    never has to be downloaded: one Range request for the tail locates the End Of
    Central Directory record, a second fetches the table itself. For a multi-GB
    archive this costs tens of kilobytes instead of gigabytes.
    """
    tail_len = min(size, 66_000)
    st, tail = request(url, token, byte_range=(size - tail_len, size - 1), as_bytes=True)
    if st not in (200, 206) or not isinstance(tail, bytes):
        bullet("tail fetch", f"HTTP {st} - cannot read the central directory")
        return
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        bullet("EOCD", "not found - not a plain ZIP, or it is split/spanned")
        return
    total = int.from_bytes(tail[eocd + 10:eocd + 12], "little")
    cd_size = int.from_bytes(tail[eocd + 12:eocd + 16], "little")
    cd_off = int.from_bytes(tail[eocd + 16:eocd + 20], "little")

    # ZIP64 carries the real values when the 32-bit fields are saturated.
    if total == 0xFFFF or cd_off == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        loc = tail.rfind(b"PK\x06\x07")
        say("  ZIP64 in use")
        if loc >= 0:
            z64_off = int.from_bytes(tail[loc + 8:loc + 16], "little")
            st64, z64 = request(url, token, byte_range=(z64_off, z64_off + 55), as_bytes=True)
            if st64 in (200, 206) and isinstance(z64, bytes) and z64[:4] == b"PK\x06\x06":
                total = int.from_bytes(z64[32:40], "little")
                cd_size = int.from_bytes(z64[40:48], "little")
                cd_off = int.from_bytes(z64[48:56], "little")

    if cd_size <= 0 or cd_off < 0:
        bullet("central directory", f"unusable (size={cd_size} offset={cd_off})")
        return
    say(f"  central directory: offset={cd_off} size={cd_size} entries={total}")
    st, cd = request(url, token, byte_range=(cd_off, cd_off + cd_size - 1), as_bytes=True)
    if st not in (200, 206) or not isinstance(cd, bytes):
        bullet("central directory fetch", f"HTTP {st}")
        return

    exts: dict[str, int] = {}
    ext_bytes: dict[str, int] = {}
    pe_entries: list = []
    abis: set = set()
    dex = 0
    v1_sig = False
    n = 0
    biggest = ("", 0)
    pos = 0
    while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        name_len = int.from_bytes(cd[pos + 28:pos + 30], "little")
        extra_len = int.from_bytes(cd[pos + 30:pos + 32], "little")
        cmt_len = int.from_bytes(cd[pos + 32:pos + 34], "little")
        usize = int.from_bytes(cd[pos + 24:pos + 28], "little")
        csize = int.from_bytes(cd[pos + 20:pos + 24], "little")
        method = int.from_bytes(cd[pos + 10:pos + 12], "little")
        lho = int.from_bytes(cd[pos + 42:pos + 46], "little")
        name = cd[pos + 46:pos + 46 + name_len].decode("utf-8", "replace")
        # ZIP64 stores, in order, whichever of these three saturated to all-ones.
        if 0xFFFFFFFF in (usize, csize, lho):
            ex = cd[pos + 46 + name_len:pos + 46 + name_len + extra_len]
            vals: list = []
            i = 0
            while i + 4 <= len(ex):
                hid = int.from_bytes(ex[i:i + 2], "little")
                hsz = int.from_bytes(ex[i + 2:i + 4], "little")
                if hid == 0x0001:
                    vals = [int.from_bytes(ex[i + 4 + k * 8:i + 12 + k * 8], "little")
                            for k in range(hsz // 8)]
                    break
                i += 4 + hsz
            k = 0
            if usize == 0xFFFFFFFF and k < len(vals):
                usize = vals[k]; k += 1
            if csize == 0xFFFFFFFF and k < len(vals):
                csize = vals[k]; k += 1
            if lho == 0xFFFFFFFF and k < len(vals):
                lho = vals[k]; k += 1
        n += 1
        low = name.lower()
        ext = low.rsplit(".", 1)[-1] if "." in low.rsplit("/", 1)[-1] else "<dir/no ext>"
        exts[ext] = exts.get(ext, 0) + 1
        ext_bytes[ext] = ext_bytes.get(ext, 0) + usize
        if usize > biggest[1]:
            biggest = (name, usize)
        if ext in ("dll", "exe", "sys", "ocx", "cpl"):
            pe_entries.append((name, method, lho, usize))
        abi = re.match(r"(?:.*/)?lib/([^/]+)/.+\Z", name)
        if abi:
            abis.add(abi.group(1))
        if ext == "dex":
            dex += 1
        if low.startswith("meta-inf/") and ext in ("rsa", "dsa", "ec"):
            v1_sig = True
        pos += 46 + name_len + extra_len + cmt_len

    bullet("entries parsed", n)
    bullet("uncompressed total", f"{sum(ext_bytes.values()) / 1e9:.3f} GB")
    bullet("by extension (count)", dict(sorted(exts.items(), key=lambda kv: -kv[1])[:25]))
    bullet("by extension (uncompressed GB)",
           {k: round(v / 1e9, 3) for k, v in
            sorted(ext_bytes.items(), key=lambda kv: -kv[1])[:15]})
    pe = [e for e in exts if e in ("dll", "exe", "sys", "ocx", "cpl")]
    bullet("Windows PE binaries present", f"{sorted(pe)}" if pe else "NONE")
    weights = [e for e in exts if e in ("gguf", "safetensors", "bin", "pt", "pth",
                                        "onnx", "tflite", "ckpt", "msgpack", "h5")]
    bullet("model-weight-looking files present", f"{sorted(weights)}" if weights else "NONE")
    inspect_pe_entries(url, token, pe_entries)
    if dex or abis or v1_sig:
        # The APK Signing Block sits immediately before the central directory and
        # ends with size_of_block(8) + the magic "APK Sig Block 42"(16). Reading
        # those 24 bytes proves a v2/v3 signature without fetching the file.
        blk_st, blk = request(url, token, byte_range=(cd_off - 24, cd_off - 1),
                              as_bytes=True)
        v2_sig = (blk_st in (200, 206) and isinstance(blk, bytes)
                  and blk[8:24] == b"APK Sig Block 42")
        say("  Android package structure:")
        bullet("classes*.dex", dex)
        bullet("native ABI directories", sorted(abis) if abis else "NONE (no lib/ entries)")
        bullet("v1 signature (META-INF/*.RSA)", "present" if v1_sig else "absent")
        bullet("v2/v3 signature (APK Signing Block)", "present" if v2_sig else "absent")
        if abis:
            if "arm64-v8a" in abis:
                say("  -> carries lib/arm64-v8a/: has ARM64 native code, so it can run")
                say("     natively on a 64-bit ARM phone.")
            else:
                say(f"  -> native code for {sorted(abis)} ONLY: no arm64-v8a, so on a")
                say("     64-bit ARM phone the native library will fail to load.")
        else:
            say("  -> no lib/ entries at all: no native code, so the ABI does not")
            say("     matter - ART runs the DEX on any architecture.")

    bullet("largest entry", f"{biggest[1] / 1e9:.3f} GB "
           f"{biggest[0] if REVEAL else '(name withheld)'}")
    if REVEAL:
        say("  full listing:")
        pos = 0
        shown = 0
        while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02" and shown < 200:
            name_len = int.from_bytes(cd[pos + 28:pos + 30], "little")
            extra_len = int.from_bytes(cd[pos + 30:pos + 32], "little")
            cmt_len = int.from_bytes(cd[pos + 32:pos + 34], "little")
            usize = int.from_bytes(cd[pos + 24:pos + 28], "little")
            name = cd[pos + 46:pos + 46 + name_len].decode("utf-8", "replace")
            say(f"      {name}  {usize} bytes")
            shown += 1
            pos += 46 + name_len + extra_len + cmt_len


def report_archives(token: str, target: str, kind: str = "datasets") -> None:
    """Inventory the archives inside the target repo without downloading them."""
    say(f"\n[10] Archive inventory of '{target}' (central directory only, no download)")
    q = urllib.parse.urlencode({"search": target, "limit": "50", "full": "true"})
    st, data = request(f"/api/{kind}?{q}", token)
    if st != 200 or not isinstance(data, list):
        say(f"  cannot locate the repo (HTTP {st})")
        return
    matches = [d for d in data if isinstance(d, dict)
               and str(d.get("id", "")).split("/")[-1].lower() == target.lower()]
    if not matches:
        say("  no exact name match")
        return
    rid = str(matches[0]["id"])
    enc = urllib.parse.quote(rid)
    st, tree = request(f"/api/{kind}/{enc}/tree/main?recursive=true&expand=true", token)
    if st != 200 or not isinstance(tree, list):
        say(f"  tree not readable (HTTP {st})")
        return
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        path = str(entry.get("path") or "")
        size = int(entry.get("size") or 0)
        low = path.lower()
        label = path if REVEAL else f"<{low.rsplit('.', 1)[-1]} file, name withheld>"
        if low.endswith((".zip", ".apk", ".jar", ".aar", ".xapk", ".whl")):
            # An APK is a ZIP; so are JAR, AAR and wheel. Same reader applies.
            kind_label = low.rsplit(".", 1)[-1].upper()
            say(f"  {kind_label} {label} ({size / 1e9:.3f} GB)")
            inventory_remote_zip(f"/{kind}/{enc}/resolve/main/{urllib.parse.quote(path)}",
                                 token, size)
        elif low.endswith((".7z", ".rar")):
            # 7z/RAR keep their header at the end too, but the format needs a real
            # parser; report what is cheap and say so honestly.
            st2, head = request(f"/{kind}/{enc}/resolve/main/{urllib.parse.quote(path)}",
                                token, nbytes=6, as_bytes=True)
            sig = head[:6] if isinstance(head, bytes) else b""
            is7z = sig == b"7z\xbc\xaf\'\x1c"
            bullet(f"{low.rsplit('.', 1)[-1].upper()} {label}",
                   f"{size / 1e9:.3f} GB | signature={'valid 7z' if is7z else 'not 7z'} | "
                   "listing needs a full download or the 7z binary, not attempted")
        else:
            bullet(label, f"{size} bytes (not an archive)")


def report_egress() -> None:
    """Prove the runner can reach huggingface.co, even with no token to test.

    Without this, 'no token found' would leave open the question of whether the
    harness itself works once a token is added.
    """
    say("\n[6] Egress check (unauthenticated, so the harness is proven ready)")
    status, data = request("/api/whoami-v2", None)
    if status == 401:
        bullet("GET /api/whoami-v2 without a token", "HTTP 401 -> reachable, "
               "and correctly rejects an anonymous caller")
    elif status == -1:
        bullet("GET /api/whoami-v2 without a token", "FAILED -> the runner cannot "
               "reach huggingface.co either; fix egress before trusting any verdict")
    else:
        bullet("GET /api/whoami-v2 without a token", f"HTTP {status} (unexpected)")
    status, data = request("/api/models?limit=1", None)
    bullet("GET /api/models?limit=1 without a token",
           f"HTTP {status} -> {'public API readable' if status == 200 else 'not readable'}")
    say("  Conclusion: as soon as a token is added to the secrets, this probe can")
    say("  authenticate it and report what it reaches.")


def run_probe(label: str, token: str) -> int:
    """Validate one token and report what it can reach."""
    say("=" * 72)
    say("Hugging Face secret probe - no token material is printed")
    say("=" * 72)
    say(f"\n[1] Secret under test: {label}")
    token = (token or "").strip()
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
        say("\n  The runner could not reach huggingface.co at all - that is a network")
        say("  egress problem, not a token problem. Nothing can be concluded yet.")
        return 1
    if status != 200 or not isinstance(who, dict) or not who:
        return 1

    account = str(who.get("name") or "")
    report_owned(account, token)
    report_owned_deep(token, account, "datasets")
    report_owned_deep(token, account, "models")
    report_gated(token)
    report_write(token, account)
    for target in TARGETS:
        report_target(token, target, me=account)
        report_target_deep(token, target, "datasets")
        report_target_deep(token, target, "models")
        report_archives(token, target, "datasets")

    say("\n" + "=" * 72)
    say("SUMMARY")
    say("=" * 72)
    say("  token valid      : yes (HTTP 200 on whoami-v2)")
    say(f"  token format     : {classify(token)}")
    say(f"  account type     : {who.get('type')}")
    say(f"  plan             : {who.get('plan')}")
    say(f"  orgs             : {len(who.get('orgs') or [])}")
    say("  identity, org names and repo names are intentionally NOT printed:")
    say("  this repository is public, so its workflow logs are public too.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="HF_TOKEN_VALUE")
    parser.add_argument("--label", default="")
    parser.add_argument("--inventory", action="store_true",
                        help="use the toJSON(secrets)/toJSON(vars) contexts")
    parser.add_argument("--named-inventory", action="store_true",
                        help="use SECRET_NAMES/VAR_NAMES mapped onto S001../V001.. env vars")
    parser.add_argument("--token-file",
                        help="read the token from this file (local private runs; keeps it "
                             "out of shell history and of the process list)")
    parser.add_argument("--target", action="append", default=None,
                        help="Hub resource name to look for (repeatable). Defaults to "
                             "'sla1'. Probed anonymously as well as authenticated.")
    parser.add_argument("--reveal-names", action="store_true",
                        help="PRIVATE LOCAL USE ONLY: also print account name, org names and "
                             "repo ids. Never use this in CI on a public repository.")
    args = parser.parse_args()

    global REVEAL, TARGETS
    REVEAL = args.reveal_names
    if args.target:
        TARGETS = [t.strip() for t in args.target if t.strip()]
    if REVEAL:
        say("!! --reveal-names is ON: identity and repo names WILL be printed.")
        say("!! Safe only on a private/local run. Public logs would expose them.")
        say("")

    if args.token_file:
        try:
            with open(args.token_file, encoding="utf-8") as fh:
                os.environ[args.env] = fh.read().strip()
        except OSError as exc:
            say(f"could not read --token-file: {exc}")
            return 2

    if not (args.inventory or args.named_inventory):
        token = (os.environ.get(args.env) or "").strip()
        return run_probe(label=args.label or args.env, token=token)

    if args.named_inventory:
        secrets, variables = named_inventory()
        source = "individually referenced names"
    else:
        secrets, variables = context_inventory()
        source = "toJSON(secrets)/toJSON(vars) context"

    candidates = inventory(secrets, variables, source)

    if not candidates:
        say("RESULT: no Hugging Face token is configured under the names probed.")
        say("        Nothing to authenticate, nothing to access.")
        report_egress()

        # Dry run of the authenticated path with a placeholder that is not a real
        # credential, so the branch that will run once a token exists is proven
        # end to end before anyone has to hand over a secret.
        dry = os.environ.get("DRY_RUN_TOKEN", "").strip()
        if dry:
            say("")
            say("#" * 72)
            say("# Dry run of the authenticated path (placeholder, NOT a real token)")
            say("#" * 72)
            run_probe(label="DRY_RUN_TOKEN placeholder", token=dry)
        say("")
        say("No token, but the named targets can still be looked up anonymously:")
        for target in TARGETS:
            report_target(None, target)
        return 0

    say(f"HF-looking candidates: {[(k, n) for k, n, _ in candidates]}")
    failures = 0
    for idx, (kind, name, value) in enumerate(candidates, 1):
        say("")
        say("#" * 72)
        say(f"# Candidate {idx}/{len(candidates)}: {kind} '{name}'")
        say("#" * 72)
        failures += 1 if run_probe(label=f"{name} ({kind})", token=value) != 0 else 0
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
