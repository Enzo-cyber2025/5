#!/usr/bin/env python3
"""Repair GGUF Chat 2.0, preserving resources and native inference code; sign with apksigner.

No Android SDK is needed when the pinned APKTOOL_JAR/APKSIGNER_JAR are provided.
The DEX and the JNI bridge ELF dependency metadata are repaired. No handwritten APK signature implementation is used.
"""
import argparse
import copy
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

from patch_dex import patch_bytes
from patch_native import patch_archive_jni, JNI_ENTRIES
from patch_smali import apply as apply_smali

HERE = Path(__file__).resolve().parent
ORIGINAL_APK_SHA256 = "02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281"
TOOLS = {
    "APKTOOL_JAR": "7956eb04194300ce0d0a84ad18771eebc94b89fb8d1ddcce8ea4c056818646f4",
    "APKSIGNER_JAR": "eefdd6aed9db9fb849e4c98a50d8741e19d1b674ba6547220bcb9c3ed152123a",
}


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def signature_entry(name):
    name = name.upper()
    return name.startswith("META-INF/") and (
        name.endswith((".SF", ".RSA", ".DSA", ".EC")) or name == "META-INF/MANIFEST.MF"
    )


def rebuild_zip(original, dex, output, native_replacements=None):
    """Copy original entries, strip obsolete signatures, align STORED data to 4 bytes.

    Native libraries retain their original compression (extractNativeLibs=true
    by default in this pinned APK). Resources are copied verbatim. ZIP padding
    is not signing; apksigner below is the sole signature implementation.
    """
    native_replacements = native_replacements or {}
    if not set(native_replacements) <= JNI_ENTRIES:
        raise ValueError("Only JNI bridge dependencies may be repaired")
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(output, "w") as dst:
        for entry in src.infolist():
            if signature_entry(entry.filename):
                continue
            info = copy.copy(entry)
            # Drop old ZIP padding; appending after zipalign's trailing zero bytes
            # would turn those bytes into a malformed extra-field header.
            info.extra = b""
            data = dex if info.filename == "classes.dex" else native_replacements.get(entry.filename, src.read(entry.filename))
            if info.compress_type == zipfile.ZIP_STORED:
                # All names in this pinned APK are ASCII. Fail rather than guess encoding.
                name_size = len(info.filename.encode("ascii"))
                offset = dst.fp.tell() + 30 + name_size + len(info.extra)
                if offset % 4:
                    padding = (-offset) % 4
                    info.extra += struct.pack("<HH", 0xD935, padding) + bytes(padding)
            dst.writestr(info, data)
    verify_alignment(output)


def verify_alignment(path):
    with zipfile.ZipFile(path) as archive, open(path, "rb") as stream:
        for info in archive.infolist():
            if info.compress_type != zipfile.ZIP_STORED:
                continue
            stream.seek(info.header_offset + 26)
            name_size, extra_size = struct.unpack("<HH", stream.read(4))
            offset = info.header_offset + 30 + name_size + extra_size
            if offset % 4:
                raise ValueError(f"Entrada ZIP desalinhada: {info.filename}")


def verify_payload(original, repaired, native_replacements=None):
    native_replacements = native_replacements or {}
    if not set(native_replacements) <= JNI_ENTRIES:
        raise ValueError("Unexpected native replacement")
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(repaired) as b:
        expected = {n for n in a.namelist() if not signature_entry(n)}
        actual = {n for n in b.namelist() if not signature_entry(n)}
        if expected != actual:
            raise ValueError("O conjunto de arquivos do APK mudou inesperadamente.")
        for name in expected - {"classes.dex"}:
            if native_replacements.get(name, a.read(name)) != b.read(name):
                raise ValueError(f"Recurso/biblioteca alterado inesperadamente: {name}")


def tool(name):
    path = Path(os.environ[name]).resolve()
    if sha256(path) != TOOLS[name]:
        raise ValueError(f"{name}: hash diferente da versão fixada. Veja scripts/fetch_tools.sh.")
    return str(path)


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--alias", default="gguf-repair")
    args = parser.parse_args()
    original, output = args.original.resolve(), args.output.resolve()
    if original == output:
        parser.error("A saída não pode sobrescrever o original.")
    if sha256(original) != ORIGINAL_APK_SHA256:
        parser.error("APK de origem desconhecido. Use o original fixado no README.")
    apktool, apksigner = tool("APKTOOL_JAR"), tool("APKSIGNER_JAR")
    java_home = Path(os.environ.get("JAVA_HOME", "/usr"))
    java = java_home / "bin/java"
    keytool = java_home / "bin/keytool"
    if not os.environ.get("GGUF_KEYSTORE_PASSWORD"):
        parser.error("Defina GGUF_KEYSTORE_PASSWORD no ambiente (não na linha de comando).")
    keystore = args.keystore.resolve()
    if not keystore.exists():
        keystore.parent.mkdir(parents=True, exist_ok=True)
        # Private keys are local artifacts, not repository contents.
        old_umask = os.umask(0o077)
        try:
            run(keytool, "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12",
                "-alias", args.alias, "-keyalg", "RSA", "-keysize", "3072", "-validity", "3650",
                "-dname", "CN=GGUF Chat local repair", "-storepass:env", "GGUF_KEYSTORE_PASSWORD")
        finally:
            os.umask(old_umask)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gguf-repair-") as tmp:
        work = Path(tmp)
        with zipfile.ZipFile(original) as archive:
            dex = patch_bytes(archive.read("classes.dex"))
            native_replacements = patch_archive_jni(archive, work)
        intermediate = work / "patched.apk"
        rebuild_zip(original, dex, intermediate)
        decoded = work / "decoded"
        run(java, "-jar", apktool, "d", "-f", "-r", "-o", decoded, intermediate)
        apply_smali(decoded)
        compiled = work / "compiled.apk"
        run(java, "-jar", apktool, "b", decoded, "-o", compiled)
        with zipfile.ZipFile(compiled) as archive:
            dex = archive.read("classes.dex")
        unsigned, signed = work / "unsigned.apk", work / "signed.apk"
        rebuild_zip(original, dex, unsigned, native_replacements)
        run(java, "-jar", apksigner, "sign", "--ks", keystore, "--ks-key-alias", args.alias,
            "--ks-pass", "env:GGUF_KEYSTORE_PASSWORD", "--v1-signing-enabled", "true",
            "--v2-signing-enabled", "true", "--v4-signing-enabled", "false", "--out", signed, unsigned)
        run(java, "-jar", apksigner, "verify", "--verbose", "--print-certs", signed)
        verify_alignment(signed)
        verify_payload(original, signed, native_replacements)
        shutil.copyfile(signed, output)
    output.with_suffix(".apk.sha256").write_text(f"{sha256(output)}  {output.name}\n")
    print(f"APK reconstruído e assinatura verificada: {output}\n"
          "Isso NÃO equivale a um teste funcional no Android. Veja docs/VALIDACAO.md.")


if __name__ == "__main__":
    main()
