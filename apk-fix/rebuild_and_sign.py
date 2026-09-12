#!/usr/bin/env python3
"""Reconstrói o APK com o classes.dex corrigido e assina (v1 + v2).

Formato APK Signature Scheme v2 seguido exatamente conforme o apksig
(AOSP, referência: LineageOS/android_tools_apksig / V2SchemeSigner.java):
  - tudo LITTLE-ENDIAN (u32/u64)
  - digest de conteúdo = SHA-256 chunked de 1 MiB:
      por chunk:  H(0xa5 || u32le(len(chunk)) || chunk)
      final:      H(0x5a || u32le(n_chunks) || chunk_digests...)
    sobre 3 segmentos: beforeCentralDir, centralDir, eocd
  - signedData = seq( [digests][certificates][additionalAttributes][vazio] )
  - digests/signatures = seq de (u32(8+len) | u32 id | u32 len | bytes)
  - assinatura = RSA-PKCS1v15-SHA256 sobre o signedData completo

Uso:
    python3 rebuild_and_sign.py GGUF-Chat.apk /tmp/classes-fixed.dex GGUF-Chat-fixed.apk
"""
import os
import sys
import struct
import hashlib
import zipfile
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_P12 = os.path.join(HERE, "key.p12")
CERT_PEM = os.path.join(HERE, "cert.pem")
KEY_PEM = os.path.join(HERE, "key.pem")
KS_PASS = "ggufchat"
KS_ALIAS = "android"

ID_V2 = 0x7109871A
SIG_ALGO_RSA_PKCS1_SHA256 = 0x0103
CHUNK = 1048576


def u32(n):
    return struct.pack("<I", n)


def u64(n):
    return struct.pack("<Q", n)


