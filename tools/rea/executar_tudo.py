#!/usr/bin/env python3
"""Reproduz o pipeline R.E.A. inteiro sobre um APK e valida o resultado.

Uso:
    python3 tools/rea/executar_tudo.py <alvo.apk> <dir_saida>

Requisitos: `pip install androguard` (a mesma versao usada no relatorio esta em
requirements-test.txt) e `openssl` no PATH (opcional, so para o certificado).

O script nao modifica o APK: tudo e aberto em modo leitura.
"""
import json
import os
import re
import subprocess
import sys
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))


def rodar(nome, *args):
    cmd = [sys.executable, os.path.join(AQUI, nome), *args]
    print(f"\n$ {' '.join(cmd[1:])}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit(f"{nome} falhou")
    return r.stdout


def checagens(apk, outdir):
    """Assercoes que o relatorio usa como evidencia; falham alto se o alvo mudar."""
    falhas = []
    recon = json.load(open(os.path.join(outdir, "recon.json")))
    integ = json.load(open(os.path.join(outdir, "integridade_apk.json")))
    comps = json.load(open(os.path.join(outdir, "componentes.json")))
    caps = json.load(open(os.path.join(outdir, "capacidades.json")))
    strings = json.load(open(os.path.join(outdir, "strings_interessantes.json")))

    z = zipfile.ZipFile(apk)
    classes = set()
    textos = set()
    for n in z.namelist():
        if re.fullmatch(r"classes\d*\.dex", n):
            from androguard.core.dex import DEX
            d = DEX(z.read(n))
            classes |= set(d.get_classes_names())
            textos |= {s for s in d.get_strings() if isinstance(s, str)}

    def exigir(cond, msg):
        if not cond:
            falhas.append(msg)

    exigir(recon["hashes"]["sha256"] == hashlib_sha256(apk),
          "sha256 do recon nao corresponde ao arquivo")
    exigir(integ["sig_block"].get("presente"), "bloco de assinatura v2 ausente")
    exigir(integ["sig_block"].get("consistente"), "tamanho do bloco v2 inconsistente")
    exigir(not integ["cobertura_v1"]["nao_cobertas"],
          f"entradas sem cobertura v1: {integ['cobertura_v1']['nao_cobertas']}")
    exigir(all(integ["cobertura_v1"]["cobre_dex"].values()), "algum DEX fora do CERT.SF")

    exportados = [c for c in comps
                  if str(c["exported_effective"]).lower() in ("true", "implicit-true (intent-filter)")]
    exigir(len(exportados) == 11, f"esperados 11 componentes exportados, achados {len(exportados)}")

    nomes = {c["name"] for c in comps}
    for esperado in ("cm.aptoide.pt.toolbox.ToolboxContentProvider",
                     "cm.aptoide.pt.DeepLinkIntentReceiver"):
        exigir(esperado in nomes, f"componente {esperado} ausente")

    cats = {r["categoria"] for r in caps}
    exigir("controle_dispositivo" not in cats,
          "o alvo declara capacidades de DevicePolicy/DPD (nao e o esperado para este APK)")
    for sonda in ("AccessibilityService", "UsageStats", "DevicePolicyManager", "familylink"):
        exigir(not any(sonda.lower() in c.lower() for c in classes),
              f"classe contendo {sonda!r} encontrada — alvo diferente do documentado")

    # CA de interceptacao embutida
    nsc = z.read("res/4u.xml")
    exigir(b"trust-anchors" in nsc, "network_security_config sem trust-anchors")
    cert = z.read("res/HY.pem")
    texto_cert = ""
    try:
        texto_cert = subprocess.run(["openssl", "x509", "-noout", "-subject", "-issuer"],
                                    input=cert, capture_output=True, check=True).stdout.decode()
    except (FileNotFoundError, subprocess.CalledProcessError):
        texto_cert = cert.decode("utf-8", "replace")  # sem openssl: ao menos o PEM
    exigir("Charles Proxy" in texto_cert,
          "CA esperada (Charles Proxy) nao e a ancora @7F100001 em res/HY.pem")

    # root install
    exigir(any("root/execution/Shell" in c for c in classes), "subsistema RootShell ausente")
    exigir(any("pm install-write" in s for s in textos), "comando pm install-write ausente")

    # http claro
    exigir(any(u.startswith("http://") for u in strings["urls"]),
          "nenhuma URL http:// clara encontrada (esperado ao menos 1)")

    if falhas:
        print("\nFALHAS:")
        for f in falhas:
            print("  -", f)
        raise SystemExit(1)
    print("\nOK: todas as checagens do relatorio passaram.")


def hashlib_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    apk, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    rodar("recon.py", apk, outdir)
    rodar("integridade_apk.py", apk, outdir)
    rodar("static_scan.py", apk, outdir)
    smali = os.path.join(outdir, "smali")
    os.makedirs(smali, exist_ok=True)
    for rx, nome in (("toolbox/(ToolboxContentProvider|ToolboxSecurityManager);", "toolbox"),
                     ("install/(installer/Root|installer/RootInstaller|"
                      "installer/RootCommandOnSubscribe|CheckRootOnBoot);", "root"),
                     ("DeepLinkIntentReceiver;|InstalledBroadcastReceiver;|SearchWidgetProvider;|"
                      "YoutubeWebViewPlayer;", "deeplink_receivers_webview")):
        saida = rodar("dump_metodos.py", apk, rx)
        with open(os.path.join(smali, nome + ".txt"), "w") as fh:
            fh.write(saida)
    checagens(apk, outdir)


if __name__ == "__main__":
    main()
