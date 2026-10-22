#!/usr/bin/env python3
"""Build the tiny test APK used by the emulator job.

The app does one thing: on launch it writes a Family Link shaped config
(shared secret + TTL) into its own SharedPreferences, and it declares
android:allowBackup="true" so `adb backup` can copy exactly that file. That is
what proves the no-root pipeline end to end on a real Android device.

Every step is a subprocess whose output is printed, so a failure is never
silent. The secret is fictitious.

    python tools/build_test_apk.py --out /tmp/selftest.apk
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

PACKAGE = "com.flcodes.selftest"
ACTIVITY = "Main"

JAVA = """
package com.flcodes.selftest;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;

/** Writes the Family Link shaped config into this app's private prefs. */
public class Main extends Activity {
    private static final String SECRET = "__SECRET__";
    private static final String CONFIG =
        "{\\"parentAccessCode\\":{\\"sharedSecret\\":\\"" + SECRET + "\\","
        + "\\"accessCodeTtl\\":600,\\"clockDriftTolerance\\":300}}";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        SharedPreferences prefs = getSharedPreferences("familylink_preferences", MODE_PRIVATE);
        prefs.edit().putString("family_link_app_config", CONFIG).commit();
        System.out.println("flcodes-selftest: wrote " + CONFIG.length() + " bytes");
        finish();
    }
}
"""

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="30" />
    <application
        android:label="flcodes selftest"
        android:allowBackup="true"
        android:fullBackupContent="true">
        <activity android:name=".{activity}" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

STRINGS = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">flcodes selftest</string>
</resources>
"""


def run(command, step, **kwargs):
    print(f"\n$ {' '.join(str(part) for part in command)}")
    completed = subprocess.run(
        [str(part) for part in command], capture_output=True, text=True, **kwargs
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if output.strip():
        print(output.strip()[:4000])
    if completed.returncode != 0:
        print(f"FAILED at step {step!r} (exit {completed.returncode})", file=sys.stderr)
        raise SystemExit(completed.returncode or 1)
    return completed


def newest(directory: Path, pattern: str) -> Path:
    candidates = sorted(
        directory.glob(pattern),
        key=lambda path: [int(part) if part.isdigit() else part for part in path.name.replace("-", ".").split(".")],
    )
    return candidates[-1] if candidates else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="selftest.apk")
    parser.add_argument("--secret", default="AItest-only-emulator-key")
    parser.add_argument("--sdk", default=os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or "/usr/local/lib/android/sdk")
    args = parser.parse_args(argv)

    sdk = Path(args.sdk)
    print(f"SDK: {sdk}")
    if not sdk.is_dir():
        print(f"no Android SDK at {sdk}", file=sys.stderr)
        return 2
    build_tools = newest(sdk / "build-tools", "*")
    # prefer a stable platform (android-30 .. android-35) over betas/previews
    stable = [path for path in sorted((sdk / "platforms").glob("android-*"))
              if path.name.count("-") == 1 and path.name.split("-")[1].isdigit()]
    platforms = stable or sorted((sdk / "platforms").glob("android-*"))
    if not build_tools or not platforms:
        print(f"SDK at {sdk} has no build-tools or platforms", file=sys.stderr)
        return 2
    platform = platforms[-1]
    android_jar = platform / "android.jar"
    print(f"build-tools: {build_tools.name}   platform: {platform.name}")

    work = Path(tempfile.mkdtemp(prefix="flcodes-apk-"))
    try:
        src = work / "src" / "com" / "flcodes" / "selftest"
        src.mkdir(parents=True)
        classes = work / "classes"
        dex = work / "dex"
        classes.mkdir()
        dex.mkdir()
        (work / "AndroidManifest.xml").write_text(
            MANIFEST.format(package=PACKAGE, activity=ACTIVITY)
        )
        (src / "Main.java").write_text(JAVA.replace("__SECRET__", args.secret))

        run(["javac", "-source", "8", "-target", "8", "-nowarn",
             "-bootclasspath", android_jar, "-d", classes, src / "Main.java"], "javac")
        class_files = sorted(str(path) for path in classes.rglob("*.class"))
        print(f"compiled: {[Path(name).name for name in class_files]}")
        run([build_tools / "d8", "--lib", android_jar, "--min-api", "21",
             "--output", dex] + class_files, "d8")

        apk = work / "base.apk"
        if (build_tools / "aapt2").exists():
            # the label is a literal in the manifest, so no resources are needed
            run([build_tools / "aapt2", "link", "-o", apk, "-I", android_jar,
                 "--manifest", work / "AndroidManifest.xml",
                 "--min-sdk-version", "21", "--target-sdk-version", "30"], "aapt2 link")
        else:
            run([build_tools / "aapt", "package", "-f", "-M", work / "AndroidManifest.xml",
                 "-I", android_jar, "-F", apk], "aapt package")

        print("\n$ zip classes.dex")
        with zipfile.ZipFile(apk, "a") as archive:
            archive.write(dex / "classes.dex", "classes.dex")

        aligned = work / "aligned.apk"
        run([build_tools / "zipalign", "-f", "4", apk, aligned], "zipalign")

        keystore = work / "debug.keystore"
        run(["keytool", "-genkeypair", "-keystore", keystore, "-alias", "androiddebugkey",
             "-storepass", "android", "-keypass", "android", "-keyalg", "RSA",
             "-keysize", "2048", "-validity", "10000",
             "-dname", "CN=flcodes selftest, O=experiment, C=BR"], "keytool")

        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        run([build_tools / "apksigner", "sign", "--ks", keystore,
             "--ks-pass", "pass:android", "--key-pass", "pass:android",
             "--out", output, aligned], "apksigner")
        run([build_tools / "apksigner", "verify", output], "apksigner verify")
        run([build_tools / "aapt2", "dump", "packagename", output], "package name")
        print(f"\nbuilt {output} ({output.stat().st_size} bytes)")
        print(f"package={PACKAGE}  secret={args.secret}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
