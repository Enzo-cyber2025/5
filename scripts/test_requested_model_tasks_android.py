#!/usr/bin/env python3
"""Exercise folder access, Termux hand-off, Box64, APK build, and zero limits per real model."""
import hashlib
import json
import os
import re
import shlex
import time
import traceback
from pathlib import Path

import test_mobile as mobile
from test_mobile import MobileAndroid
from test_inference_android import reply
from test_tool_integrations_android import set_termux_external_apps, tap_tool
from test_gemma3_270m_android import import_model_via_saf
from android_checks import PACKAGE, PICKERS, has_package, position

EVIDENCE = Path("evidence")
APK = Path(os.environ.get("GGUF_TEST_APK", ".cache/GGUF-Chat-mobile.apk"))
TERMUX_APK = Path(os.environ.get("GGUF_TERMUX_TEST_APK", ".cache/termux-app-x86_64.apk"))
VARIANT = os.environ.get("MODEL_VARIANT", "gemma3-270m")
MARKER = "BLUE-LANTERN-5831"
TERMUX_HOME = "/data/data/com.termux/files/home"
FOLDER = TERMUX_HOME + "/model-audit"

FOLDER_COMMAND = f"cat {FOLDER}/only-note.txt > {TERMUX_HOME}/model-audit-output.txt"
BOX64_COMMAND = (
    "pkg install -y box64 > " + TERMUX_HOME + "/box64-install.log 2>&1; "
    "echo $? > " + TERMUX_HOME + "/box64-install.status"
)
BUILD_COMMAND = "bash " + TERMUX_HOME + "/text-binary/run-build.sh"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assistant_code(answer):
    blocks = re.findall(r"```(?:bash|sh|shell|termux)\s*\n(.*?)```", answer, flags=re.I | re.S)
    return blocks[-1].strip() if blocks else answer.strip()


def ask_for_command(device, model, prompt, expected, stage, summary):
    """Execute only an exact command proposed by the latest assistant message."""
    summary["checks"][stage] = {"prompt": prompt, "expected_command": expected,
                                "executed": False, "status": "INFERENCE_PENDING"}
    chat = device.new_chat(model, 0, context_size=2048, threads=2, n_predict=64)
    try:
        answer = reply(device, chat, prompt, stage, timeout=1200)
    except Exception as exc:
        summary["checks"][stage].update({"chat_id": chat["id"], "chat_title": chat["title"],
                                         "status": "INFERENCE_FAILED_OR_TIMEOUT",
                                         "inference_error": str(exc)})
        raise
    selected = assistant_code(answer)
    record = {"prompt": prompt, "assistant_reply": answer[:6000],
              "selected_command": selected, "expected_command": expected,
              "chat_id": chat["id"], "chat_title": chat["title"], "executed": False,
              "status": "AWAITING_REVIEW"}
    summary["checks"][stage] = record
    if selected != expected:
        record["status"] = "MODEL_DID_NOT_RETURN_THE_EXACT_REVIEWABLE_COMMAND"
        summary["checks"][stage] = record
        return None

    # Return to the exact conversation after the native worker may have closed its pane.
    device.launch()
    def active_chat():
        xml = device.ui()
        return (position(xml, desc="Alternar ferramentas", package={PACKAGE})
                and position(xml, desc="Anexar arquivos", package={PACKAGE})
                and position(xml, text="Enviar", contains=True, package={PACKAGE}))
    if not active_chat():
        device.tap(text=chat["title"], package={PACKAGE})
    device.wait(active_chat, "conversa exata reaberta com ferramentas e compositor visíveis", timeout=30)
    # Verify the app presents the exact model-generated code for human review.
    device.tap(desc="Alternar ferramentas", package={PACKAGE})
    def tools_open():
        import xml.etree.ElementTree as ET
        return any(n.get("content-desc") == "Ferramentas da conversa"
                   for n in ET.fromstring(device.ui()).iter("node"))
    device.wait(tools_open, "linha de ferramentas da conversa", timeout=15)
    tap_tool(device, "Termux")
    device.wait(lambda: position(device.ui(), text="Revisar comando do Termux",
                                 contains=True, package={PACKAGE}),
                "diálogo de revisão do comando proposto pelo modelo", timeout=30)
    # The current UI dump is saved by device.ui(); use a fresh dump and inspect it.
    import xml.etree.ElementTree as ET
    tree = ET.fromstring(device.ui())
    labels = [n.get("text", "") for n in tree.iter("node")]
    if expected not in labels:
        record["status"] = "REVIEW_DIALOG_DID_NOT_SHOW_EXACT_COMMAND"
        summary["checks"][stage] = record
        return None
    record["review_dialog_exact_match"] = True
    record["confirmation"] = "automation tapped the app's explicit approval button in a disposable emulator; no human reviewed this CI prompt"
    record["human_confirmation"] = False
    record["termux_output_returned_to_model_automatically"] = False
    device.capture(stage + "-review.png")
    device.tap(text="Abrir no Termux", package={PACKAGE})

    def permission_point():
        xml = device.ui()
        if "permissioncontroller" not in xml.lower() and "permission" not in xml.lower():
            return None
        for label in ("Allow", "While using the app", "Allow only while using the app", "Permitir"):
            point = position(xml, text=label, package=None)
            if point:
                return point
        return None

    point = None
    try:
        point = device.wait(permission_point, "permissão RUN_COMMAND do Termux", timeout=12)
    except AssertionError:
        pass  # A prior grant is possible; the output file below remains the source of truth.
    if point:
        device.shell(f"input tap {point[0]} {point[1]}")

    completion = (TERMUX_HOME + "/model-audit-output.txt" if stage == "folder_termux_access"
                  else TERMUX_HOME + "/box64-install.status" if stage == "box64_install_attempt"
                  else TERMUX_HOME + "/text-binary/build.exit")
    record["completion_file"] = completion
    try:
        device.wait(lambda: device.shell("test -f " + shlex.quote(completion) + " && echo done", check=False) == "done",
                    "resultado do comando no Termux: " + stage, timeout=900)
        record["executed"] = True
        record["status"] = "TERMUX_COMMAND_COMPLETED"
    except AssertionError as exc:
        record["status"] = "TERMUX_OUTPUT_FILE_NOT_CREATED"
        record["execution_error"] = str(exc)
    summary["checks"][stage] = record
    return record if record["executed"] else None


