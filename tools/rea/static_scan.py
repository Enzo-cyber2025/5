#!/usr/bin/env python3
"""Fase 2 (R.E.A.) - varredura estatica: capacidades sensiveis, anti-tamper,
superficie de ataque exposta e mapa de chamadas.

Uso: python3 static_scan.py <alvo.apk> <dir_saida>
Gera: capacidades.json, strings_interessantes.json, mapa_chamadas.json
"""
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

from androguard.core.dex import DEX

# (categoria, descricao, regex testada em "classe->metodo" e no texto da instrucao)
SINKS = [
    # --- deteccao de processos / uso de apps ---
    ("deteccao_processos", "ActivityManager.getRunningAppProcesses",
     r"Landroid/app/ActivityManager;->getRunningAppProcesses"),
    ("deteccao_processos", "ActivityManager.getRunningTasks",
     r"Landroid/app/ActivityManager;->getRunningTasks"),
    ("deteccao_processos", "ActivityManager.getRunningServices",
     r"Landroid/app/ActivityManager;->getRunningServices"),
    ("deteccao_processos", "ActivityManager.RunningAppProcessInfo (leitura de campos)",
     r"Landroid/app/ActivityManager\$RunningAppProcessInfo;"),
    ("deteccao_processos", "UsageStatsManager.queryUsageStats",
     r"Landroid/app/usage/UsageStatsManager;->queryUsageStats"),
    ("deteccao_processos", "UsageStatsManager.queryEvents",
     r"Landroid/app/usage/UsageStatsManager;->queryEvents"),
    ("deteccao_processos", "UsageStatsManager.queryEventStats",
     r"Landroid/app/usage/UsageStatsManager;->queryEventStats"),
    ("deteccao_processos", "UsageStatsManager.queryAndAggregateUsageStats",
     r"Landroid/app/usage/UsageStatsManager;->queryAndAggregateUsageStats"),
    ("deteccao_processos", "AppOpsManager (checagem de op)",
     r"Landroid/app/AppOpsManager;->(checkOp|noteOp|startWatchingMode|unsafeCheckOp)"),
    ("deteccao_processos", "PackageManager.getInstalledPackages/Applications",
     r"Landroid/content/pm/PackageManager;->(getInstalledPackages|getInstalledApplications|getPackagesForUid)"),
    ("deteccao_processos", "ActivityManager.getRunningAppProcesses (via contexto)",
     r"getSystemService\(.*\)|Landroid/app/ActivityManager;"),
    ("deteccao_processos", "Process.myPid / leitura de /proc",
     r"Landroid/os/Process;->myPid|/proc/|ProcessBuilder|Ljava/lang/Runtime;->exec"),
    ("deteccao_processos", "ActivityLifecycleCallbacks (foreground/background)",
     r"registerActivityLifecycleCallbacks|ComponentCallbacks2;->onTrimMemory"),
    ("deteccao_processos", "JobScheduler / WorkManager (polling periodico)",
     r"Landroid/app/job/JobScheduler;->(schedule|enqueue)|Landroidx/work/"),
    ("deteccao_processos", "AlarmManager (wakeup periodico)",
     r"Landroid/app/AlarmManager;->set"),
    ("deteccao_processos", "AccessibilityEvent / janela ativa",
     r"Landroid/view/accessibility/AccessibilityEvent;|getRootInActiveWindow|getWindows\(\)|onAccessibilityEvent"),
    ("deteccao_processos", "Uso de overlay (SYSTEM_ALERT_WINDOW / TYPE_APPLICATION_OVERLAY)",
     r"TYPE_APPLICATION_OVERLAY|TYPE_PHONE|TYPE_SYSTEM_ALERT|canDrawOverlays|ACTION_MANAGE_OVERLAY_PERMISSION"),
    # --- controle do dispositivo (device admin / DPC) ---
    ("controle_dispositivo", "DevicePolicyManager.lockNow",
     r"Landroid/app/admin/DevicePolicyManager;->lockNow"),
    ("controle_dispositivo", "DevicePolicyManager.setPackagesSuspended",
     r"Landroid/app/admin/DevicePolicyManager;->(setPackagesSuspended|isPackageSuspended)"),
    ("controle_dispositivo", "DevicePolicyManager.setApplicationHidden",
     r"Landroid/app/admin/DevicePolicyManager;->(setApplicationHidden|isApplicationHidden)"),
    ("controle_dispositivo", "DevicePolicyManager.setApplicationEnabledSetting / permissao",
     r"Landroid/app/admin/DevicePolicyManager;->(setApplicationEnabledSetting|setPermissionGrantState|setPackagesSuspended)"),
    ("controle_dispositivo", "DevicePolicyManager wipeData/resetPassword",
     r"Landroid/app/admin/DevicePolicyManager;->(wipeData|resetPassword|wipeDataWithReason)"),
    ("controle_dispositivo", "DevicePolicyManager user restrictions",
     r"Landroid/app/admin/DevicePolicyManager;->(addUserRestriction|clearUserRestriction|setUserRestriction)"),
    ("controle_dispositivo", "DevicePolicyManager.setScreenCaptureDisabled",
     r"Landroid/app/admin/DevicePolicyManager;->(setScreenCaptureDisabled|setStatusBarDisabled|setKeyguardDisabled)"),
    ("controle_dispositivo", "DeviceAdminReceiver",
     r"Landroid/app/admin/DeviceAdminReceiver"),
    ("controle_dispositivo", "getAdminActive / isAdminActive",
     r"Landroid/app/admin/DevicePolicyManager;->isAdminActive"),
    ("controle_dispositivo", "VPN (VpnService / prepare)",
     r"Landroid/net/VpnService|VpnService\$Builder;->establish"),
    # --- integridade / anti-tamper ---
    ("integridade", "assinatura do pacote (GET_SIGNATURES / GET_SIGNING_CERTIFICATES)",
     r"Landroid/content/pm/PackageManager;->(getPackageInfo|checkSignatures|getPackageArchiveInfo)"),
    ("integridade", "PackageInfo.signatures / signingInfo",
     r"Landroid/content/pm/(PackageInfo|SigningInfo);->(signatures|apkContentsSigners)"),
    ("integridade", "Signature.toByteArray/hashCode (pin de certificado)",
     r"Landroid/content/pm/Signature;->(toByteArray|hashCode|toCharsString)"),
    ("integridade", "Play Integrity / SafetyNet attestation",
     r"Lcom/google/android/gms/(safetynet|integrity)/|IntegrityTokenRequest|SafetyNetApi|IntegrityManager"),
    ("integridade", "uso/checagem de root (su, magisk, Superuser)",
     r'"su"|"su -c|"su -v|/system/xbin/su|magisk|Superuser\.apk|Lcm/aptoide/pt/root/|RootAvailability'),
    ("integridade", "deteccao de depurador / hook (frida, xposed, ptrace)",
     r"isDebuggerConnected|waitingForDebugger|frida|xposed|Xposed|ptrace|TracerPid"),
    ("integridade", "Build.TAGS / Build.TYPE (emulador, debug)",
     r"Landroid/os/Build;->(TAGS|TYPE|FINGERPRINT|MODEL|MANUFACTURER|PRODUCT|HARDWARE)|goldfish|ranchu"),
    ("integridade", "pinning / verificacao TLS do lado cliente",
     r"Lokhttp3/CertificatePinner;->|CertificatePinner\$Builder;->add|X509TrustManager|HostnameVerifier;->verify|NetworkSecurityPolicy;->isCleartextTrafficPermitted"),
    # --- superficie webview / IPC / crypto ---
    ("superficie", "WebView.addJavascriptInterface",
     r"Landroid/webkit/WebView;->addJavascriptInterface"),
    ("superficie", "WebView.setAllowFileAccess / universal access",
     r"setAllowFileAccess|setAllowUniversalAccessFromFileURLs|setAllowContentAccess|setJavaScriptEnabled"),
    ("superficie", "Intent implicito (setAction / new Intent com action)",
     r"Landroid/content/Intent;->(setAction|setComponent|setPackage)"),
    ("superficie", "startActivity/startService/sendBroadcast sem componente",
     r"Landroid/content/Context;->(startActivity|startService|sendBroadcast|bindService)"),
    ("superficie", "DexClassLoader / dalvik.system (carregamento dinamico)",
     r"DexClassLoader|PathClassLoader|InMemoryDexClassLoader|dalvik/system"),
    ("superficie", "Reflexao generica (Class.forName)", r"Ljava/lang/Class;->forName"),
    ("superficie", "Desserializacao Java (ObjectInputStream)",
     r"Ljava/io/ObjectInputStream;->readObject"),
    ("superficie", "Parcel / Bundle generico", r"Landroid/os/Parcel;->(readBundle|readValue|unmarshall)"),
    ("superficie", "ContentProvider openFile (path traversal)",
     r"Landroid/content/ContentProvider;->openFile|openAssetFile|openFileHelper"),
    ("superficie", "Crypto ECB / chave fixa",
     r"AES/ECB|/ECB/|PBKDF2|SecretKeySpec|IvParameterSpec"),
    ("superficie", "MODE_WORLD_READABLE/WRITABLE",
     r"MODE_WORLD_READABLE|MODE_WORLD_WRITEABLE|MODE_WORLD_READABLE"),
    ("superficie", "Log de dados sensiveis",
     r"Landroid/util/Log;->(d|v|i|w|e)"),
    ("superficie", "SharedPreferences sem protecao / external storage",
     r"getExternalFilesDir|getExternalStorageDirectory|MODE_MULTI_PROCESS"),
]

