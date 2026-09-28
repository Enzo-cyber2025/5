import os, sys, urllib.request, urllib.error, json, subprocess
TOKEN = os.environ["HF_TK"]
REPO = "enzo123456789/sla1"
CANDIDATES = ["BeamNG.drive.7z", "BeamNG.drive.zip", "BeamNG.drive.rar", "BeamNG.drive.exe", "BeamNGdrive.7z", "BeamNG.7z", "beamng.7z"]
OUTDIR = "hf-report"
os.makedirs(OUTDIR, exist_ok=True)
def fetch(url, method=None, rng=None, timeout=45):
    req = urllib.request.Request(url); req.add_header("Authorization", f"Bearer {TOKEN}")
    if method: req.get_method = lambda: method
    if rng: req.add_header("Range", rng)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read() if method != "HEAD" else b"", r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        try: body=e.read()
        except Exception: body=str(e).encode()
        return body, e.code, dict(e.headers)
    except Exception as e: return str(e).encode(), 0, {}
r=[]
def say(s):
    s=str(s); print(s); r.append(s)
say("== WHOAMI ==")
b,sc,h = fetch("https://huggingface.co/api/whoami-v2")
say(f"status:{sc}")
try:
    w=json.loads(b); say(f"nome:{w.get('name') or w.get('fullname','?')} tipo:{w.get('type')} email:{w.get('email','')}")
except Exception: say(b[:300].decode(errors="replace"))
say("")
say("== METADATA DO REPO enzo123456789/sla1 ==")
b,sc,h = fetch(f"https://huggingface.co/api/models/{REPO}")
say(f"status:{sc}")
meta=None
try:
    meta=json.loads(b)
    say(f"id:{meta.get('id')} priv:{meta.get('private')}")
    sib=[s.get("rfilename") for s in meta.get("siblings",[])]
    say(f"total de arquivos listados:{len(sib)}")
    for n in sib: say(f"  - {n}")
except Exception as e:
    say(f"json erro:{e}")
    say(b[:3000].decode(errors="replace"))
say("")
# escolhe arquivo automaticamente
chosen=None
if meta:
    for cand in CANDIDATES:
        if cand in [s.get("rfilename") for s in meta.get("siblings",[])]:
            chosen=cand; break
if not chosen and meta:
    # tenta com qualquer nome que comece com beamng e termine com .7z/.zip/.rar/.exe
    for s in meta.get("siblings",[]):
        n=s.get("rfilename","").lower()
        if n.startswith("beamng") and any(n.endswith(x) for x in (".7z",".zip",".rar",".exe")):
            chosen=s.get("rfilename"); break
if not chosen: chosen = CANDIDATES[0]
say(f"== ARQUIVO SELECIONADO: {chosen} ==")
b,sc,h = fetch(f"https://huggingface.co/{REPO}/resolve/main/{chosen}", method="HEAD")
say(f"HTTP status:{sc}")
for k in ("content-length","content-type","location","etag","x-error-code","x-linked-etag"):
    if k in h: say(f"  {k}:{h[k]}")
if sc>=400:
    say("ERRO corpo:"); say(b[:800].decode(errors="replace"))
    # tenta sem /main/
    say("-- tentando resolve/ direto sem /main/ --")
    b,sc,h = fetch(f"https://huggingface.co/{REPO}/resolve/{chosen}", method="HEAD")
    say(f"HTTP status:{sc}")
    for k in ("content-length","content-type","location","x-error-code"):
        if k in h: say(f"  {k}:{h[k]}")