def provision_text_model(device, source):
    """Stage a real text GGUF without reading several GB into host RAM."""
    device.shell(f"am force-stop {PACKAGE}")
    digest = sha256(source)
    dest = f"/data/user/0/{PACKAGE}/files/models/{source.name}"
    uid = device.shell(f"stat -c %u /data/user/0/{PACKAGE}")
    assert uid.isdigit(), "UID do aplicativo inválido"
    parent = str(Path(dest).parent)
    device.shell("mkdir -p " + shlex.quote(parent))
    device.adb("push", source, dest, timeout=1800)
    actual = device.shell("sha256sum " + shlex.quote(dest)).split()[0]
    assert actual == digest, "GGUF recebido pelo app difere do arquivo validado"
    device.shell(f"chown -R {uid}:{uid} {shlex.quote(parent)} && chmod 700 {shlex.quote(parent)} "
                 f"&& chmod 600 {shlex.quote(dest)} && restorecon -R {shlex.quote(parent)}")
    model = {"id": "ci-" + digest[:16], "name": source.stem, "fileName": source.name,
             "path": dest, "size": source.stat().st_size, "importedAt": int(time.time() * 1000),
             "multimodal": False, "mmprojPath": None}
    device.write_private("files/models.json", json.dumps([model]))
    device.launch()
    rows = device.read_json("models.json")
    matches = [row for row in rows if row.get("fileName") == source.name and row.get("path") == dest]
    assert len(matches) == 1, "O app não preservou o modelo de texto preparado"
    return matches[0]