def ensure_key():
    if os.path.exists(KEY_P12) and os.path.exists(KEY_PEM):
        return
    subprocess.run([
        "keytool", "-genkeypair", "-keystore", KEY_P12, "-storetype", "PKCS12",
        "-alias", KS_ALIAS, "-keyalg", "RSA", "-keysize", "2048",
        "-validity", "36500", "-dname", "CN=GGUF-Chat Fix, O=arena",
        "-storepass", KS_PASS, "-keypass", KS_PASS,
    ], check=True, capture_output=True)
    key, cert, _ = pkcs12.load_key_and_certificates(
        open(KEY_P12, "rb").read(), KS_PASS.encode())
    with open(KEY_PEM, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    with open(CERT_PEM, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("[key] chave + certificado gerados (keytool/PKCS12)")


def rebuild_apk(orig_apk, patched_dex, out_apk):
    with zipfile.ZipFile(orig_apk) as zin, zipfile.ZipFile(out_apk, "w") as zout:
        for item in zin.infolist():
            fn = item.filename
            if fn == "classes.dex":
                continue
            if fn.startswith("META-INF/") and (
                fn.endswith(".SF") or fn.endswith(".RSA")
                or fn.endswith(".DSA") or fn.endswith(".EC")
                or fn == "META-INF/MANIFEST.MF"):
                continue
            zout.writestr(item, zin.read(fn))
        zout.writestr("classes.dex", open(patched_dex, "rb").read())
    print("[rebuild] zip reconstruído:", out_apk)


def jarsigner_v1(apk):
    subprocess.run([
        "jarsigner", "-keystore", KEY_P12, "-storetype", "PKCS12",
        "-storepass", KS_PASS, "-keypass", KS_PASS,
        "-sigalg", "SHA256withRSA", "-digestalg", "SHA-256",
        apk, KS_ALIAS,
    ], check=True, capture_output=True)
    print("[v1] assinatura JAR aplicada")


def chunked_sha256(segments):
    chunk_digests = []
    for seg in segments:
        for i in range(0, len(seg), CHUNK):
            ch = seg[i:i + CHUNK]
            d = hashlib.sha256(b"\xa5" + u32(len(ch)) + ch).digest()
            chunk_digests.append(d)
    return hashlib.sha256(b"\x5a" + u32(len(chunk_digests)) + b"".join(chunk_digests)).digest()


def encode_sequence(elements):
    out = b""
    for e in elements:
        out += u32(len(e)) + e
    return out


def encode_pairs(pairs):
    out = b""
    for algo, data in pairs:
        out += u32(8 + len(data)) + u32(algo) + u32(len(data)) + data
    return out


def zip_layout(apk_bytes):
    eocd_pos = apk_bytes.rfind(b"PK\x05\x06")
    cd_offset = struct.unpack("<I", apk_bytes[eocd_pos + 16:eocd_pos + 20])[0]
    return cd_offset, eocd_pos


def v2_sign(apk_path):
    with open(apk_path, "rb") as f:
        data = bytearray(f.read())
    key = serialization.load_pem_private_key(open(KEY_PEM, "rb").read(), None)
    cert = x509.load_pem_x509_certificate(open(CERT_PEM, "rb").read())
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    pub_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    cd_offset, eocd_pos = zip_layout(bytes(data))

    # --- tamanho do bloco (determinístico: digest 32, assinatura RSA-2048 = 256) ---
    dummy_digest = b"\x00" * 32
    dummy_sig = b"\x00" * 256
    dummy_block = make_signing_block(dummy_digest, dummy_sig, cert_der, pub_der)
    block_size = len(dummy_block)

    # atualiza o offset da central directory no EOCD
    data[eocd_pos + 16:eocd_pos + 20] = struct.pack("<I", cd_offset + block_size)

    # digest real sobre 3 segmentos (sem o bloco)
    segments = [bytes(data[:cd_offset]), bytes(data[cd_offset:eocd_pos]), bytes(data[eocd_pos:])]
    content_digest = chunked_sha256(segments)

    # assinatura real
    signed_data = make_signed_data(content_digest, cert_der)
    signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())

    block = make_signing_block(content_digest, signature, cert_der, pub_der)
    assert len(block) == block_size, "tamanho do bloco mudou!"

    full = bytes(data[:cd_offset]) + block + bytes(data[cd_offset:])
    with open(apk_path, "wb") as f:
        f.write(full)
    print("[v2] APK Signature Scheme v2 aplicado (bloco=%d bytes)" % block_size)
    return full


def make_signed_data(content_digest, cert_der):
    digests = encode_pairs([(SIG_ALGO_RSA_PKCS1_SHA256, content_digest)])
    certs = encode_sequence([cert_der])
    return encode_sequence([digests, certs, b"", b""])  # 4 seções (canônico)


def make_signing_block(content_digest, signature, cert_der, pub_der):
    signed_data = make_signed_data(content_digest, cert_der)
    signatures = encode_pairs([(SIG_ALGO_RSA_PKCS1_SHA256, signature)])
    signer = encode_sequence([signed_data, signatures, pub_der])
    # v2 block = seq(seq(signers))  (dupla aninhagem canônica do apksig)
    v2_block = encode_sequence([encode_sequence([signer])])
    pair = u64(4 + len(v2_block)) + u32(ID_V2) + v2_block
    return pair + u64(len(pair)) + b"APK Sig Block 42"


def verify_v2(apk_path):
    data = open(apk_path, "rb").read()
    eocd_pos = data.rfind(b"PK\x05\x06")
    cd_offset = struct.unpack("<I", data[eocd_pos + 16:eocd_pos + 20])[0]
    assert data[cd_offset - 16:cd_offset] == b"APK Sig Block 42", "magic ausente"
    block_size = struct.unpack("<Q", data[cd_offset - 24:cd_offset - 16])[0]
    pair = data[cd_offset - 24 - block_size: cd_offset - 24]
    # par único: [u64 len][u32 id][value]
    plen = struct.unpack("<Q", pair[0:8])[0]
    pid = struct.unpack("<I", pair[8:12])[0]
    assert pid == ID_V2, "id v2 ausente"
    v2 = pair[12:8 + plen]

    def read_seq(buf):
        ln = struct.unpack("<I", buf[0:4])[0]
        return buf[4:4 + ln], buf[4 + ln:]

    inner, _ = read_seq(v2)         # dupla aninhagem: v2 = seq(seq(signer))
    signer, _ = read_seq(inner)
    signed_data, rest = read_seq(signer)
    sigs, rest = read_seq(rest)
    pub, _ = read_seq(rest)

    # assinatura (par: [u32 total][u32 algo][u32 len][sig])
    salgo = struct.unpack("<I", sigs[4:8])[0]
    slen = struct.unpack("<I", sigs[8:12])[0]
    sig = sigs[12:12 + slen]
    assert salgo == SIG_ALGO_RSA_PKCS1_SHA256

    # cert dentro de signed_data
    ds, r2 = read_seq(signed_data)
    cs, _ = read_seq(r2)
    clen = struct.unpack("<I", cs[0:4])[0]
    cert_der = cs[4:4 + clen]
    cert = x509.load_der_x509_certificate(cert_der)
    cert.public_key().verify(sig, signed_data, padding.PKCS1v15(), hashes.SHA256())
    print("[verify] assinatura v2 VÁLIDA (algo=0x%x, RSA-%d bits, %s)"
          % (salgo, cert.public_key().key_size, cert.subject.rfc4514_string()[:40]))


def main():
    orig_apk, patched_dex, out_apk = sys.argv[1], sys.argv[2], sys.argv[3]
    ensure_key()
    rebuild_apk(orig_apk, patched_dex, out_apk)
    jarsigner_v1(out_apk)
    v2_sign(out_apk)
    verify_v2(out_apk)
    print("PRONTO:", out_apk)


if __name__ == "__main__":
    main()
