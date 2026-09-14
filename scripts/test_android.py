#!/usr/bin/env python3
"""Strict, destructive integration suite for a DISPOSABLE rooted Android emulator.

Requires a real text GGUF supplied via --model; there is no fake-model fallback.
Optional --vision/--mmproj verifies SAF import and link persistence, not image inference.
Every critical command/assertion fails the run; diagnostics are always retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET

from android_checks import (PACKAGE, PICKERS, assistant_reply, fusion, generation_completed,
                            gpu_offloaded, has_package, imported, position, basic_response_quality, vulkan_offloaded)


class Android:
    def __init__(self, serial, evidence):
        self.serial, self.evidence = serial, evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.generation_pid = None
        self.last_ui_summary = None

    def adb(self, *args, check=True, timeout=45, binary=False, with_status=False):
        result = subprocess.run(["adb", "-s", self.serial, *map(str, args)], capture_output=True, timeout=timeout)
        with (self.evidence / "commands.log").open("a") as f:
            f.write(f"$ adb {' '.join(map(str, args))}\nexit={result.returncode}\n")
            if not binary:
                output = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
                # Keep diagnostics useful: final dumpsys/logcat must not bury the
                # command which actually failed in a multi-megabyte log tail.
                f.write(output[:4096] + ("\n[output truncated]\n" if len(output) > 4096 else ""))
        if check and result.returncode:
            detail = (result.stdout + result.stderr).decode(errors="replace")[-3000:]
            raise RuntimeError(f"ADB falhou ({result.returncode}): {args}\n{detail}")
        if with_status:
            return result
        return result.stdout if binary else result.stdout.decode(errors="replace").strip()

    def shell(self, command, **kwargs):
        return self.adb("shell", command, **kwargs)

    def ui(self):
        # Never reuse a stale UI dump after a navigation/failed command.
        self.shell("rm -f /sdcard/gguf-test-ui.xml")
        self.shell("uiautomator dump /sdcard/gguf-test-ui.xml")
        xml = self.adb("exec-out", "cat", "/sdcard/gguf-test-ui.xml")
        root = ET.fromstring(xml)
        summary = [{k: n.get(k) for k in ("text", "content-desc", "resource-id", "bounds", "enabled", "selected")}
                   for n in root.iter("node") if n.get("text") or n.get("content-desc")]
        if summary != self.last_ui_summary:
            print("UI " + json.dumps(summary, ensure_ascii=False), flush=True)
            self.last_ui_summary = summary
        self.counter += 1
        (self.evidence / f"ui-{self.counter:04d}.xml").write_text(xml)
        return xml

    def capture(self, name):
        (self.evidence / name).write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))

    def wait(self, fn, description, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = fn()
            if result:
                return result
            time.sleep(1)
        raise AssertionError(f"Timeout: {description}")

    def tap(self, *, optional=False, **selector):
        point = position(self.ui(), **selector)
        if point is None:
            if optional:
                return False
            raise AssertionError(f"Controle não encontrado: {selector}")
        self.shell(f"input tap {point[0]} {point[1]}")
        return True

    def alive(self):
        pid = self.shell(f"pidof {PACKAGE}", check=False)
        if not pid:
            raise AssertionError("Processo do app ausente; isso não prova sozinho um crash nativo")
        return pid.split()[0]

    def check_cpp_runtime(self, directory):
        target = "/data/local/tmp/gguf-native-regression"
        self.shell(f"mkdir -p {target}")
        for name in ("runtime-probe", "original-libc++_shared.so", "fixed-libc++_shared.so"):
            self.adb("push", directory / name, target + "/" + name)
        self.shell(f"chmod 755 {target}/runtime-probe")
        reports = {}
        try:
            for kind, expected_exit, expected_preserved in (("fixed", 0, True), ("original", 1, False)):
                result = self.adb("shell", f"{target}/runtime-probe {target}/{kind}-libc++_shared.so",
                                  check=False, with_status=True)
                report = {"exit_code": result.returncode,
                          "stdout": result.stdout.decode(errors="replace"),
                          "stderr": result.stderr.decode(errors="replace")}
                reports[kind] = report
                report["result"] = json.loads(report["stdout"])
                if result.returncode != expected_exit or report["result"].get("callee_saved_preserved") is not expected_preserved:
                    raise AssertionError(f"Controle de ABI C++ inesperado: {kind}: {report}")
                if report["result"].get("pthread_mutexattr_size") != 8:
                    raise AssertionError("Probe não está usando a ABI Bionic LP64 esperada")
        finally:
            (self.evidence / "runtime-regression.json").write_text(json.dumps(reports, indent=2))
            (self.evidence / "runtime-provenance.json").write_bytes((directory / "runtime-provenance.json").read_bytes())

    def grant_test_notifications(self):
        # pm clear resets the -g install grant. Only the disposable test app's
        # notification permission is needed; this is not permission-dialog validation.
        sdk = int(self.shell("getprop ro.build.version.sdk"))
        if sdk >= 33:
            self.shell(f"pm grant {PACKAGE} android.permission.POST_NOTIFICATIONS")
        return sdk

    def launch(self):
        # Clear the task too: a stale DocumentsUI must not remain over the app.
        # Android 11's am parser does not support --activity-new-task.
        # Use the documented numeric Intent flags: NEW_TASK | CLEAR_TASK.
        out = self.shell(f"am start -W -S -f 0x10008000 -n {PACKAGE}/.MainActivity")
        if "Status: ok" not in out:
            raise AssertionError(f"Activity não iniciou: {out}")
        self.wait(lambda: has_package(self.ui(), {PACKAGE}), "MainActivity em primeiro plano")
        self.alive()

    def read_json(self, name, optional=False):
        path = shlex.quote(f"/data/user/0/{PACKAGE}/files/{name}")
        # exec-out can merge cat's stderr into stdout. A missing optional store
        # is [], but malformed JSON and permission errors must still fail.
        command = f"cat {path}"
        if optional:
            command = f"if [ -e {path} ]; then cat {path}; else printf '[]'; fi"
        output = self.shell(command)
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"JSON inválido em {name}: {output[:250]!r}") from exc

    def write_private(self, relative, data):
        uid = self.shell(f"stat -c %u /data/user/0/{PACKAGE}")
        if not uid.isdigit():
            raise AssertionError("UID do aplicativo inválido")
        temp = self.evidence / "private-input.tmp"
        temp.write_text(data)
        self.adb("push", temp, "/data/local/tmp/gguf-test-input")
        dest = f"/data/user/0/{PACKAGE}/{relative}"
        parent = str(Path(dest).parent)
        # File and directory ownership AND SELinux labels must be correct.
        self.shell(f"mkdir -p {shlex.quote(parent)} && cp /data/local/tmp/gguf-test-input {shlex.quote(dest)} "
                   f"&& chown {uid}:{uid} {shlex.quote(parent)} {shlex.quote(dest)} "
                   f"&& chmod 700 {shlex.quote(parent)} && chmod 600 {shlex.quote(dest)} "
                   f"&& restorecon -R {shlex.quote(parent)}")
        temp.unlink()

    def provision_model(self, source):
        """Real GGUF, test setup only. Explicitly does NOT validate the SAF importer."""
        self.shell(f"am force-stop {PACKAGE}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        dest = f"/data/user/0/{PACKAGE}/files/models/{source.name}"
        uid = self.shell(f"stat -c %u /data/user/0/{PACKAGE}")
        if not uid.isdigit():
            raise AssertionError("UID do aplicativo inválido")
        parent = str(Path(dest).parent)
        self.shell("mkdir -p " + shlex.quote(parent))
        self.adb("push", source, dest, timeout=300)
        actual = self.shell("sha256sum " + shlex.quote(dest)).split()[0]
        if actual != digest:
            raise AssertionError("GGUF transferido difere do arquivo real de entrada")
        self.shell(f"chown -R {uid}:{uid} {shlex.quote(parent)} && chmod 700 {shlex.quote(parent)} "
                   f"&& chmod 600 {shlex.quote(dest)} && restorecon -R {shlex.quote(parent)}")
        model = dict(id="ci-" + digest[:16], name=source.stem, fileName=source.name,
                     path=dest, size=source.stat().st_size, importedAt=int(time.time() * 1000),
                     multimodal=False, mmprojPath=None)
        self.write_private("files/models.json", json.dumps([model]))
        self.launch()
        saved = imported(self.read_json("models.json"), source.name)
        if saved["path"] != dest:
            raise AssertionError("Modelo preparado não foi preservado pelo app")
        return saved

    def select_downloads(self):
        for label in ("Downloads", "Download"):
            if self.tap(text=label, resource_id="android:id/title", package=PICKERS, optional=True):
                return
        raise AssertionError("Raiz Downloads ausente no menu SAF")

    def confirm_picker(self, xml):
        for label in ("Open", "Abrir", "Select", "Selecionar", "Done", "Concluído"):
            point = position(xml, text=label, package=PICKERS) or position(xml, desc=label, package=PICKERS)
            if point:
                self.shell(f"input tap {point[0]} {point[1]}")
                return True
        return False

    def choose_file(self, filename):
        for attempt in range(4):
            xml = self.ui()
            if not has_package(xml, PICKERS):
                return
            # DocumentsUI also dumps the obscured page behind its root drawer.
            # Never tap a filename or breadcrumb through that drawer.
            if any(position(xml, text=t, package=PICKERS) for t in ("Open from", "Abrir de")):
                self.select_downloads()
                time.sleep(2)
                continue
            point = position(xml, text=filename, package=PICKERS)
            if point:
                self.shell(f"input tap {point[0]} {point[1]}")
                time.sleep(2)
                xml = self.ui()
                if not has_package(xml, PICKERS):
                    return
                if self.confirm_picker(xml):
                    self.wait(lambda: not has_package(self.ui(), PICKERS), "retorno do SAF")
                    return
                # Multi-select DocumentsUI may require long-press before Open appears.
                point = position(xml, text=filename, package=PICKERS)
                if point:
                    x, y = point
                    self.shell(f"input touchscreen swipe {x} {y} {x} {y} 1000")
                    time.sleep(1)
                    if self.confirm_picker(self.ui()):
                        self.wait(lambda: not has_package(self.ui(), PICKERS), "confirmação SAF")
                        return
            for desc in ("Show roots", "Mostrar raízes"):
                if self.tap(desc=desc, package=PICKERS, optional=True):
                    break
            self.select_downloads()
            time.sleep(2)
        raise AssertionError(f"Falha ao selecionar {filename}; nenhuma importação será presumida")

    def import_model(self, source):
        self.launch()
        self.adb("push", source, f"/sdcard/Download/{source.name}", timeout=300)
        self.shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d " +
                   shlex.quote(f"file:///storage/emulated/0/Download/{source.name}"), check=False)
        self.tap(text="Importar", package={PACKAGE}, contains=True)
        self.tap(text="Importar .gguf", package={PACKAGE}, contains=True)
        self.wait(lambda: has_package(self.ui(), PICKERS), "seletor de arquivos")
        self.choose_file(source.name)

        def completed():
            self.alive()
            models = self.read_json("models.json", optional=True)
            try:
                return imported(models, source.name)
            except AssertionError:
                return None
        return self.wait(completed, f"importação persistida de {source.name}", timeout=300)

    def new_chat(self, model, gpu_layers, context_size=1024):
        self.shell(f"am force-stop {PACKAGE}")
        prefs = ET.Element("map")
        for name, value in (("selectedModelId", model["id"]), ("selectedModelName", model["name"]),
                            ("selectedModelPath", model["path"])):
            ET.SubElement(prefs, "string", name=name).text = value
        for name, value in (("gpuLayers", gpu_layers), ("contextSize", context_size), ("nThreads", 2)):
            ET.SubElement(prefs, "int", name=name, value=str(value))
        self.write_private("shared_prefs/ggufchat_settings.xml", ET.tostring(prefs, encoding="unicode"))
        before = {c["id"] for c in self.read_json("chats.json", optional=True)}
        self.launch()
        self.tap(text="Nova conversa", package={PACKAGE}, contains=True)
        self.wait(lambda: position(self.ui(), text=model["name"], contains=True, package={PACKAGE}),
                  "modelo visível na seleção de nova conversa")
        self.tap(text=model["name"], contains=True, package={PACKAGE})

        def created():
            chats = self.read_json("chats.json", optional=True)
            return next((c for c in chats if c["id"] not in before), None)
        chat = self.wait(created, "nova conversa persistida")
        if chat.get("modelPath") != model["path"]:
            raise AssertionError("Conversa criada com modelo errado ou caminho perdido")
        # Bound test runtime; configure this specific new conversation, not unrelated data.
        self.shell(f"am force-stop {PACKAGE}")
        chats = self.read_json("chats.json")
        for c in chats:
            if c["id"] == chat["id"]:
                c.update(nPredict=128, temperature=0.0, contextSize=context_size,
                         gpuLayers=gpu_layers, webSearch=False, thinking=False)
                c["title"] = "GGUF regression " + chat["id"]
                chat = c
        self.write_private("files/chats.json", json.dumps(chats))
        self.launch()
        self.open_existing_chat(chat["title"])
        return chat

    def open_existing_chat(self, title):
        # After a cold activity launch, the first input can arrive before the
        # window accepts touch. Retry ONLY the same persisted row, never create
        # another chat or send a prompt twice. A native crash is not retried.
        expected_pid = self.alive()
        self.generation_pid = expected_pid
        def ready():
            if self.alive() != expected_pid:
                raise RuntimeError(f"Processo reiniciou durante abertura da conversa (PID esperado {expected_pid}); não repetir após crash")
            return position(self.ui(), class_name="android.widget.EditText", package={PACKAGE})
        for attempt in range(3):
            self.tap(text=title, package={PACKAGE})
            try:
                self.wait(ready, "tela da conversa", timeout=15)
                return
            except AssertionError:
                if self.alive() != expected_pid:
                    raise RuntimeError("Processo reiniciou; não repetir após crash")
                xml = self.ui()
                if attempt == 2 or not position(xml, text=title, package={PACKAGE}):
                    raise

    def send(self, prompt, clear_log=True):
        if clear_log:
            self.adb("logcat", "-c")
        self.tap(class_name="android.widget.EditText", package={PACKAGE})
        self.shell("input text " + shlex.quote(prompt.replace(" ", "%s")))
        self.tap(text="Enviar", package={PACKAGE}, contains=True)

    def generate(self, model, gpu_layers, stage, prompt="Reply in English with a short greeting."):
        # Keep model-loading/offload evidence: clearing at send loses the backend
        # selected by the preload worker. A new chat restarts the app; filter its PID.
        self.adb("logcat", "-c")
        chat = self.new_chat(model, gpu_layers)
        pid = self.alive()
        self.send(prompt, clear_log=False)
        def submitted():
            chats = self.read_json("chats.json")
            (self.evidence / f"{stage}-chats.json").write_text(json.dumps(chats, ensure_ascii=False))
            current = next(c for c in chats if c["id"] == chat["id"])
            return any(m.get("role") == "user" and m.get("content") == prompt
                       for m in current.get("messages", []))
        self.wait(submitted, "prompt enviado e persistido pelo aplicativo", timeout=30)

        def completed():
            self.alive()
            log = self.adb("logcat", "-d", f"--pid={pid}")
            (self.evidence / f"{stage}-logcat.txt").write_text(log)
            chats = self.read_json("chats.json")
            (self.evidence / f"{stage}-chats.json").write_text(json.dumps(chats, ensure_ascii=False))
            if not generation_completed(log):
                return None
            try:
                reply = assistant_reply(chats, chat["id"], prompt)
            except AssertionError:
                return None  # success marker precedes the atomic chat save
            (self.evidence / f"{stage}-chats.json").write_text(json.dumps(chats, ensure_ascii=False))
            (self.evidence / f"{stage}-reply.txt").write_text(reply)
            return log
        return self.wait(completed, f"geração real {stage}", timeout=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime-regression", type=Path, help="Native C++ ABI probe and original/fixed libraries (x86_64)")
    parser.add_argument("--model-setup", choices=("saf", "provisioned"), default="saf")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--vulkan-only", action="store_true", help="Require actual Vulkan offload and native completion")
    modes.add_argument("--generation-only", action="store_true",
                        help="Scope: two native CPU replies; not SAF, Vulkan or missing-model tests")
    parser.add_argument("--vision", type=Path)
    parser.add_argument("--mmproj", type=Path)
    parser.add_argument("--require-vulkan", action="store_true")
    parser.add_argument("--allow-data-reset", action="store_true")
    parser.add_argument("--evidence", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    if not args.allow_data_reset or not args.serial.startswith("emulator-"):
        parser.error("Use somente emulador descartável, com --allow-data-reset explícito.")
    if bool(args.vision) != bool(args.mmproj):
        parser.error("Forneça --vision e --mmproj juntos.")
    for path in [args.apk, args.model, args.vision, args.mmproj]:
        if path and not path.is_file():
            parser.error(f"Arquivo inexistente: {path}")
    if len({p.name for p in [args.model, args.vision, args.mmproj] if p}) != len([p for p in [args.model, args.vision, args.mmproj] if p]):
        parser.error("Os modelos devem ter nomes de arquivo distintos.")
    device = Android(args.serial, args.evidence)
    with zipfile.ZipFile(args.apk) as archive:
        fingerprints = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()
                        if n == "classes.dex" or n.startswith("lib/") and n.endswith(".so")}
    (args.evidence / "apk-payload.json").write_text(json.dumps(fingerprints, indent=2))
    result = {"status": "FAIL", "checks": {}, "apk_sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(),
              "scope": "vulkan-offload-generation" if args.vulkan_only else ("native-response-generation" if args.generation_only else "android-integration"),
              "generation_parameters": {"max_tokens": 128, "temperature": 0.0, "language_requested": "English"},
              "model_setup": args.model_setup, "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest()}
    try:
        if device.shell("getprop ro.kernel.qemu") != "1":
            raise AssertionError("O dispositivo não é um emulador")
        device.adb("root", check=False)  # adbd may close the transport while restarting; verify UID below
        device.adb("wait-for-device", timeout=60)
        if device.shell("id -u") != "0":
            raise AssertionError("É necessário emulador com adb root, não imagem Play Store")
        if args.runtime_regression:
            if device.shell("getprop ro.product.cpu.abi") != "x86_64":
                raise AssertionError("O controle de ABI exige o emulador x86_64")
            device.check_cpp_runtime(args.runtime_regression)
            result["checks"]["cpp_runtime_abi"] = "PASS: original corrupts RBX, official runtime preserves it"
        device.adb("logcat", "-G", "16M")  # retain native preload logs during cold shader compilation
        if args.vulkan_only:
            # Pixel Launcher ANRs in this software-rendered disposable image can
            # cover the app with a system dialog before Native is even loaded.
            # Isolate this background component; never dismiss an app ANR/crash.
            device.shell("pm disable-user --user 0 com.google.android.apps.nexuslauncher")
            device.shell("am force-stop com.google.android.apps.nexuslauncher")
            device.shell("wm size 720x1280")
            device.shell("wm density 240")
            result["checks"]["emulator_isolation"] = "Pixel Launcher disabled; 720x1280 at 240 dpi; disposable emulator only"
        result["checks"]["emulator"] = "BOOTED: " + device.shell("getprop ro.product.cpu.abi")
        device.adb("install", "-r", "-g", args.apk, timeout=120)
        result["checks"]["installation"] = "PASS"
        if device.shell(f"pm clear {PACKAGE}") != "Success":
            raise AssertionError("Falha ao limpar dados do emulador")
        sdk = device.grant_test_notifications()
        result["android_api"] = sdk
        result["checks"]["notification_setup"] = "GRANTED_FOR_TEST" if sdk >= 33 else "NOT_REQUIRED"
        device.shell("mkdir -p /sdcard/Download")
        device.launch()
        result["checks"]["launch"] = "PASS"
        device.capture("launch.png")
        if args.model_setup == "provisioned":
            model = device.provision_model(args.model)
            result["checks"]["text_import"] = "SKIP: modelo real preparado diretamente; SAF não validado"
            result["checks"]["model_provisioning"] = "PASS: SHA-256 no emulador confere"
        else:
            model = device.import_model(args.model)
            result["checks"]["text_import"] = "PASS"
        device.capture("import.png")
        if args.vision:
            device.import_model(args.vision)
            device.import_model(args.mmproj)
            before = fusion(device.read_json("models.json"), args.vision.name, args.mmproj.name)
            device.launch()
            after = fusion(device.read_json("models.json"), args.vision.name, args.mmproj.name)
            if before != after:
                raise AssertionError("Vínculo mudou após reiniciar")
            result["checks"]["fusion_persistence"] = "PASS (não testa inferência de imagem)"
        else:
            result["checks"]["fusion_persistence"] = "SKIP: par visão/mmproj não fornecido"
        if args.vulkan_only:
            result["generation_parameters"]["gpu_layers_requested"] = 99
            result["checks"]["answer_quality"] = "NOT_ASSESSED: teste de backend; falhas anteriores permanecem"
            for name, command in (("vulkan-device.json", "cmd gpu vkjson"),
                                  ("vulkan-features.txt", "pm list features"),
                                  ("graphics-properties.txt", "getprop")):
                (args.evidence / name).write_text(device.shell(command, check=False))
            # Bounded device facts remain legible when the full vkjson is large.
            raw_vk = (args.evidence / "vulkan-device.json").read_text()
            try:
                vk = json.loads(raw_vk)
                capabilities = {"loader_api_version": vk.get("apiVersion"), "devices": [
                    {"properties": {k: d.get("properties", {}).get(k) for k in
                        ("deviceName", "deviceType", "apiVersion", "driverVersion")},
                     "storage_16bit": d.get("16bitStorageFeatures"),
                     "core12_features": {k: d.get("core12", {}).get("features", {}).get(k)
                        for k in ("shaderFloat16", "shaderInt8", "storageBuffer8BitAccess")}}
                    for d in vk.get("devices", [])]}
            except (ValueError, TypeError, AttributeError) as exc:
                capabilities = {"diagnostic_error": str(exc)}
            (args.evidence / "vulkan-capabilities.json").write_text(json.dumps(capabilities, indent=2))
            try:
                vk_log = device.generate(model, 99, "vulkan")
                result["checks"]["native_generation"] = "PASS"
            finally:
                # Also retain backend details when generation/crash checks fail.
                pid = device.generation_pid
                if pid:
                    latest = device.adb("logcat", "-d", f"--pid={pid}", check=False)
                    (args.evidence / "vulkan-final-logcat.txt").write_text(latest)
                all_logs = device.adb("logcat", "-d", check=False)
                import re
                diagnostic = "\n".join(line for line in all_logs.splitlines() if re.search(
                    r'GGUFChatNative|GGUFNativeStderr|GGUF_REPAIR|Fatal signal|FATAL EXCEPTION|Abort message:|F DEBUG|Process com\.ggufchat\.app.*has died', line))
                (args.evidence / "vulkan-crash-diagnostic.txt").write_text(diagnostic)
            device.capture("vulkan-reply.png")
            offloaded = vulkan_offloaded(vk_log)
            result["checks"]["vulkan_offload"] = "PASS" if offloaded else "NOT_CONFIRMED: CPU fallback or unavailable Vulkan"
            (args.evidence / "vulkan-backend.txt").write_text("\n".join(
                line for line in vk_log.splitlines() if any(t in line.lower() for t in ("vulkan", "offload", "backend", "gguf_repair"))))
            if not offloaded:
                raise AssertionError("Vulkan não comprovado: requer backend Vulkan inicializado e camadas offloaded > 0; fallback CPU não passa")
            result["status"] = "PASS"
            return
        device.generate(model, 0, "cpu")
        result["checks"]["cpu_generation"] = "PASS"
        device.capture("cpu-reply.png")
        if args.generation_only:
            device.generate(model, 0, "cpu-second", prompt="Reply in English: What is two plus two?")
            result["checks"]["cpu_second_generation"] = "PASS: novo processo e nova conversa"
            device.capture("cpu-second-reply.png")
            try:
                basic_response_quality((args.evidence / "cpu-reply.txt").read_text(),
                                       (args.evidence / "cpu-second-reply.txt").read_text())
            except AssertionError as exc:
                result["checks"]["basic_relevance"] = "FAIL: " + str(exc)
                raise
            result["checks"]["basic_relevance"] = "PASS: verificação básica, não benchmark"
            result["status"] = "PASS"
            return
        vk_log = device.generate(model, -1, "vulkan")
        offloaded = gpu_offloaded(vk_log)
        result["checks"]["vulkan"] = "PASS: GPU offload confirmado" if offloaded else "CPU_FALLBACK: GPU não comprovada"
        if args.require_vulkan and not offloaded:
            raise AssertionError("Vulkan exigido, mas nenhuma camada foi comprovadamente enviada à GPU")
        # Exercise a real error path by deleting this test-only imported model.
        device.new_chat(model, 0)
        device.shell("rm " + shlex.quote(model["path"]))
        device.send("Teste")
        device.wait(lambda: "Arquivo GGUF ausente" in device.shell("dumpsys notification --noredact"),
                    "erro tratado de arquivo ausente", timeout=30)
        device.alive()
        result["checks"]["missing_model"] = "PASS: erro tratado e processo vivo"
        result["status"] = "PASS"
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        # Evidence collection never masks the original failure or turns FAIL into PASS.
        for name, command in (("final-logcat.txt", ("logcat", "-d")),
                              ("final-activities.txt", ("shell", "dumpsys activity activities"))):
            try:
                (args.evidence / name).write_text(device.adb(*command, check=False))
            except Exception as exc:
                result.setdefault("diagnostic_errors", []).append(str(exc))
        try:
            device.capture("final-screen.png")
        except Exception as exc:
            result.setdefault("diagnostic_errors", []).append(str(exc))
        (args.evidence / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
