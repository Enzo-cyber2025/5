import os, sys, json, urllib.request
TOKEN = os.environ.get("HF_TOKEN","")
REPO = "enzo123456789/sla1"
FILE = "BeamNG.drive.7z"
def hf(url, method=None, rng=None):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if method: req.get_method = lambda: method
    if rng: req.add_header("Range", rng)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read() if method!="HEAD" else b"", r.status, dict(r.headers)
    except Exception as e:
        return str(e).encode(), 0, {}
print("== whoami ==")
try:
    req=urllib.request.Request("https://huggingface.co/api/whoami-v2",
        headers={"Authorization":f"Bearer {TOKEN}"})
    d=json.loads(urllib.request.urlopen(req,timeout=15).read())
    print("auth ok. tipo:", d.get("type"),"email:",d.get("email"))
except Exception as e:
    print("whoami FALHOU:",e); sys.exit(1)
print("== metadata do repo ==")
try:
    req=urllib.request.Request(f"https://huggingface.co/api/models/{REPO}",
        headers={"Authorization":f"Bearer {TOKEN}"})
    meta=json.loads(urllib.request.urlopen(req,timeout=15).read())
    print("id:",meta.get("id"),"privado:",meta.get("private"))
    sib=[s.get("rfilename") for s in meta.get("siblings",[])]
    print("total de arquivos:",len(sib))
    for n in sib[:120]: print(" ",n)
except Exception as e:
    print("repo FALHOU:",e); sys.exit(1)
print("== HEAD HTTP do arquivo ==")
_,sc,hdr = hf(f"https://huggingface.co/{REPO}/resolve/main/{FILE}", method="HEAD")
print("status:",sc)
for k in ("content-length","content-type","location","etag","x-error-code"):
    if k in hdr: print(f"  {k}: {hdr[k]}")
print("== primeiros 512KB ==")
data,sc,hdr = hf(f"https://huggingface.co/{REPO}/resolve/main/{FILE}", rng="bytes=0-524287")
print("status:",sc,"bytes:",len(data))
if sc==206 or sc==200:
    open("/tmp/head.bin","wb").write(data)
    import subprocess
    print("file(1):", subprocess.check_output(["file","/tmp/head.bin"]).decode().strip())
    print("magic hex:")
    print(subprocess.check_output(["xxd","-l","64","/tmp/head.bin"]).decode())
    print("strings iniciais:")
    out=subprocess.check_output(["strings","-n","8","/tmp/head.bin"]).decode(errors="replace").splitlines()
    for line in out[:40]: print(" ",line)
else:
    print("erro:",data[:400].decode(errors="replace"))
