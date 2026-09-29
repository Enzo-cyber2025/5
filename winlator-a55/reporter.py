#!/usr/bin/env python3
import json, os, sys, urllib.request
log_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/wl-build.log"
issue_num = os.environ["ISSUE_NUM"]
repo = os.environ["GITHUB_REPOSITORY"]
tok = os.environ["GH_TOKEN"]
try:
    with open(log_path, "rb") as f:
        log = f.read().decode("utf-8", "replace")
except FileNotFoundError:
    log = "(log file not found)"
log = log[-55000:]  # deixa o final (onde fica o erro)
body = "## Winlator-A55 build log (tail)\n\n```\n" + log + "\n```\n"
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/issues/{issue_num}/comments",
    data=json.dumps({"body": body}).encode(),
    headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
    method="POST")
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("comment posted", r.status)
except Exception as e:
    print("ERR comment", e)