def load_model(device):
    if VARIANT == "gemma4-e2b":
        mobile.MODEL = Path(".cache/gemma4-models/gemma-4-E2B-it-Q3_K_S.gguf")
        mobile.PROJ = Path(".cache/gemma4-models/mmproj-F16.gguf")
        # This battery is deliberately text-only. The exact signed Gemma 4 E2B
        # language GGUF is provisioned directly into app-private storage; earlier
        # acceptance already covers the much slower SAF model+mmproj merge. Avoid
        # spending this task's emulator budget re-merging the 3.4 GB vision pair.
        return provision_text_model(device, mobile.MODEL)
    if VARIANT == "gemma3-270m":
        source = Path(".cache/gemma-3-270m-it-Q8_0.gguf")
        return import_model_via_saf(device, source)
    raise ValueError("MODEL_VARIANT desconhecida: " + VARIANT)


def check_settings_screen(device):
    device.launch()
    first = device.ui()
    if position(first, text="Ajustes", package={PACKAGE}):
        device.tap(text="Ajustes", package={PACKAGE})
        device.ui()
    texts = []
    for page in range(3):
        xml = device.ui()
        import xml.etree.ElementTree as ET
        texts.extend(n.get("text", "") for n in ET.fromstring(xml).iter("node") if n.get("text"))
        device.shell("input swipe 360 1080 360 360 350")
    unique = list(dict.fromkeys(texts))
    terms = ("context", "contexto", "armazen", "storage", "memória", "memoria", "cache")
    candidates = [text for text in unique if any(term in text.casefold() for term in terms)]
    persistence_terms = ("armazenar contexto", "contexto no armazenamento", "persistir contexto",
                         "context storage", "context on disk", "save context to disk")
    return {"visible_settings_labels": unique,
            "storage_backed_context_option_found": any(
                any(term in text.casefold() for term in persistence_terms) for text in unique),
            "context_related_labels": candidates}


def prepare_termux_folder(device):
    uid = device.shell("stat -c %u /data/user/0/com.termux").strip()
    assert uid.isdigit(), "UID do Termux ausente"
    device.shell("rm -rf " + shlex.quote(FOLDER))
    device.shell("mkdir -p " + shlex.quote(FOLDER))
    body = "Arquivo unico da pasta de teste. Identificador: " + MARKER + "."
    path = FOLDER + "/only-note.txt"
    device.shell("printf %s " + shlex.quote(body) + " > " + shlex.quote(path))
    device.shell(f"chown -R {uid}:{uid} {shlex.quote(FOLDER)} && chmod 700 {shlex.quote(FOLDER)} "
                 f"&& chmod 600 {shlex.quote(path)} && restorecon -R {shlex.quote(FOLDER)}")
    files = device.shell("ls -A " + shlex.quote(FOLDER)).splitlines()
    assert files == ["only-note.txt"], files
    return {"path": FOLDER, "files": files, "file_content": body,
            "sha256": device.shell("sha256sum " + shlex.quote(path)).split()[0]}


