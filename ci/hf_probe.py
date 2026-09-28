import sys, os, urllib.request, urllib.error, json
TOKEN = sys.argv[1]
REPO = "enzo123456789/sla1"
FILE = "BeamNG.drive.7z"
def fetch(url, method=None, rng=None):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if method: req.get_method = lambda: method
    if rng: req.add_header("Range", rng)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.read() if method != "HEAD" else b"", r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        try: body = e.read()
        except Exception: body = str(e).encode()
        return body, e.code, dict(e.headers)
    except Exception as e:
        return str(e).encode(), 0, {}
print("== WHOAMI ==")
b,sc,h = fetch("https://huggingface.co/api/whoami-v2")
print("status:", sc)
print(b[:300].decode(errors="replace"))
print()
print("== REPO METADATA ==")
b,sc,h = fetch(f"https://huggingface.co/api/models/{REPO}")
print("status:", sc)
try:
    meta = json.loads(b)
    print("id:", meta.get("id"), "privado:", meta.get("private"))
    sib = [s.get("rfilename") for s in meta.get("siblings",[])]
    print("arquivos:", len(sib))
    for n in sib[:80]: print(" ", n)
except Exception as e:
    print("json falhou:", e)
    print(b[:1500].decode(errors="replace"))
print()
print("== FILE HEAD ==")
b,sc,h = fetch(f"https://huggingface.co/{REPO}/resolve/main/{FILE}", method="HEAD")
print("status:", sc)
for k in ("content-length","content-type","location","etag","x-error-code","x-repo-id"):
    if k in h: print(f"  {k}: {h[k]}")
if sc >= 400: print("ERRO:", b[:600].decode(errors="replace"))
print()
print("== 1 MB INICIAL ==")
b,sc,h = fetch(f"https://huggingface.co/{REPO}/resolve/main/{FILE}", rng="bytes=0-1048575")
print("status:", sc, "bytes:", len(b))
if sc in (200,206):
    open("/tmp/head.bin","wb").write(b)
    import subprocess
    print(subprocess.check_output(["file","/tmp/head.bin"]).decode())
    print(subprocess.check_output(["xxd","-l","32","/tmp/head.bin"]).decode())
    print("primeiros 6 bytes hex:", b[:6].hex(), "(esperado 377abcaf271c para 7z)")
    try:
        out = subprocess.check_output(["7z","l","/tmp/head.bin"], stderr=subprocess.STDOUT, timeout=15).decode(errors="replace")
        print("-- 7z list (primeiros 60 linhas):")
        print("\n".join(out.splitlines()[:60]))
    except subprocess.CalledProcessError as e:
        print("-- 7z falhou:")
        print(e.output.decode(errors="replace")[:1200] if e.output else "sem output")
