#!/usr/bin/env python3
"""Fase 1 (R.E.A.) - Recon do APK: identidade, hashes, manifest, componentes, permissoes.

Uso: python3 recon.py <alvo.apk> <dir_saida>
Nao requer rede. Usa androguard (pip install androguard).
"""
import hashlib
import json
import os
import sys
import zipfile

from androguard.core.apk import APK

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def hashes(path):
    h = {"sha256": hashlib.sha256(), "sha1": hashlib.sha1(), "md5": hashlib.md5()}
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            size += len(chunk)
            for v in h.values():
                v.update(chunk)
    return {"size_bytes": size, **{k: v.hexdigest() for k, v in h.items()}}


def cert_info(apk):
    out = []
    for c in apk.get_certificates() or []:
        out.append({
            "subject": c.subject.human_friendly,
            "issuer": c.issuer.human_friendly,
            "serial": str(c.serial_number),
            "not_before": str(c.not_valid_before),
            "not_after": str(c.not_valid_after),
            "signature_algo": c.signature_algo,
            "sha256": c.sha256_fingerprint if not callable(getattr(c, "sha256_fingerprint", None))
                      else c.sha256_fingerprint("sha256").replace(":", ""),
        })
    return out


def comp_table(apk):
    """Componentes com atributos de exposicao e filtros de intent."""
    from lxml import etree
    root = etree.fromstring(apk.get_android_manifest_axml().get_xml())
    app = root.find("application")
    rows = []
    for tag, kind in (("activity", "activity"), ("activity-alias", "activity-alias"),
                      ("service", "service"), ("receiver", "receiver"),
                      ("provider", "provider")):
        for el in app.findall(tag):
            filters = []
            for fi in el.findall("intent-filter"):
                act = [a.get(ANDROID_NS + "name") for a in fi.findall("action")]
                cat = [c.get(ANDROID_NS + "name") for c in fi.findall("category")]
                dat = [dict(d.attrib) for d in fi.findall("data")]
                prio = fi.get(ANDROID_NS + "priority")
                filters.append({"actions": act, "categories": cat, "data": dat, "priority": prio})
            rows.append({
                "kind": kind,
                "name": el.get(ANDROID_NS + "name"),
                "exported": el.get(ANDROID_NS + "exported"),
                "permission": el.get(ANDROID_NS + "permission"),
                "read_permission": el.get(ANDROID_NS + "readPermission"),
                "write_permission": el.get(ANDROID_NS + "writePermission"),
                "authorities": el.get(ANDROID_NS + "authorities"),
                "grant_uri_permissions": el.get(ANDROID_NS + "grantUriPermissions"),
                "process": el.get(ANDROID_NS + "process"),
                "enabled": el.get(ANDROID_NS + "enabled"),
                "direct_boot_aware": el.get(ANDROID_NS + "directBootAware"),
                "intent_filters": filters,
            })
    # exported efetivo (regra: com intent-filter => default true em targetSdk < 31 para
    # activity/service/receiver; provider default false ate API 16)
    for r in rows:
        if r["exported"] is None and r["intent_filters"]:
            r["exported_effective"] = "implicit-true (intent-filter)"
        elif r["exported"] is None:
            r["exported_effective"] = "implicit-false"
        else:
            r["exported_effective"] = r["exported"]
    return rows


def manifest_flags(apk):
    from lxml import etree
    root = etree.fromstring(apk.get_android_manifest_axml().get_xml())
    app = root.find("application")
    keys = ["debuggable", "allowBackup", "fullBackupContent", "dataExtractionRules",
            "usesCleartextTraffic", "networkSecurityConfig", "requestLegacyExternalStorage",
            "testOnly", "extractNativeLibs", "largeHeap", "vmSafeMode", "hasCode",
            "backupAgent", "killAfterRestore", "restoreAnyVersion"]
    out = {k: app.get(ANDROID_NS + k) for k in keys}
    for k in ("versionCode", "versionName", "compileSdkVersion", "compileSdkVersionCodename",
              "platformBuildVersionCode", "platformBuildVersionName", "sharedUserId",
              "protectionLevel"):
        out["root_" + k] = root.get(ANDROID_NS + k)
    out["uses_sdk"] = {k: root.find("uses-sdk").get(ANDROID_NS + k) if root.find("uses-sdk") is not None else None
                       for k in ("minSdkVersion", "targetSdkVersion", "maxSdkVersion")}
    out["queries"] = [p.get(ANDROID_NS + "name") for t in ("package", "provider", "intent")
                      for p in (root.find("queries").findall(t) if root.find("queries") is not None else [])]
    return out


def declared_permissions(apk):
    from lxml import etree
    root = etree.fromstring(apk.get_android_manifest_axml().get_xml())
    out = []
    for p in root.findall("permission"):
        out.append({
            "name": p.get(ANDROID_NS + "name"),
            "protectionLevel": p.get(ANDROID_NS + "protectionLevel"),
            "permissionGroup": p.get(ANDROID_NS + "permissionGroup"),
        })
    for p in root.findall("permission-tree"):
        out.append({"name": p.get(ANDROID_NS + "name"), "protectionLevel": "TREE"})
    return out


def main():
    apk_path, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    apk = APK(apk_path)
    info = {
        "arquivo": os.path.basename(apk_path),
        "hashes": hashes(apk_path),
        "package": apk.get_package(),
        "app_name": apk.get_app_name(),
        "version_name": apk.get_androidversion_name(),
        "version_code": apk.get_androidversion_code(),
        "min_sdk": apk.get_min_sdk_version(),
        "target_sdk": apk.get_target_sdk_version(),
        "main_activity": apk.get_main_activity(),
        "is_signed_v1v2": apk.is_signed(),
        "certificates": cert_info(apk),
        "manifest_flags": manifest_flags(apk),
        "declared_permissions": declared_permissions(apk),
        "uses_permissions": sorted(set(apk.get_permissions())),
        "has_dex": apk.get_dex() is not None,
        "apk_entries": len(zipfile.ZipFile(apk_path).namelist()),
    }
    comps = comp_table(apk)
    with open(os.path.join(outdir, "recon.json"), "w") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(outdir, "componentes.json"), "w") as fh:
        json.dump(comps, fh, indent=2, ensure_ascii=False)
    xml = apk.get_android_manifest_axml().get_xml()
    with open(os.path.join(outdir, "AndroidManifest.xml"), "wb") as fh:
        fh.write(xml)
    print(json.dumps({k: info[k] for k in ("package", "app_name", "version_name",
                                           "version_code", "min_sdk", "target_sdk")}, indent=2))
    print("componentes:", len(comps), "| permissoes usadas:", len(info["uses_permissions"]))


if __name__ == "__main__":
    main()
