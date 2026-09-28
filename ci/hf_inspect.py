#!/usr/bin/env python3
import urllib.request, json, sys, os, subprocess
TOKEN = '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'
REPO = "enzo123456789/sla1"
FILE = "BeamNG.drive.7z"
def req(url, head=False, rng=None):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if head: req.get_method = lambda: "HEAD"
    if rng: req.add_header("Range", rng)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if head:
                return dict(r.headers), r.status
            return r.read(), r.status, dict(r.headers)
    except Exception as e:
        return str(e), 0, {}
print("== whoami ==")
try:
    import urllib.request
    req=urllib.request.Request("https://huggingface.co/api/whoami-v2")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    d=json.loads(urllib.request.urlopen(req, timeout=15).read())
    print("ok, user type:", d.get("type"), "email:", d.get("email"))
except Exception as e:
    print("whoami falhou:", e); sys.exit(1)
print("== repo metadata ==")
req=urllib.request.Request(f"https://huggingface.co/api/models/{REPO}")
req.add_header("Authorization", f"Bearer {TOKEN}")
try:
    meta=json.loads(urllib.request.urlopen(req,timeout=15).read())
    print("id:", meta.get("id"),"privado:",meta.get("private"))
    sib=[s.get("rfilename") for s in meta.get("siblings",[])]
    print("arquivos:",len(sib))
    for n in sib[:80]: print(" ",n)
except Exception as e:
    print("repo falhou:",e); sys.exit(1)
print("== file HEAD ==")
try:
    req=urllib.request.Request(f"https://huggingface.co/{REPO}/resolve/main/{FILE}")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.get_method=lambda:"HEAD"
    with urllib.request.urlopen(req,timeout=15) as r:
        for k,v in r.headers.items(): print(f" {k}: {v}")
except Exception as e:
    print("HEAD falhou:",e)
print("== 512KB ==")
try:
    req=urllib.request.Request(f"https://huggingface.co/{REPO}/resolve/main/{FILE}",
        headers={"Authorization":f"Bearer {TOKEN}", "Range":"bytes=0-524287"})
    data=urllib.request.urlopen(req,timeout=30).read()
    open("/tmp/head.bin","wb").write(data)
    print("bytes recebidos:",len(data))
except Exception as e:
    print("download falhou:",e); sys.exit(0)
