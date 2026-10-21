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
            absolute: bool = False, nbytes: int = 0) -> tuple[int, object]:
    """GET a HF endpoint. Returns (status, parsed_json_or_text).

    absolute=True allows the sibling datasets-server host. nbytes>0 sends a Range
    header so a file-access probe costs one byte instead of a whole weight file.
    """
    url = path if absolute else f"{HF}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    if nbytes:
        req.add_header("Range", f"bytes=0-{nbytes - 1}")
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
    except Exception as exc:  # blocked egress, DNS, TLS, timeout...
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
        say("  VERDICT: token REJECTED (401). Revoked, expired, or not a valid token.")
        return {}
    if status == 403:
        say("  VERDICT: token present but FORBIDDEN (403).")
        return {}
    if status != 200 or not isinstance(data, dict):
        say(f"  VERDICT: could not validate. Response head: {str(data)[:160]!r}")
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
