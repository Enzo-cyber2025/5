#!/usr/bin/env python3
"""Real SAF import and native Android inference with Gemma 3 270M GGUF."""
import hashlib
import json
import re
import traceback
from pathlib import Path

from test_android import Android
from android_checks import PACKAGE, PICKERS, has_package, imported, position

EVIDENCE = Path("evidence")
APK = Path(".cache/GGUF-Chat-mobile.apk")
MODEL = Path(".cache/gemma-3-270m-it-Q8_0.gguf")
APK_SHA256 = "f228a5d150348da37b365de541c99021b06fcb4eaa2713712cae816f0c10dbbc"
APK_CERT_SHA256 = "9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a"
MODEL_SHA256 = "d156a5159f2f79c1b1d53c7c1cc20f1ff28ab8d00f17a292620aad13399b9698"
MODEL_BYTES = 291546144


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def import_model_via_saf(device, source):
    """Handle either supported UI path: direct picker or an Import GGUF sheet."""
    device.launch()
    device.adb("push", source, f"/sdcard/Download/{source.name}", timeout=300)
    device.shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "
                 f"file:///storage/emulated/0/Download/{source.name}", check=False)
    # On this signed release, the importer is a bottom tab labelled with an
    # icon; the similarly named header is not the navigation control.
    if position(device.ui(), text="📁 Importar", package={PACKAGE}):
        device.tap(text="📁 Importar", package={PACKAGE})

    def destination():
        xml = device.ui()
        if has_package(xml, PICKERS):
            return "picker"
        if position(xml, text="Importar GGUF", package={PACKAGE}):
            return "import-sheet"
        if position(xml, text="Importar .gguf", package={PACKAGE}):
            return "import-action"
        return None

    state = device.wait(destination, "ação de importação GGUF ou seletor SAF", timeout=30)
    if state == "import-sheet":
        device.tap(text="Importar GGUF", package={PACKAGE})
        device.wait(lambda: has_package(device.ui(), PICKERS), "seletor SAF")
    elif state == "import-action":
        device.tap(text="Importar .gguf", package={PACKAGE})
        device.wait(lambda: has_package(device.ui(), PICKERS), "seletor SAF")
    device.choose_file(source.name)

    def imported_model():
        device.alive()
        try:
            return imported(device.read_json("models.json", optional=True), source.name)
        except AssertionError:
            return None

    return device.wait(imported_model, "importação SAF persistida", timeout=300)


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    device = Android("emulator-5554", EVIDENCE)
    summary = {
        "status": "FAIL",
        "scope": "signed-APK-real-SAF-import-and-Gemma-3-270M-native-text-inference",
        "environment": "Android API 35 x86_64 emulator; CPU inference; not physical-device acceptance",
        "apk": {"sha256": sha256(APK) if APK.exists() else None,
                "expected_sha256": APK_SHA256,
                "certificate_sha256": APK_CERT_SHA256,
                "certificate_evidence": "previous signed-publication acceptance, run 34909764328; exact APK hash pinned above"},
        "model": {"repository": "cdracars/gemma-3-270m-it-gguf-mirror",
                  "release_tag": "upstream-d156a5159f2f79c1b1d53c7c1cc20f1ff28ab8d00f17a292620aad13399b9698",
                  "asset": MODEL.name,
                  "quantization": "Q8_0",
                  "bytes": MODEL.stat().st_size if MODEL.exists() else None,
                  "sha256": sha256(MODEL) if MODEL.exists() else None,
                  "expected_sha256": MODEL_SHA256},
        "checks": {},
        "response_quality": {},
    }
    try:
        assert summary["apk"]["sha256"] == APK_SHA256, "APK SHA-256 mismatch"
        assert summary["model"]["bytes"] == MODEL_BYTES, "GGUF byte size mismatch"
        assert summary["model"]["sha256"] == MODEL_SHA256, "GGUF SHA-256 mismatch"
        assert device.shell("getprop ro.kernel.qemu") == "1", "Runner is not the declared emulator"
        device.adb("root", check=False)
        device.adb("wait-for-device", timeout=90)
        device.shell("wm size 720x1280")
        device.shell("wm density 240")
        device.adb("logcat", "-G", "16M", check=False)
        device.adb("install", "-g", APK, timeout=300)
        assert device.shell("pm clear " + PACKAGE) == "Success"
        device.grant_test_notifications()
        device.launch()
        summary["checks"]["signed_apk_installed_and_launched"] = "PASS"

        model = import_model_via_saf(device, MODEL)
        assert model["size"] == MODEL_BYTES, model
        assert model.get("architecture", "").lower() == "gemma3", model
        assert not model.get("mmprojPath") and not model.get("multimodal"), model
        summary["model"].update({"imported_name": model.get("name"),
                                 "architecture": model.get("architecture"),
                                 "capability": model.get("capability"),
                                 "app_reported_size": model.get("size")})
        summary["checks"]["real_SAF_GGUF_import_architecture_and_size"] = "PASS"
        (EVIDENCE / "gemma3-270m-imported-model.json").write_text(
            json.dumps(model, indent=2, ensure_ascii=False))

        prompt = "What is 2 + 2? Reply with only the number."
        log = device.generate(model, 0, "gemma3-270m-text", prompt=prompt)
        chats = device.read_json("chats.json")
        reply_file = EVIDENCE / "gemma3-270m-text-reply.txt"
        reply = reply_file.read_text().strip() if reply_file.exists() else ""
        assert "GGUF_NATIVE_COMPLETE" in log, "Native generation completion marker missing"
        assert reply, "No persisted assistant response after native completion"
        summary["checks"]["native_text_generation_and_persisted_reply"] = "PASS"
        summary["response_quality"]["arithmetic_2_plus_2"] = {
            "status": "PASS" if re.fullmatch(r"4[.!\s]*", reply) else "NOT_PASS",
            "expected": "4", "response": reply}
        summary["chat_count"] = len(chats)
        summary["status"] = "PASS"
    except Exception as exc:
        summary["error"] = str(exc)
        summary["traceback"] = traceback.format_exc()
        summary["last_ui_summary"] = device.last_ui_summary
        (EVIDENCE / "gemma3-270m-failure.txt").write_text(summary["traceback"])
        traceback.print_exc()
    finally:
        try:
            (EVIDENCE / "gemma3-270m-final-logcat.txt").write_text(device.adb("logcat", "-d"))
            device.capture("gemma3-270m-final-screen.png")
        except Exception:
            pass
        (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
