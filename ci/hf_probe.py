import sys, os, urllib.request, urllib.error, json, subprocess
TOKEN = sys.argv[1]; REPO = "enzo123456789/sla1"; FILE = "BeamNG.drive.7z"; OUTDIR = "hf-report"
os.makedirs(OUTDIR, exist_ok=True)
def fetch(url, method=None, rng=None):
    req = urllib.request.Request(url); req.add_header("Authorization", f"Bearer {TOKEN}")
    if method: req.get_method = lambda: method
    if rng: req.add_header("Range", rng)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read() if method != "HEAD" else b"", r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        try: body=e.read()
        except Exception: body=str(e).encode()
        return body, e.code, dict(e.headers)
    except Exception as e: return str(e).encode(),0,{}
r=[]
def say(s): print(s); r.append(s)
say("== WHOAMI ==")
b,sc,h=fetch("https://huggingface.co/api/whoami-v2"); say(f"status:{sc}"); say(b[:500].decode(errors="replace"))
say("== REPO ==")
b,sc,h=fetch(f"https://huggingface.co/api/models/{REPO}"); say(f"status:{sc}")
try:
    meta=json.loads(b); say(f"id:{meta.get('id')} priv:{meta.get('private')}")
    sib=[s.get("rfilename") for s in meta.get("siblings",[])]; say(f"arquivos:{len(sib)}")
    for n in sib: say(f"  {n}")
except Exception as e: say(f"json falhou:{e}"); say(b[:3000].decode(errors="replace"))
say("== FILE HEAD ==")
b,sc,h=fetch(f"https://huggingface.co/{REPO}/resolve/main/{FILE}",method="HEAD"); say(f"status:{sc}")
for k in ("content-length","content-type","location","etag"):
    if k in h: say(f" {k}:{h[k]}")
say("== BAIXANDO 2MB ==")
b,sc,h=fetch(f"https://huggingface.co/{REPO}/resolve/main/{FILE}",rng="bytes=0-2097151"); say(f"status:{sc} bytes:{len(b)}")
open(f"{OUTDIR}/head-2mb.bin","wb").write(b)
if sc in (200,206):
    try: say(subprocess.check_output(["file",f"{OUTDIR}/head-2mb.bin"]).decode())
    except Exception as e: say(f"file:{e}")
    say("hex16:"+b[:16].hex())
    say("7z sig: "+("SIM" if b[:6]==b"7z\xbc\xaf'\x1c" else "NAO"))
    say("zip sig: "+("SIM" if b[:2]==b"PK" else "NAO"))
    say("rar sig: "+("SIM" if b[:7].startswith(b"Rar!\x1a\x07") else "NAO"))
    try:
        out=subprocess.check_output(["7z","l",f"{OUTDIR}/head-2mb.bin"],stderr=subprocess.STDOUT,timeout=20).decode(errors="replace")
        for line in out.splitlines()[:80]: say(line)
    except subprocess.CalledProcessError as e:
        say("7z falhou:"); say((e.output.decode(errors="replace") if e.output else "")[:1500])
open(f"{OUTDIR}/report.txt","w").write("\n".join(r))
