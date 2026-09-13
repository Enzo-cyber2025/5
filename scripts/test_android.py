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
import xml.etree.ElementTree as ET

from android_checks import (PACKAGE, PICKERS, assistant_reply, fusion, generation_completed,
                            gpu_offloaded, has_package, imported, position)


class Android:
    def __init__(self, serial, evidence):
        self.serial, self.evidence = serial, evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.last_ui_summary = None

    def adb(self, *args, check=True, timeout=45, binary=False):
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
        output = self.adb("exec-out", "cat", f"/data/user/0/{PACKAGE}/files/{name}", check=not optional)
        if optional and not output:
            return []
        return json.loads(output)

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

    def new_chat(self, model, gpu_layers):
        self.shell(f"am force-stop {PACKAGE}")
        prefs = ET.Element("map")
        for name, value in (("selectedModelId", model["id"]), ("selectedModelName", model["name"]),
                            ("selectedModelPath", model["path"])):
            ET.SubElement(prefs, "string", name=name).text = value
        for name, value in (("gpuLayers", gpu_layers), ("contextSize", 1024), ("nThreads", 2)):
            ET.SubElement(prefs, "int", name=name, value=str(value))
        self.write_private("shared_prefs/ggufchat_settings.xml", ET.tostring(prefs, encoding="unicode"))
        before = {c["id"] for c in self.read_json("chats.json", optional=True)}
        self.launch()
        self.tap(text="Nova conversa", package={PACKAGE}, contains=True)

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
                c.update(nPredict=16, contextSize=1024, gpuLayers=gpu_layers, webSearch=False)
                c["title"] = "GGUF regression " + chat["id"]
                chat = c
        self.write_private("files/chats.json", json.dumps(chats))
        self.launch()
        self.tap(text=chat["title"], package={PACKAGE}, contains=True)
        self.wait(lambda: position(self.ui(), class_name="android.widget.EditText", package={PACKAGE}), "tela da conversa")
        return chat

    def send(self, prompt):
        self.adb("logcat", "-c")
        self.tap(class_name="android.widget.EditText", package={PACKAGE})
        self.shell("input text " + shlex.quote(prompt.replace(" ", "%s")))
        self.tap(text="Enviar", package={PACKAGE}, contains=True)

    def generate(self, model, gpu_layers, stage):
        chat = self.new_chat(model, gpu_layers)
        pid = self.alive()
        prompt = "Ola"
        self.send(prompt)

        def completed():
            self.alive()
            log = self.adb("logcat", "-d", f"--pid={pid}")
            (self.evidence / f"{stage}-logcat.txt").write_text(log)
            if not generation_completed(log):
                return None
            chats = self.read_json("chats.json")
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
    result = {"status": "FAIL", "checks": {}, "apk_sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest()}
    try:
        if device.shell("getprop ro.kernel.qemu") != "1":
            raise AssertionError("O dispositivo não é um emulador")
        device.adb("root")
        device.adb("wait-for-device", timeout=60)
        if device.shell("id -u") != "0":
            raise AssertionError("É necessário emulador com adb root, não imagem Play Store")
        result["checks"]["emulator"] = "BOOTED: " + device.shell("getprop ro.product.cpu.abi")
        device.adb("install", "-r", "-g", args.apk, timeout=120)
        result["checks"]["installation"] = "PASS"
        if device.shell(f"pm clear {PACKAGE}") != "Success":
            raise AssertionError("Falha ao limpar dados do emulador")
        device.shell("mkdir -p /sdcard/Download")
        device.launch()
        result["checks"]["launch"] = "PASS"
        device.capture("launch.png")
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
        device.generate(model, 0, "cpu")
        result["checks"]["cpu_generation"] = "PASS"
        device.capture("cpu-reply.png")
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
