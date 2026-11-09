#!/usr/bin/env python3
"""Fase 1/2 (R.E.A.) - integridade de empacotamento do APK.

Verifica: cobertura do esquema de assinatura v2 (bloco "APK Sig Block 42"),
IDs de bloco presentes, certificado do assinante, cobertura do CERT.SF por
entrada, e diferencas entre o que o MANIFEST/CERT.SF declara e o que existe no
ZIP (indicador de repack).

Uso: python3 integridade_apk.py <alvo.apk> <dir_saida>
"""
import hashlib
import json
import os
import re
import struct
import sys
import zipfile

from androguard.core.apk import APK

BLOCK_NAMES = {
    0x1A: "v2 (APK Signature Scheme v2)",
    0x1B: "v3 (APK Signature Scheme v3)",
    0x1C: "v3.1 (rotation)",
    0x1D: "APK Signature Scheme v4/rotacao (idsig)",
    0x2B: "SourceStamp (v2)",
    0x31B: "desconhecido neste script (0x031b)",
}

RAW_TYPES = {"png", "webp", "jpg", "jpeg", "gif", "pem", "xml", "9.png"}


def sig_block(raw):
    """Localiza e decodifica o APK Signing Block (formato do AOSP apksig)."""
    marker = b"APK Sig Block 42"
    pos = raw.rfind(marker)
    if pos < 0:
        return {"presente": False}
    size = struct.unpack("<Q", raw[pos - 8:pos])[0]
    # layout: [uint64 size][pairs...][uint64 size][16-byte magic]
    start = pos + 16 - size - 8
    lead = struct.unpack("<Q", raw[start:start + 8])[0]
    pairs, p = [], start + 8
    while p < pos - 8:
        ln = struct.unpack("<Q", raw[p:p + 8])[0]
        pid = struct.unpack("<I", raw[p + 8:p + 12])[0]
        pairs.append({"id": hex(pid), "nome": BLOCK_NAMES.get(pid, "desconhecido"),
                      "tamanho": ln})
        p += 8 + ln
    return {"presente": True, "tamanho_bloco": size,
            "tamanho_declarado_inicio": lead, "consistente": lead == size,
            "inicio": start, "fim_central_directory_offset": pos + 16,
            "pares": pairs,
            "ids": [x["id"] for x in pairs]}


def cobertura_sf(z):
    """Compara entradas do ZIP com as entradas assinadas em META-INF/CERT.SF."""
    sf = z.read("META-INF/CERT.SF").decode("utf-8", "replace")
    # LINHAS DE CONTINUACAO: o MANIFEST quebra nomes longos em "\r\n " (RFC 822).
    continuado = re.sub(r"\r?\n ", "", sf)  # desfaz quebra de linha RFC 822
    assinadas = {x.strip() for x in re.findall(r"^Name: (.+)$", continuado, re.M)}
    no_zip = set(z.namelist()) - {"META-INF/CERT.SF", "META-INF/CERT.RSA", "META-INF/MANIFEST.MF"}
    cobertas = assinadas & no_zip
    return {
        "entradas_zip": len(no_zip),
        "entradas_assinadas": len(assinadas),
        "cobertas": len(cobertas),
        "nao_cobertas": sorted(no_zip - assinadas)[:20],
        "assinadas_ausentes_do_zip": sorted(assinadas - no_zip)[:5],
        "cobre_dex": {n: n in assinadas for n in ("classes.dex", "classes2.dex", "classes3.dex")},
    }


def entradas_sem_compressao_ou_estranhas(z):
    """Heuristica de repack: entradas com extensao 'raw' que nao sao recurso valido."""
    suspeitas = []
    for i in z.infolist():
        if i.filename.endswith("/"):
            continue
        ext = i.filename.rsplit(".", 1)[-1].lower()
        if ext in RAW_TYPES:
            continue
        base = i.filename.rsplit(".", 1)[0]
        if i.filename.startswith("res/") and "/" in base:
            suspeitas.append({"entrada": i.filename, "tamanho": i.file_size,
                              "comprimido": i.compress_size,
                              "metodo": "stored" if i.compress_type == 0 else "deflate"})
    return suspeitas


def main():
    apk_path, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    raw = open(apk_path, "rb").read()
    z = zipfile.ZipFile(apk_path)
    apk = APK(apk_path)
    certs = []
    for c in apk.get_certificates() or []:
        certs.append({
            "subject": c.subject.human_friendly,
            "issuer": c.issuer.human_friendly,
            "serial": str(c.serial_number),
            "not_before": str(c.not_valid_before),
            "not_after": str(c.not_valid_after),
            "sig_algo": c.signature_algo,
            "pubkey_algo": c.public_key.algorithm if hasattr(c, "public_key") else None,
            "sha256_der": hashlib.sha256(c.dump()).hexdigest() if hasattr(c, "dump") else None,
        })
    info = {
        "arquivo": os.path.basename(apk_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sha1": hashlib.sha1(raw).hexdigest(),
        "md5": hashlib.md5(raw).hexdigest(),
        "tamanho": len(raw),
        "eocd_offset": raw.rfind(b"PK\x05\x06"),
        "esquema_v1": z.read("META-INF/CERT.SF") is not None and "META-INF/CERT.RSA" in z.namelist(),
        "sig_block": sig_block(raw),
        "cobertura_v1": cobertura_sf(z),
        "certificados": certs,
        "entradas_estranhas": entradas_sem_compressao_ou_estranhas(z)[:30],
        "libs_nativas": sorted({n for n in z.namelist() if n.startswith("lib/")}),
        "recursos_nao_imagem": sorted(n for n in z.namelist()
                                     if n.startswith("res/") and n.rsplit(".", 1)[-1] not in
                                     ("png", "xml", "webp", "9")),
    }
    with open(os.path.join(outdir, "integridade_apk.json"), "w") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
    print(json.dumps({k: info[k] for k in ("sha256", "esquema_v1", "sig_block")},
                     indent=2, ensure_ascii=False)[:1500])
    print("certificados:", json.dumps(certs, indent=2, ensure_ascii=False))
    print("cobertura v1:", json.dumps(info["cobertura_v1"], indent=2, ensure_ascii=False))
    print("entradas estranhas:", info["entradas_estranhas"])
    print("recursos nao-imagem:", info["recursos_nao_imagem"])


if __name__ == "__main__":
    main()