TRANSPORT_RX = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{4,120}")
INTEREST_RX = re.compile(
    r"(?i)(block|bloque|lock|suspend|supervis|parental|family|fam[ií]lia|kids|child|"
    r"screen_?time|bedtime|time_?limit|daily_?limit|dpc|device_?owner|kiosk|"
    r"pin|uninstall|bypass|integrity|tamper|hook|root)")


def iter_methods(dexes):
    for dx in dexes:
        for c in dx.get_classes():
            for m in c.get_methods():
                yield c, m


def scan(apk_path):
    z = zipfile.ZipFile(apk_path)
    dex_names = sorted(n for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n))
    dexes = [DEX(z.read(n)) for n in dex_names]
    compiled = [(cat, desc, re.compile(rx)) for cat, desc, rx in SINKS]

    findings = defaultdict(list)
    strings = defaultdict(set)
    for c, m in iter_methods(dexes):
        code = m.get_code()
        if not code:
            continue
        cn = c.get_name()
        callee_me = f"{cn}->{m.get_name()}{m.get_descriptor()}"
        for ins in code.get_bc().get_instructions():
            op = ins.get_name()
            text = ins.get_output()
            if op in ("const-string", "const-string/jumbo"):
                val = ins.get_raw_string() if hasattr(ins, "get_raw_string") else text
                if isinstance(val, bytes):
                    val = val.decode("utf-8", "replace")
                if not isinstance(val, str):
                    val = str(val)
                for u in TRANSPORT_RX.findall(val):
                    strings["urls"].add(u)
                if INTEREST_RX.search(val) and 3 < len(val) < 120:
                    strings["termos"].add(val)
                if val.startswith(("android.", "com.google.android.", "com.android.")) and "." in val:
                    strings["actions"].add(val)
                if val.startswith("/") and 2 < len(val) < 80:
                    strings["caminhos"].add(val)
                if val.startswith("su") or "magisk" in val.lower() or "frida" in val.lower():
                    strings["anti_tamper"].add(val)
            for cat, desc, rx in compiled:
                if rx.search(text) or rx.search(callee_me):
                    key = (cat, desc)
                    bucket = findings[key]
                    if len(bucket) < 60:
                        bucket.append({"classe": cn, "metodo": m.get_name() + m.get_descriptor(),
                                       "instrucao": text.strip()[:200]})
                    break

    out = []
    for (cat, desc), hits in findings.items():
        out.append({"categoria": cat, "capacidade": desc, "ocorrencias": len(hits),
                    "classes": sorted({h["classe"] for h in hits}),
                    "amostra": hits[:12]})
    out.sort(key=lambda r: (r["categoria"], -r["ocorrencias"]))

    return out, {k: sorted(v) for k, v in strings.items()}


def main():
    apk_path, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    caps, strs = scan(apk_path)
    json.dump(caps, open(os.path.join(outdir, "capacidades.json"), "w"), indent=2, ensure_ascii=False)
    json.dump(strs, open(os.path.join(outdir, "strings_interessantes.json"), "w"), indent=2, ensure_ascii=False)
    for r in caps:
        print(f"{r['categoria']:22s} {r['ocorrencias']:4d}  {r['capacidade']}")
    print("\nurls:", len(strs.get("urls", [])), "| termos:", len(strs.get("termos", [])),
          "| acoes:", len(strs.get("actions", [])))


if __name__ == "__main__":
    main()
