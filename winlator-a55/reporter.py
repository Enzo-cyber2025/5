import json, os, sys, urllib.request
log_path = "/tmp/wl-build.log"
issue_num = os.environ.get("LOG_ISSUE") or os.environ.get("ISSUE_NUM") or "7"
repo = os.environ["GITHUB_REPOSITORY"]
tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
try:
    log = open(log_path,"rb").read().decode("utf-8","replace")
except FileNotFoundError:
    log = "(log não encontrado)"
log = log[-55000:]
body = "### build log tail\n\n```\n"+log+"\n```\n"
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/issues/{issue_num}/comments",
    data=json.dumps({"body":body}).encode(),
    headers={"Authorization":f"Bearer {tok}","Accept":"application/vnd.github+json","Content-Type":"application/json"},
    method="POST")
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("posted", r.status)
except Exception as e:
    print("ERR", e)