def check_zero_limits(device, model, summary):
    chat = device.new_chat(model, 0, context_size=0, threads=2, n_predict=0)
    answer = reply(device, chat, "Reply with only: OK", VARIANT + "-zero-context-zero-response", timeout=900)
    log = device.adb("logcat", "-d")
    budget = re.search(r"GGUF_OUTPUT_BUDGET requested=0 effective=([1-9][0-9]*) available_context=([1-9][0-9]*)", log)
    prompt = re.search(r"GGUF_PROMPT_CACHE input_tokens=([1-9][0-9]*)", log)
    chats = device.read_json("chats.json")
    saved = next(c for c in chats if c["id"] == chat["id"])
    assert saved.get("contextSize") == 0 and saved.get("nPredict") == 0, saved
    assert budget and prompt, "Valores zero não chegaram ao orçamento nativo"
    assert int(budget.group(1)) == int(budget.group(2)), "Zero de resposta não usou o contexto restante"
    context = int(prompt.group(1)) + int(budget.group(2))
    device.launch()
    persisted = next(c for c in device.read_json("chats.json") if c["id"] == chat["id"])
    assert persisted.get("contextSize") == 0 and persisted.get("nPredict") == 0
    assert any(m.get("role") == "assistant" and m.get("content", "").strip()
               for m in persisted.get("messages", [])), "Histórico não persistiu no armazenamento interno"
    result = {"status": "PASS", "context_setting": 0, "response_limit_setting": 0,
              "model_context_tokens_observed": context,
              "prompt_tokens": int(prompt.group(1)), "remaining_response_budget": int(budget.group(1)),
              "effective_context_is_finite": True, "assistant_reply": answer,
              "chat_history_persisted_after_restart": True,
              "history_path": "/data/user/0/" + PACKAGE + "/files/chats.json",
              "explicit_context_on_disk_setting": "not found in Settings UI"}
    summary["checks"]["zero_context_and_zero_response_limits"] = result
    return result


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    device = MobileAndroid("emulator-5554", EVIDENCE)
    summary = {"status": "FAIL", "scope": "requested-Gemma-folder-Termux-Box64-APK-and-zero-limits",
               "variant": VARIANT,
               "apk": {"sha256": sha256(APK), "expected_sha256": "f228a5d150348da37b365de541c99021b06fcb4eaa2713712cae816f0c10dbbc"},
               "checks": {}, "limitations": ["Android emulator x86_64, not a physical handset"]}
    try:
        assert sha256(APK) == summary["apk"]["expected_sha256"]
        assert device.shell("getprop ro.kernel.qemu") == "1"
        device.adb("root", check=False); device.adb("wait-for-device", timeout=90)
        assert device.shell("id -u") == "0"
        device.shell("pm disable-user --user 0 com.google.android.apps.nexuslauncher", check=False)
        device.shell("am force-stop com.google.android.apps.nexuslauncher", check=False)
        device.shell("wm size 720x1280"); device.shell("wm density 240")
        device.adb("logcat", "-G", "32M", check=False)
        if VARIANT == "gemma4-e2b":
            model_path = Path(".cache/gemma4-models/gemma-4-E2B-it-Q3_K_S.gguf")
            proj_path = Path(".cache/gemma4-models/mmproj-F16.gguf")
            summary["model"] = {"name": "Gemma 4 E2B", "quantization": "Q3_K_S text weights; mmproj omitted for text-only task",
                                 "weights_sha256": sha256(model_path), "projector_sha256": sha256(proj_path),
                                 "projector_used_in_this_task": False}
        else:
            model_path = Path(".cache/gemma-3-270m-it-Q8_0.gguf")
            summary["model"] = {"name": "Gemma 3 270M IT", "quantization": "Q8_0",
                                 "weights_sha256": sha256(model_path)}
        summary["model"]["apk_signed_sha256"] = sha256(APK)

        device.adb("install", "-r", "-g", APK, timeout=300)
        assert device.shell("pm clear " + PACKAGE) == "Success"
        device.grant_test_notifications(); device.launch()
        model = load_model(device)
        summary["model"].update({"app_name": model.get("name"), "architecture": model.get("architecture"),
                                 "capability": model.get("capability"), "size": model.get("size")})
        if VARIANT == "gemma4-e2b":
            summary["checks"]["signed_apk_and_real_gguf_provisioning"] = {
                "status": "PASS", "method": "ADB provisioning into app-private models directory",
                "SAF_import_in_this_task": False,
                "note": "Text-only Gemma 4 task; prior release acceptance covers SAF pair merge."
            }
        else:
            summary["checks"]["signed_apk_and_real_gguf_import"] = "PASS"

        summary["settings_ui"] = check_settings_screen(device)
        # Create the single-file folder in Termux's own private home. Nothing else
        # is placed in it; shell output is copied back to the model by the harness.
        device.adb("install", "-r", TERMUX_APK, timeout=180)
        device.shell("monkey -p com.termux 1", check=False)
        device.wait(lambda: device.shell("test -x /data/data/com.termux/files/usr/bin/bash && echo ready", check=False) == "ready",
                    "Termux bootstrap", timeout=360)
        uid = device.shell("stat -c %u /data/user/0/com.termux").strip()
        prop = TERMUX_HOME + "/.termux/termux.properties"
        device.shell("mkdir -p " + shlex.quote(TERMUX_HOME + "/.termux"))
        device.shell("printf 'allow-external-apps=true\\n' > " + shlex.quote(prop))
        device.shell(f"chown -R {uid}:{uid} {shlex.quote(TERMUX_HOME + '/.termux')} && chmod 700 {shlex.quote(TERMUX_HOME + '/.termux')} "
                     f"&& chmod 600 {shlex.quote(prop)} && restorecon -R {shlex.quote(TERMUX_HOME + '/.termux')}")
        device.shell("am force-stop com.termux"); device.shell("monkey -p com.termux 1", check=False)
        device.wait(lambda: device.shell("test -x /data/data/com.termux/files/usr/bin/bash && echo ready", check=False) == "ready",
                    "Termux com allow-external-apps", timeout=90)
        summary["checks"]["official_termux_bootstrap"] = "PASS"

        folder = prepare_termux_folder(device)
        summary["folder_fixture"] = folder
        folder_prompt = ("Inspect the output from your Termux folder command and describe what is inside the folder. "
                         "Name the only text file and repeat its identifier exactly. Output: " +
                         "the folder listing shows only-note.txt; its contents are: " + folder["file_content"])
        # First ask the model for the actual shell command. Then send the real
        # output back as a user message, since this app deliberately does not
        # pipe Termux output back into the model automatically.
        record = ask_for_command(device, model,
            "Use Termux to inspect the folder. Return only a fenced bash block with exactly this command:\\n" + FOLDER_COMMAND,
            FOLDER_COMMAND, "folder_termux_access", summary)
        if record:
            output = device.shell("cat " + shlex.quote(TERMUX_HOME + "/model-audit-output.txt")).strip()
            assert MARKER in output, output
            record["shell_output"] = output
            chats = device.read_json("chats.json")
            chat = next(c for c in chats if c["id"] == record["chat_id"])
            device.launch(); device.open_existing_chat(chat["title"])
            description = reply(device, chat, folder_prompt + " Actual Termux output: " + output,
                                VARIANT + "-describe-folder-output", timeout=600)
            record["description_reply"] = description
            record["description_status"] = "PASS" if MARKER.casefold() in description.casefold() and "only-note.txt" in description.casefold() else "NOT_PASS"
            summary["checks"]["model_describes_actual_folder_contents"] = record["description_status"]

        # Context=0 and response=0 are tested on the actual selected GGUF. A
        # restart then proves chat history stays in app-private storage.
        zero = check_zero_limits(device, model, summary)

        # Stage a minimal Java Android project and android.jar into Termux home.
        source_dir = Path("tests/android-text-binary")
        host_sdk = Path(os.environ.get("ANDROID_HOME", os.environ.get("ANDROID_SDK_ROOT", "")))
        android_jar = host_sdk / "platforms/android-35/android.jar"
        assert android_jar.is_file(), "Android API 35 android.jar missing on runner"
        project = TERMUX_HOME + "/text-binary"
        device.shell("mkdir -p " + shlex.quote(project))
        for filename in ("AndroidManifest.xml", "MainActivity.java", "build-termux.sh", "run-build.sh"):
            device.adb("push", source_dir / filename, project + "/" + filename, timeout=120)
        device.adb("push", android_jar, project + "/android.jar", timeout=300)
        device.shell(f"chown -R {uid}:{uid} {shlex.quote(project)} && chmod 700 {shlex.quote(project)} "
                     f"&& chmod 700 {shlex.quote(project + '/build-termux.sh')} && restorecon -R {shlex.quote(project)}")
        summary["checks"]["text_to_binary_project_staged_in_termux_home"] = "PASS"

        # The install attempt is intentionally performed by a model-proposed,
        # UI-reviewed Termux command. Box64 is architecture-specific; no fallback
        # binary is substituted if the official package is unavailable.
        box_prompt = ("Install Box64 in Termux now. Return only a fenced bash block whose single command is exactly:\\n"
                      + BOX64_COMMAND)
        box = ask_for_command(device, model, box_prompt, BOX64_COMMAND, "box64_install_attempt", summary)
        if box:
            box_log = device.shell("cat " + shlex.quote(TERMUX_HOME + "/box64-install.log"), check=False)
            box_exit = device.shell("cat " + shlex.quote(TERMUX_HOME + "/box64-install.status"), check=False).strip()
            box["exit_code"] = box_exit
            box["log_tail"] = box_log[-8000:]
            box["box64_executable"] = ("/data/data/com.termux/files/usr/bin/box64"
                                        if device.shell("test -x /data/data/com.termux/files/usr/bin/box64 && echo yes", check=False).strip() == "yes"
                                        else "")
            box["status"] = "INSTALLED" if box_exit == "0" and box["box64_executable"] else "PACKAGE_UNAVAILABLE_OR_FAILED"
            summary["checks"]["box64_install_result"] = box["status"]
            if box["status"] != "INSTALLED":
                summary["limitations"].append("Box64 package was attempted in the x86_64 Termux emulator; installation did not produce a box64 executable.")

        build_prompt = ("Compile the staged Text to Binary Android project into an APK from Termux. "
                        "Return only one fenced bash block whose exact command is:\n" + BUILD_COMMAND)
        build = ask_for_command(device, model, build_prompt, BUILD_COMMAND, "termux_compile_text_to_binary_apk", summary)
        if build:
            build_log = device.shell("cat " + shlex.quote(project + "/build.log"), check=False)
            tools_log = device.shell("cat " + shlex.quote(project + "/build-tools-install.log"), check=False)
            build_exit = device.shell("cat " + shlex.quote(project + "/build.exit"), check=False).strip()
            build["exit_code"] = build_exit
            build["build_log_tail"] = build_log[-12000:]
            build["tool_install_log_tail"] = tools_log[-6000:]
            summary["checks"]["termux_apk_build_result"] = "PASS" if build_exit == "0" else "FAIL"
            if build_exit == "0":
                termux_apk = Path(".cache/TextToBinary.apk")
                termux_apk.parent.mkdir(parents=True, exist_ok=True)
                device.adb("pull", project + "/out/TextToBinary.apk", termux_apk, timeout=120)
                assert termux_apk.is_file() and termux_apk.stat().st_size > 1000
                summary["compiled_apk"] = {"path": str(termux_apk), "bytes": termux_apk.stat().st_size,
                                            "sha256": sha256(termux_apk), "built_inside": "Termux on Android emulator"}
                device.adb("install", "-r", termux_apk, timeout=180)
                started = device.shell("am start -W -n com.example.textbinary/.MainActivity")
                assert "Status: ok" in started, started
                device.wait(lambda: position(device.ui(), desc="text-input", package={"com.example.textbinary"}),
                            "APK de conversão iniciou e expôs entrada", timeout=30)
                device.tap(desc="text-input", package={"com.example.textbinary"})
                device.shell("input text A")
                device.tap(desc="convert-button", package={"com.example.textbinary"})
                device.wait(lambda: position(device.ui(), text="01000001", package={"com.example.textbinary"}),
                            "conversão real de A para 01000001", timeout=20)
                device.capture("text-to-binary-installed.png")
                summary["checks"]["compiled_apk_installed_and_text_converted_to_binary"] = "PASS"
                # Keep the small deliverable available from the Actions artifact.
                (EVIDENCE / "TextToBinary.apk").write_bytes(termux_apk.read_bytes())

        summary["internal_context_storage"] = {
            "conversation_history_saved_in_private_app_files": zero["chat_history_persisted_after_restart"],
            "explicit_context_storage_toggle_in_settings": summary["settings_ui"]["storage_backed_context_option_found"],
            "native_KV_cache_persistence": "not claimed or tested; chat transcript persistence is separate"
        }
        core = all(summary["checks"].get(key) == "PASS" for key in (
            "signed_apk_and_real_gguf_import", "official_termux_bootstrap",
            "model_describes_actual_folder_contents", "zero_context_and_zero_response_limits",
            "termux_apk_build_result", "compiled_apk_installed_and_text_converted_to_binary"))
        box_status = summary["checks"].get("box64_install_result")
        summary["status"] = "PASS" if core and box_status == "INSTALLED" else "PARTIAL" if core else "FAIL"
    except Exception as exc:
        summary["error"] = str(exc)
        summary["traceback"] = traceback.format_exc()
        try:
            summary["logcat_tail"] = device.adb("logcat", "-d", check=False)[-12000:]
            summary["last_ui_summary"] = device.last_ui_summary
        except Exception:
            pass
        traceback.print_exc()
    finally:
        try:
            (EVIDENCE / "final-logcat.txt").write_text(device.adb("logcat", "-d"))
        except Exception:
            pass
        (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