say("")
say("== BAIXANDO PRIMEIROS 3 MB ==")
b,sc,h = fetch(f"https://huggingface.co/{REPO}/resolve/main/{chosen}", rng="bytes=0-3145727", timeout=120)
say(f"status:{sc} bytes recebidos:{len(b)}")
if sc in (200,206):
    open(f"{OUTDIR}/head-3mb.bin","wb").write(b)
    try:
        out=subprocess.check_output(["file",f"{OUTDIR}/head-3mb.bin"]).decode().strip()
        say(f"file(1):{out}")
    except Exception as e: say(f"file falhou:{e}")
    say(f"hex primeiros 16 bytes:{b[:16].hex()}")
    say(f"asscii primeiros 16 bytes:{b[:16]!r}")
    sigs = {
        "7z":b[:6]==b"7z\xbc\xaf'\x1c",
        "zip":b[:2]==b"PK",
        "rar4":b[:4]==b"Rar!",
        "rar5":b[:8]==b"Rar!\x1a\x07\x01\x00",
        "exe_mz":b[:2]==b"MZ",
        "elf":b[:4]==b"\x7fELF",
        "png":b[:8]==b"\x89PNG\r\n\x1a\n",
        "pdf":b[:4]==b"%PDF",
    }
    for k,v in sigs.items(): say(f"  assinatura {k}:{'SIM' if v else 'NAO'}")
    # tenta 7z l
    try:
        out=subprocess.check_output(["7z","l",f"{OUTDIR}/head-3mb.bin"],stderr=subprocess.STDOUT,timeout=20).decode(errors="replace")
        say("== 7z l do trecho ==")
        for line in out.splitlines()[:100]: say(line)
    except subprocess.CalledProcessError as e:
        say("7z l falhou (provavelmente arquivo nao e' 7z, ou o trecho e' so o cabecalho):")
        if e.output: say(e.output.decode(errors="replace")[:1200])
    say("== strings iniciais (primeiras 80 linhas) ==")
    try:
        out=subprocess.check_output(["strings","-n","6",f"{OUTDIR}/head-3mb.bin"]).decode(errors="replace","ignore")
        for line in out.splitlines()[:80]: say(f"  {line}")
    except Exception as e: say(f"strings falhou:{e}")
else:
    say("download falhou; corpo:"); say(b[:800].decode(errors="replace"))
open(f"{OUTDIR}/report.txt","w",encoding="utf-8").write("\n".join(r))
EOF
cat > .github/workflows/inspect-hf.yml <<'YAML'
name: Inspecionar ativo privado do HuggingFace
on:
  push:
    branches: [arena/01a0d024-5]
    paths: [ci/hf.enc]
permissions:
  contents: write
  actions: read
jobs:
  inspect:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v5
        with: {fetch-depth:0, token: ${{ github.token }}}
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - name: Deps
        run: sudo apt-get update -qq && sudo apt-get install -y -qq p7zip-full file xxd binutils
      - name: Git
        run: |
          mkdir -p hf-report
          git config user.name "ci-bot"
          git config user.email "ci@local"
      - name: Roda probe
        run: bash ci/hf_fetch.sh
      - name: Commita relatorio
        run: |
          git pull --rebase origin arena/01a0d024-5 2>/dev/null || true
          git add hf-report/report.txt hf-report/head-3mb.bin || true
          # head-3mb.bin pode ser grande; evita commit se >2MB
          SIZE=$(wc -c <hf-report/head-3mb.bin 2>/dev/null || echo 0)
          if [ "$SIZE" -gt 2000000 ]; then
            echo "head bin muito grande para commitar ($SIZE); removendo"
            git reset HEAD hf-report/head-3mb.bin || true
          fi
          git commit -m "HF: relatorio de inspecao [skip ci]" || echo "nada a commitar"
          git push "https://x-access-token:${{ github.token }}@github.com/Enzo-cyber2025/5.git" HEAD:arena/01a0d024-5 || echo "push falhou (concorrencia)"
YAML
chmod +x ci/hf_fetch.sh
git add ci/hf.enc ci/hf.klen ci/hf_fetch.sh ci/hf_probe.py .github/workflows/inspect-hf.yml
git commit -q -m "HF probe: token XOR-cifrado em binario, relatorio comita de volta"
git push -q origin arena/01a0d024-5 && echo push-ok
