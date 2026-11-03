#!/usr/bin/env python3
"""Install and smoke-test pinned Box64 only inside an ARM64 Termux emulator."""
import json
import os
import subprocess
import time
import traceback
from pathlib import Path

EVIDENCE = Path("evidence/box64-arm64")
APK = Path(os.environ.get("BOX64_TERMUX_APK", ".cache/termux-app-arm64.apk"))
INSTALLER = Path("tests/box64-termux/install-box64-arm64.sh")
HOME = "/data/data/com.termux/files/home"
PREFIX = "/data/data/com.termux/files/usr"


def adb(*args, timeout=120, check=True):
    result = subprocess.run(["adb", *map(str, args)], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    output = result.stdout.strip()
    if check and result.returncode:
        raise RuntimeError(f"adb {args!r} exited {result.returncode}: {output[-6000:]}")
    return output


def wait_for(predicate, description, timeout=900):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            last = predicate() or ""
            if last:
                return last
        except Exception as exc:
            last = str(exc)
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {description}: {last[-2000:]}")


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = {"status": "FAIL", "scope": "pinned Box64 installation smoke test in ARM64 Termux",
              "official_termux_package": False,
              "box64_source": "third-party patched v0.4.5-termux.1 release; pinned SHA-256",
              "sha256": "0dae8257ac7396db4766721e5e4f317679b2080752d32e90d4e6e6fdfee467cf",
              "installer": str(INSTALLER), "app_mediated_model_handoff": False,
              "limitations": ["This separate architecture smoke test does not claim that Gemma installed Box64.",
                              "The release is a third-party Android ARM64 build, not an official Termux package."]}
    try:
        assert APK.is_file() and APK.stat().st_size > 100_000, f"Missing Termux APK: {APK}"
        assert INSTALLER.is_file()
        abi = adb("shell", "getprop", "ro.product.cpu.abi")
        report["android_abi"] = abi
        assert abi.startswith("arm64"), f"Expected ARM64 Android guest, got {abi!r}"
        adb("root", check=False)
        adb("wait-for-device", timeout=120)
        assert adb("shell", "id", "-u") == "0", "Emulator adb root unavailable for test fixture setup"
        adb("shell", "wm", "size", "720x1280", check=False)
        adb("shell", "wm", "density", "240", check=False)
        adb("install", "-r", APK, timeout=180)
        adb("shell", "monkey", "-p", "com.termux", "1", check=False)
        wait_for(lambda: (ready if (ready := adb("shell", "sh", "-c",
                 f"test -x {PREFIX}/bin/bash && echo ready", check=False)) == "ready" else ""),
                 "Termux first-run bootstrap", timeout=900)
        uid = adb("shell", "stat", "-c", "%u", "/data/user/0/com.termux")
        assert uid.isdigit(), f"Invalid Termux UID: {uid!r}"

        remote_installer = HOME + "/install-box64-arm64.sh"
        remote_runner = HOME + "/run-box64-arm64-test.sh"
        adb("push", INSTALLER, remote_installer)
        wrapper = ("#!/data/data/com.termux/files/usr/bin/bash\n"
                   f"printf 'started\\n' > {HOME}/box64-test.started\n"
                   f"bash {remote_installer} > {HOME}/box64-test.log 2>&1\n"
                   "status=$?\n"
                   f"printf '%s\\n' \"$status\" > {HOME}/box64-test.exit\n"
                   f"if [ \"$status\" = 0 ]; then {PREFIX}/bin/box64 --version >> {HOME}/box64-test.log 2>&1; fi\n"
                   "exit 0\n")
        wrapper_local = EVIDENCE / "run-box64-arm64-test.sh"
        wrapper_local.write_text(wrapper)
        adb("push", wrapper_local, remote_runner)
        adb("shell", "chown", f"{uid}:{uid}", remote_installer, remote_runner)
        adb("shell", "chmod", "700", remote_installer, remote_runner)
        adb("shell", "restorecon", remote_installer, remote_runner, check=False)
        adb("shell", "rm", "-f", HOME + "/box64-test.started", HOME + "/box64-test.exit", HOME + "/box64-test.log", check=False)

        adb("shell", "am", "force-stop", "com.termux", check=False)
        adb("shell", "monkey", "-p", "com.termux", "1", check=False)
        time.sleep(5)
        adb("shell", "input", "tap", "100", "1100", check=False)
        # Execute through Termux's own foreground terminal UI; no shell-as-UID
        # shortcut or harness-side execution is used for this smoke test.
        adb("shell", "input", "text", "bash%strun-box64-arm64-test.sh")
        adb("shell", "input", "keyevent", "66")
        wait_for(lambda: (started if (started := adb("shell", "sh", "-c",
                 f"test -f {HOME}/box64-test.started && echo started", check=False)) == "started" else ""),
                 "Box64 install command start marker", timeout=60)
        exit_code = wait_for(lambda: (value if (value := adb("shell", "cat", HOME + "/box64-test.exit", check=False)).isdigit() else ""),
                             "Box64 install completion", timeout=1200)
        log = adb("shell", "cat", HOME + "/box64-test.log", check=False)
        report["install_exit_code"] = int(exit_code)
        report["installer_log"] = log[-16000:]
        report["box64_version_output"] = adb("shell", "grep", "-m", "1", "-E", "Box64|box64", HOME + "/box64-test.log", check=False)
        report["box64_executable_exists"] = adb("shell", "test", "-x", PREFIX + "/bin/box64", "&&", "echo yes", check=False).strip() == "yes"
        assert report["install_exit_code"] == 0, log[-6000:]
        assert report["box64_executable_exists"], "Pinned installer did not create $PREFIX/bin/box64"
        assert report["box64_version_output"], "box64 --version produced no identifying output"
        report["status"] = "PASS"
    except Exception as exc:
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        try:
            report["termux_log"] = adb("shell", "cat", HOME + "/box64-test.log", check=False)[-16000:]
            report["logcat_tail"] = adb("logcat", "-d", check=False)[-10000:]
        except Exception:
            pass
        raise
    finally:
        (EVIDENCE / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
