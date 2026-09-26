#!/usr/bin/env python3
"""Strict, destructive integration suite for a DISPOSABLE rooted Android emulator.

Requires a real text GGUF supplied via --model; there is no fake-model fallback.
Optional --vision/--mmproj verifies SAF import and link persistence, not image inference.
Every critical command/assertion fails the run; diagnostics are always retained.
"""
import argparse
import hashlib
import os
import json
import re
from pathlib import Path
import shlex
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET

from android_checks import (PACKAGE, PICKERS, assistant_reply, fusion, generation_completed,
                            gpu_offloaded, has_package, imported, position, basic_response_quality, vulkan_offloaded,
                            generation_stats, ui_first_text_s, software_vulkan_refused, cpu_threads,
                            warmup_state, search_timing, search_panel, context_tuning)


class Android:
    def __init__(self, serial, evidence):
        self.serial, self.evidence = serial, evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.perf = {}
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
        # uiautomator pode responder sucesso sem produzir dump enquanto a janela
        # troca (DocumentsUI, transições de atividade): nesse caso o XML chega
        # vazio. Um dump vazio é repetido — nunca reaproveitado como se fosse a
        # tela atual, e nunca confundido com falha do aplicativo.
        for attempt in range(3):
            xml = self._ui_dump()
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                if attempt == 2:
                    raise
                self.alive()
                time.sleep(0.5)
                continue
            break
        summary = [{k: n.get(k) for k in ("text", "content-desc", "resource-id", "bounds", "enabled", "selected")}
                   for n in root.iter("node") if n.get("text") or n.get("content-desc")]
        if summary != self.last_ui_summary:
            print("UI " + json.dumps(summary, ensure_ascii=False), flush=True)
            self.last_ui_summary = summary
        self.counter += 1
        (self.evidence / f"ui-{self.counter:04d}.xml").write_text(xml)
        return xml

    def _ui_dump(self):
        # Never reuse a stale UI dump after a navigation/failed command.
        self.shell("rm -f /sdcard/gguf-test-ui.xml")
        self.shell("uiautomator dump /sdcard/gguf-test-ui.xml")
        return self.adb("exec-out", "cat", "/sdcard/gguf-test-ui.xml")

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
        # The drawer animates/populates asynchronously. A single lookup for each
        # spelling can miss Downloads just as it appears on the second lookup.
        # Use one observed snapshot and accept both framework/provider title IDs.
        def ready():
            xml = self.ui()
            if not any(position(xml, text=t, package=PICKERS) for t in ("Open from", "Abrir de")):
                return None
            for n in ET.fromstring(xml).iter("node"):
                rid = n.get("resource-id", "")
                if n.get("text", "").casefold() in ("downloads", "download") and rid.endswith("/title"):
                    point = position(xml, text=n.get("text"), resource_id=rid, package=PICKERS)
                    if point:
                        return point
            return None
        x, y = self.wait(ready, "Raiz Downloads visível no menu SAF", timeout=30)
        self.shell(f"input tap {x} {y}")

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
                if getattr(self,'progress_observer',None):self.progress_observer.poll()
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
        self.tap(text="Importar GGUF", package={PACKAGE}, contains=True)
        self.wait(lambda: has_package(self.ui(), PICKERS), "seletor de arquivos")
        self.choose_file(source.name)

        def completed():
            if getattr(self,'progress_observer',None):self.progress_observer.poll()
            self.alive()
            models = self.read_json("models.json", optional=True)
            try:
                return imported(models, source.name)
            except AssertionError:
                return None
        return self.wait(completed, f"importação persistida de {source.name}", timeout=300)

    def new_chat(self, model, gpu_layers, context_size=1024, threads=2, search=False):
        self.shell(f"am force-stop {PACKAGE}")
        prefs = ET.Element("map")
        for name, value in (("selectedModelId", model["id"]), ("selectedModelName", model["name"]),
                            ("selectedModelPath", model["path"])):
            ET.SubElement(prefs, "string", name=name).text = value
        for name, value in (("gpuLayers", gpu_layers), ("contextSize", context_size), ("nThreads", threads)):
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
                         gpuLayers=gpu_layers, webSearch=search, thinking=False)
                c["title"] = "GGUF regression " + chat["id"]
                chat = c
        self.write_private("files/chats.json", json.dumps(chats))
        self.launch()
        self.open_existing_chat(chat["title"])
        # Guarda a conversa desta etapa: generate() devolve o logcat, e os passos
        # seguintes precisam do id para conferir rótulo, persistência e painel.
        self.last_chat = chat
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

    @staticmethod
    def search_toggle_visible(xml):
        """O rótulo do botão de busca está na tela AGORA? (casamento exato)"""
        return bool(position(xml, text="Busca ON", package={PACKAGE})
                    or position(xml, text="Busca", package={PACKAGE}))

    def search_button_state(self):
        """Estado do botão de busca, com a gaveta de ferramentas aberta.

        Os controles da conversa (Busca, Raciocínio, foto, anexo, ferramentas) vivem
        numa gaveta recolhida, aberta pelo botão de ferramentas — é assim que o
        usuário chega neles. Sem abrir a gaveta o rótulo não está na tela, e isso não
        é defeito: é o desenho compacto da barra.
        """
        if not self.tools_open():
            return None
        xml = self.ui()
        if position(xml, text="Busca ON", package={PACKAGE}):
            return True
        if position(xml, text="Busca", package={PACKAGE}):
            return False
        return None

    def ping_ok(self):
        """A rede do emulador responde? Verificado de dentro do aparelho."""
        out = self.shell("ping -c 1 -W 2 8.8.8.8", check=False)
        return "1 received" in out or "1 packets received" in out

    def disable_network(self):
        """Derruba a rede do emulador e confirma; sem confirmação, não se afirma nada."""
        self.shell("cmd connectivity airplane-mode enable", check=False)
        self.shell("svc wifi disable", check=False)
        self.shell("svc data disable", check=False)
        for _ in range(15):
            if not self.ping_ok():
                return True
            time.sleep(1)
        return False

    def restore_network(self):
        self.shell("svc wifi enable", check=False)
        self.shell("svc data enable", check=False)
        self.shell("cmd connectivity airplane-mode disable", check=False)
        for _ in range(20):
            if self.ping_ok():
                return True
            time.sleep(1)
        return False

    def tools_open(self):
        """Garante a gaveta de ferramentas aberta e devolve se os controles apareceram."""
        xml = self.ui()
        if self.search_toggle_visible(xml):
            return True
        drawer = position(xml, desc="Alternar ferramentas", package={PACKAGE})
        if drawer is None:
            return False
        self.shell(f"input tap {drawer[0]} {drawer[1]}")
        self.wait(lambda: self.search_toggle_visible(self.ui()),
                  "gaveta de ferramentas aberta (botão 'Alternar ferramentas')", timeout=20)
        return True

    def toggle_search(self, desired):
        """Alterna a busca pelo botão real e confirma estado, rótulo e persistência."""
        current = self.search_button_state()
        if current is None:
            raise AssertionError("não foi possível abrir a gaveta de ferramentas")
        if current != desired:
            self.tap(text="Busca ON" if current else "Busca", package={PACKAGE})

        def persisted():
            chats = self.read_json("chats.json", optional=True) or []
            row = next((c for c in chats if c.get("id") == self.last_chat["id"]), None)
            if row is None:
                return None
            return True if row.get("webSearch") == desired else None

        self.wait(persisted, f"busca {'ligada' if desired else 'desligada'} e persistida", timeout=20)
        after = self.search_button_state()
        if after != desired:
            raise AssertionError(f"o rótulo do botão não acompanhou o estado: {after} != {desired}")
        return True

    def wait_for_load(self, timeout=120):
        """Espera o preload do modelo terminar (o nativo registra GGUF_UNIT_LOADED).

        As etapas de aquecimento esperam isso antes de enviar: o que elas medem é a
        espera do envio, não o carregamento — que já é medido nas outras etapas.
        """
        def ready():
            return 'GGUF_UNIT_LOADED' in self.adb("logcat", "-d", check=False) or None
        self.wait(ready, "modelo carregado antes do envio", timeout=timeout)

    def wait_for_warmup(self, timeout=20):
        """Espera o aquecimento de prefixo terminar, se ele estiver acontecendo."""
        def finished():
            log = self.adb("logcat", "-d", check=False)
            if 'GGUF_WARMUP ' in log or 'GGUF_WARMUP_SKIPPED' in log:
                return True
            return None
        try:
            self.wait(finished, "aquecimento de prefixo", timeout=timeout)
        except AssertionError:
            # Não é falha da etapa: o nativo registra o motivo (SKIPPED) quando não aquece.
            pass

    def send(self, prompt, clear_log=True, typed_pause=0.0):
        """Digita e envia.

        Com `typed_pause` o texto entra em duas passadas separadas por essa pausa,
        como um usuário que digita e hesita: é o cenário que permite ao aplicativo
        aquecer o prompt no tempo de digitação. Sem a pausa, é o envio direto.
        """
        if clear_log:
            self.adb("logcat", "-c")
        self.tap(class_name="android.widget.EditText", package={PACKAGE})
        words = prompt.split(" ")
        if typed_pause <= 0 or len(words) < 2:
            self.shell("input text " + shlex.quote(prompt.replace(" ", "%s")))
        else:
            half = max(1, len(words) // 2)
            self.shell("input text " + shlex.quote(" ".join(words[:half]).replace(" ", "%s")))
            time.sleep(typed_pause)
            self.shell("input text " + shlex.quote(" " + " ".join(words[half:]).replace(" ", "%s")))
        self.tap(text="Enviar", package={PACKAGE}, contains=True)

    def generate(self, model, gpu_layers, stage, prompt="Reply in English with a short greeting.",
                 threads=2, record=True, typed_pause=0.0, await_load=False, settle=0.0, search=False,
                 submit_timeout=30):
        # Keep model-loading/offload evidence: clearing at send loses the backend
        # selected by the preload worker. A new chat restarts the app; filter its PID.
        self.adb("logcat", "-c")
        chat = self.new_chat(model, gpu_layers, threads=threads, search=search)
        pid = self.alive()
        if await_load:
            self.wait_for_load()
            if typed_pause > 0:
                self.wait_for_warmup()
            if settle:
                time.sleep(settle)
        self.send(prompt, clear_log=False, typed_pause=typed_pause)
        def submitted():
            chats = self.read_json("chats.json")
            (self.evidence / f"{stage}-chats.json").write_text(json.dumps(chats, ensure_ascii=False))
            current = next(c for c in chats if c["id"] == chat["id"])
            return any(m.get("role") == "user" and m.get("content") == prompt
                       for m in current.get("messages", []))
        # Digitar é parte do envio: um prompt longo entra caractere a caractere pelo
        # `input text`, e 30 s fixos reprovavam o aplicativo por lentidão do teclado
        # do emulador (rodada 36245048939).
        self.wait(submitted, "prompt enviado e persistido pelo aplicativo", timeout=submit_timeout)

        def completed():
            if getattr(self,'progress_observer',None):self.progress_observer.poll()
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
            if record:
                self.record_perf(stage, log, gpu_layers, threads)
            return log
        return self.wait(completed, f"geração real {stage}", timeout=300)

    def prefill_metric(self, log):
        """Custo real do pré-preenchimento: ms por token que o backend processou.

        `prefill_ns` cobre só os tokens que NÃO vieram do aquecimento, então dividir
        pelo tamanho do prompt mentiria quando o prefixo foi reutilizado. A conta
        honesta é (prompt_tokens - reused_tokens).
        """
        rows = re.findall(r'GGUF_GENERATION_STATS tokens=\d+ decode_ns=\d+ prefill_ns=(\d+)'
                          r'[^\n]*prompt_tokens=(\d+) reused_tokens=(\d+)', log)
        if not rows:
            return None
        prefill_ns, prompt, reused = map(int, rows[-1])
        fresh = prompt - reused
        if fresh <= 0:
            return None
        return {'prompt_tokens': prompt, 'reused_tokens': reused, 'fresh_tokens': fresh,
                'prefill_s': round(prefill_ns / 1e9, 4),
                'prefill_ms_per_token': round(prefill_ns / 1e6 / fresh, 3)}

    def record_perf(self, stage, log, gpu_layers, threads):
        """Contadores nativos de UMA geração real, gravados como evidência.

        A taxa vem de tokens nativos e do tempo nativo de decodificação; o tempo
        até o primeiro texto vem do relógio da thread principal do Android. Nada
        é estimado a partir de caracteres, quadros ou contagem de callbacks.
        """
        stats = generation_stats(log) or {}
        # dict(stage, ...) tentava usar a string como sequência de pares e quebrava
        # a rodada inteira com "dictionary update sequence element #0 has length 1".
        entry = dict(stage=stage, gpu_layers_requested=gpu_layers, threads_requested=threads,
                     threads_resolved=cpu_threads(log),
                     backend='vulkan' if gpu_offloaded(log) else 'cpu',
                     ui_first_text_s=ui_first_text_s(log),
                     warmup=warmup_state(log),
                     prefill=self.prefill_metric(log),
                     context_tuning=context_tuning(log),
                     software_vulkan_notice=software_vulkan_refused(log), **stats)
        self.perf[stage] = entry
        (self.evidence / f"{stage}-perf.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        return entry


REGRESSION_TOLERANCE = 0.05


def gpu_experiments_enabled():
    """Etapas experimentais de GPU/aquecimento só rodam quando pedidas.

    Elas existem para medir o que este emulador consegue provar: o pedido de GPU
    com recusa explícita, o aquecimento de prefixo ligado e desligado na mesma
    rodada. Não alteram nenhum critério de aprovação do fluxo normal.
    """
    return os.environ.get('GGUF_EXPERIMENT_SUITE') == '1'


def performance_report(perf):
    """Compara a geração real entre configurações e declara o que foi medido.

    A linha de base é o comportamento anterior, medido nesta mesma execução:
    Vulkan por software aceito, 2 threads. A espera que o usuário sente é
    `ui_first_text_s` (envio até o primeiro texto desenhado na thread principal);
    o tempo de motor (`first_token_s`) fica ao lado como diagnóstico, porque não
    inclui a fila da interface.
    """
    report = {'scope': ('Medido no emulador descartável x86_64 com o modelo real do CI; '
                        'taxa = tokens nativos / tempo nativo de decodificação; '
                        'primeiro texto = relógio da thread principal do Android. '
                        'Cada etapa abre uma conversa nova, portanto a carga do modelo '
                        'entra no tempo de tela e nunca na taxa de decodificação. '
                        'A linha de base é o comportamento anterior, reproduzido pelo '
                        'opt-in de teste no driver Vulkan por software deste emulador.'),
              'baseline': 'vulkan',
              'interpretation': ('O pedido original dizia -300% de espera, o que não existe '
                                 '(um tempo negativo); o alvo aplicado é um terço do tempo '
                                 'anterior, ou seja 3x mais rápido até o primeiro texto.'),
              'stages': perf, 'candidates': {}}
    baseline = perf.get(report['baseline']) or {}
    base_rate = baseline.get('tokens_s')
    base_ui = baseline.get('ui_first_text_s')
    base_engine = baseline.get('first_token_s')
    if not base_rate:
        report['baseline_missing'] = ('A etapa de linha de base não produziu contadores; '
                                      'nenhum ganho pode ser declarado nesta rodada.')
    for name, entry in perf.items():
        # Uma chave que não seja uma etapa medida nunca derruba o relatório.
        if name == report['baseline'] or not isinstance(entry, dict) or not entry.get('tokens_s'):
            continue
        # As etapas de sub-lote medem o PRÉ-PREENCHIMENTO (prompt longo, aquecimento
        # desligado): a taxa de decodificação delas não é comparável à linha de base
        # de prompt curto e por isso não entram na conta de ganho/regressão. Elas
        # aparecem em `prefill_experiment`, com a conta que lhes pertence.
        if name.startswith('prefill-ubatch-'):
            continue
        rate = entry['tokens_s']
        ui = entry.get('ui_first_text_s')
        engine = entry.get('first_token_s')
        waited_before, waited_now = (base_ui, ui) if base_ui and ui else (base_engine, engine)
        report['candidates'][name] = {
            'tokens_s': rate,
            'throughput_gain_vs_baseline': round(rate / base_rate, 3) if base_rate else None,
            'ui_first_text_s': ui,
            'engine_first_token_s': engine,
            'wait_speedup_vs_baseline': (round(waited_before / waited_now, 3)
                                         if waited_before and waited_now else None),
            'waited_metric': 'ui_first_text_s' if base_ui and ui else 'engine_first_token_s',
            'targets': {'throughput_1_5x': bool(base_rate and rate / base_rate >= 1.5),
                        'first_text_3x': bool(waited_before and waited_now and waited_before / waited_now >= 3.0)},
            # Ruído entre etapas do mesmo emulador chega a poucos por cento: só uma
            # queda maior que a tolerância é tratada como regressão.
            'regression_vs_baseline': bool(base_rate and rate < base_rate * (1 - REGRESSION_TOLERANCE))}
    report['warmup_experiment'] = warmup_experiment(perf)
    report['prefill_experiment'] = prefill_experiment(perf)
    report['targets_met'] = sorted(name for name, c in report['candidates'].items()
                                   if all(c['targets'].values()))
    report['regressions'] = sorted(name for name, c in report['candidates'].items()
                                   if c['regression_vs_baseline'])
    report['regression_tolerance'] = REGRESSION_TOLERANCE
    report['environment'] = environment_limits(perf)
    return report


def prefill_experiment(perf):
    """Compara o custo do pré-preenchimento entre tamanhos de sub-lote.

    A métrica é ms por token que o backend realmente processou
    (`prefill_ns / (prompt_tokens - reused_tokens)`), medida com o aquecimento
    desligado e o MESMO texto nas duas etapas. Sem ganho medido, o padrão do
    aplicativo não muda — o experimento não vira promessa.
    """
    stages = []
    for name, entry in sorted(perf.items()):
        if not name.startswith('prefill-ubatch-') or not isinstance(entry, dict):
            continue
        prefill = entry.get('prefill') or {}
        if not prefill.get('prefill_ms_per_token'):
            continue
        stages.append({'stage': name,
                       'sub_batch': (entry.get('context_tuning') or {}).get('ubatch'),
                       **prefill})
    if len(stages) < 2:
        return {'status': 'NOT_MEASURED', 'stages': stages,
                'detail': 'faltou a métrica de pré-preenchimento em uma das etapas'}
    melhor = min(stages, key=lambda stage: stage['prefill_ms_per_token'])
    pior = max(stages, key=lambda stage: stage['prefill_ms_per_token'])
    ganho = round(pior['prefill_ms_per_token'] / melhor['prefill_ms_per_token'], 3)
    return {'status': 'MEDIDO', 'stages': stages, 'best': melhor['stage'],
            'gain_x': ganho,
            'detail': ('mesmo texto, aquecimento desligado nas duas etapas; '
                       f"{melhor['stage']} custou {melhor['prefill_ms_per_token']} ms por token "
                       f"pré-preenchido contra {pior['prefill_ms_per_token']} ms "
                       f"({ganho}x)")}


def warmup_experiment(perf):
    """O aquecimento de prefixo comparado consigo mesmo, na mesma rodada.

    Só entra no relatório o que foi medido nas etapas nomeadas abaixo: com o
    aquecimento desligado por propriedade de teste e com ele ligado, no mesmo
    aparelho, no mesmo modelo e na mesma configuração de envio. Sem as duas
    medições, o relatório diz que não há comparação — nunca estima.
    """
    off = perf.get('gpu-off-cold') or {}
    cold = perf.get('gpu-preferred-cold') or {}
    typed = perf.get('gpu-preferred-typed') or {}
    result = {'compared': False,
              'scope': ('Mesma rodada, mesmo emulador, mesmo modelo e mesmos tokens de '
                        'saída; a única diferença entre "off" e "cold" é o aquecimento '
                        'de prefixo ligado por propriedade de teste.')}
    if off.get('ui_first_text_s') and cold.get('ui_first_text_s'):
        result['compared'] = True
        result['wait_off_s'] = off['ui_first_text_s']
        result['wait_cold_s'] = cold['ui_first_text_s']
        result['wait_speedup_cold'] = round(off['ui_first_text_s'] / cold['ui_first_text_s'], 3)
        result['engine_wait_off_s'] = off.get('first_token_s')
        result['engine_wait_cold_s'] = cold.get('first_token_s')
        result['prefill_off_s'] = off.get('prefill_s')
        result['prefill_cold_s'] = cold.get('prefill_s')
        result['reused_tokens_off'] = off.get('reused_tokens')
        result['reused_tokens_cold'] = cold.get('reused_tokens')
    if typed.get('ui_first_text_s') and cold.get('ui_first_text_s'):
        result['wait_typed_s'] = typed['ui_first_text_s']
        result['wait_speedup_typed'] = round(cold['ui_first_text_s'] / typed['ui_first_text_s'], 3)
        result['warmup_typed'] = typed.get('warmup')
    result['comparator_note'] = ('As etapas de aquecimento esperam o modelo terminar de carregar '
                                 'antes de enviar, porque o que elas medem é a espera do envio. As '
                                 'demais etapas enviam assim que a conversa abre; por isso a '
                                 'comparação justa do aquecimento é contra gpu-off-cold, medido nas '
                                 'mesmas condições (mesma carga, mesma espera, mesma configuração).')
    result['warmup_cold'] = cold.get('warmup')
    result['warmup_off'] = off.get('warmup')
    return result


def environment_limits(perf):
    """O que o aparelho desta rodada não permite exigir.

    Um alvo de +50% de taxa e de um terço da espera não é avaliável num aparelho
    com pouquíssimos núcleos nem num backend que executa na própria CPU; exigir
    esse número ali reprovaria toda rodada sem informar nada. O que continua
    exigível é não regredir — e isso o relatório mede.
    """
    limits = []
    entries = [e for e in perf.values() if isinstance(e, dict) and e.get('tokens_s')]
    cores = {e['threads_resolved']['available'] for e in entries
             if isinstance(e.get('threads_resolved'), dict)}
    if cores and max(cores) <= 2:
        limits.append(f'aparelho com {max(cores)} núcleos: sem paralelismo para ganho de taxa')
    if any(e.get('software_vulkan_notice') for e in entries):
        limits.append('dispositivo Vulkan é um rasterizador por software; o caminho padrão já é a CPU')
    return {'limits': limits, 'targets_required': not limits}


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
        # O emulador só oferece um rasterizador Vulkan por software. Para provar
        # que o caminho Vulkan não regrediu, o teste liga o opt-in e reproduz o
        # comportamento anterior; sem o opt-in, a política padrão recusa esse
        # dispositivo e executa na CPU.
        device.shell("setprop debug.gguf.allow_software_vulkan 1")
        try:
            vk_log = device.generate(model, -1, "vulkan")
        finally:
            device.shell("setprop debug.gguf.allow_software_vulkan 0")
        offloaded = gpu_offloaded(vk_log)
        result["checks"]["vulkan"] = ("PASS: GPU offload confirmado (opt-in de teste para o driver por software)"
                                      if offloaded else "CPU_FALLBACK: GPU não comprovada")
        if args.require_vulkan and not offloaded:
            raise AssertionError("Vulkan exigido, mas nenhuma camada foi comprovadamente enviada à GPU")
        policy_log = device.generate(model, -1, "vulkan-policy-default")
        refused = software_vulkan_refused(policy_log)
        if not refused:
            raise AssertionError("Política padrão não declarou a recusa do Vulkan por software")
        result["checks"]["software_vulkan_policy"] = "PASS: dispositivo por software recusado -> CPU (" + refused + ")"
        # Busca na web de verdade, com o teto de tempo que o defeito exigiu.
        # 0) O botão da busca: parte de desligado (a conversa desta etapa), liga e
        #    desliga pelo toque real, conferindo rótulo e persistência nos dois
        #    sentidos.
        state = device.search_button_state()
        if state is None:
            raise AssertionError("não foi possível abrir a gaveta de ferramentas da conversa")
        if state is not False:
            raise AssertionError("a conversa desta etapa deveria estar com a busca desligada")
        device.toggle_search(True)
        device.toggle_search(False)
        result["checks"]["search_toggle"] = "PASS: liga, desliga e persiste com o rótulo acompanhando"
        # 1) Rede como o runner oferecer (com internet ou não): a resposta sai e o
        #    teto é respeitado.
        device.generate(model, 0, "search-online", search=True, await_load=True,
                        settle=5.0,
                        prompt="Reply in English: What is the capital of Brazil?")
        # generate() devolve o logcat; a conversa desta etapa fica em last_chat.
        online_chat_id = device.last_chat["id"]
        online_log = (args.evidence / "search-online-logcat.txt").read_text()
        online = search_timing(online_log)
        if not online:
            raise AssertionError("a busca não registrou orçamento (GGUF_SEARCH_BUDGET ausente)")
        allowance = online["budget_ms"] + 1500  # margem do relógio entre processos
        if online["used_ms"] > allowance:
            raise AssertionError(f"busca passou do teto: {online['used_ms']} ms > {online['budget_ms']} ms")
        if online["announced_budget_ms"] != online["budget_ms"]:
            raise AssertionError("o status não anunciou o mesmo teto aplicado na busca")
        if online["prompt_mode"] is None:
            raise AssertionError("o modelo não foi informado do resultado da busca")
        if not online["attempt_slices_within_budget"]:
            raise AssertionError("uma tentativa recebeu mais tempo do que o orçamento restante")
        chats = device.read_json("chats.json")
        panel = search_panel(chats, online_chat_id,
                             "Reply in English: What is the capital of Brazil?")
        panel_file = args.evidence / "search-online-panel.json"
        panel_file.write_text(json.dumps(panel, ensure_ascii=False, indent=2))
        if online["sources"]:
            if not panel or not panel.get("hits"):
                raise AssertionError("fontes encontradas, mas o painel de proveniência não as registrou")
            result["checks"]["search_online"] = (
                f"PASS: {online['provider']} com {online['sources']} fonte(s) em "
                f"{online['used_ms']} ms de {online['budget_ms']} ms, painel persistido")
        else:
            if not panel or not (panel.get("error") or "").strip():
                raise AssertionError("busca sem fontes precisa registrar o motivo no painel")
            if not online["exhausted"] and not online["error"]:
                raise AssertionError("busca terminou sem fontes, sem motivo declarado")
            result["checks"]["search_online"] = (
                f"PASS: sem fontes neste runner; resposta gerada mesmo assim em "
                f"{online['used_ms']} ms de {online['budget_ms']} ms, motivo no painel")
        # 2) O cenário do relato: aparelho SEM rede. A cadeia de provedores precisa
        #    parar na primeira falha (não tentar as quatro) e a resposta precisa sair
        #    de qualquer forma, com o motivo declarado ao usuário e ao modelo.
        network_down = device.disable_network()
        try:
            if not network_down:
                result["checks"]["search_offline"] = (
                    "SKIP: não foi possível derrubar a rede do emulador (ping ainda responde)")
            else:
                device.generate(model, 0, "search-offline", search=True, await_load=True,
                                settle=5.0,
                                prompt="Reply in English: What is the capital of France?")
                offline_chat_id = device.last_chat["id"]
                offline = search_timing((args.evidence / "search-offline-logcat.txt").read_text())
                if not offline:
                    raise AssertionError("a busca sem rede não registrou orçamento")
                if offline["used_ms"] > offline["budget_ms"] + 1500:
                    raise AssertionError(
                        f"busca sem rede passou do teto: {offline['used_ms']} ms > {offline['budget_ms']} ms")
                if len(offline["attempts"]) != 1:
                    raise AssertionError(
                        "falha de rede não interrompeu a cadeia: " + str(offline["attempts"]))
                if offline["sources"]:
                    raise AssertionError("sem rede, a busca não pode produzir fontes")
                offline_panel = search_panel(device.read_json("chats.json"), offline_chat_id,
                                             "Reply in English: What is the capital of France?")
                (args.evidence / "search-offline-panel.json").write_text(
                    json.dumps(offline_panel, ensure_ascii=False, indent=2))
                if not offline_panel or not (offline_panel.get("error") or "").strip():
                    raise AssertionError("busca sem rede precisa declarar a falha no painel")
                if offline["prompt_mode"] != "indisponivel":
                    raise AssertionError(
                        "sem fontes, o modelo precisa ser avisado de que a busca falhou: "
                        + str(offline["prompt_mode"]))
                result["checks"]["search_offline"] = (
                    f"PASS: sem rede, a cadeia parou na primeira tentativa "
                    f"({offline['provider']}) em {offline['used_ms']} ms, resposta gerada sem fontes")
        finally:
            if not device.restore_network():
                result["checks"]["network_restored"] = "AVISO: a rede do emulador não voltou ao normal"
        if gpu_experiments_enabled():
            # Preferência por GPU pedida pelo usuário (camadas 99 = modelo inteiro).
            # Neste emulador o dispositivo Vulkan é um rasterizador por software:
            # a política recusa a GPU e executa na CPU, e a rodada registra o
            # motivo. Onde houver GPU real (Adreno/Mali), este mesmo pedido é o
            # caminho executado — é o padrão de fábrica do aplicativo.
            device.generate(model, 99, "gpu-preferred-cold", await_load=True, settle=5.0)
            result["checks"]["gpu_preferred"] = ("PASS: pedido de GPU medido; "
                + ("offload real confirmado" if gpu_offloaded((args.evidence / "gpu-preferred-cold-logcat.txt").read_text())
                   else "recusa registrada e CPU usada (emulador sem GPU real)"))
            # Digitação com pausa: o aplicativo aquece o prompt enquanto o usuário escreve.
            device.generate(model, 99, "gpu-preferred-typed", typed_pause=1.2,
                            await_load=True, settle=5.0)
            # OFF na mesma rodada: aquecimento desligado por propriedade de teste.
            device.shell("setprop debug.gguf.disable_warmup 1")
            try:
                device.generate(model, 99, "gpu-off-cold", await_load=True, settle=5.0)
            finally:
                device.shell("setprop debug.gguf.disable_warmup 0")
            result["checks"]["prefix_warmup_experiment"] = (
                "PASS: aquecimento ligado e desligado medidos na mesma rodada"
                if (device.perf.get("gpu-off-cold", {}).get("ui_first_text_s")
                    and device.perf.get("gpu-preferred-cold", {}).get("ui_first_text_s"))
                else "NOT_MEASURED: falta uma das duas medições")
            # Sub-lote do pré-preenchimento: mesmo texto, mesmo contexto, mesma
            # quantidade de tokens — a única diferença é o tamanho do sub-lote. O
            # aquecimento fica desligado nas duas para que o número meça o
            # pré-preenchimento inteiro, e não o resto depois do prefixo.
            # Prompt longo o bastante para o pré-preenchimento ser medível, e curto o
            # bastante para o teclado do emulador digitar dentro do prazo (o prazo é
            # declarado abaixo, não escondido).
            long_prompt = "Summarize in English, one line. " + " ".join(
                f"item {n} of a list about local language models and their speed"
                for n in range(12))
            device.shell("setprop debug.gguf.disable_warmup 1")
            try:
                for stage, ubatch in (("prefill-ubatch-128", 128), ("prefill-ubatch-256", 256)):
                    device.shell(f"setprop debug.gguf.prefill_ubatch {ubatch}")
                    device.generate(model, 0, stage, prompt=long_prompt, await_load=True,
                                    submit_timeout=180)
            finally:
                device.shell("setprop debug.gguf.prefill_ubatch 0")
                device.shell("setprop debug.gguf.disable_warmup 0")
            small = device.perf.get("prefill-ubatch-128", {})
            large = device.perf.get("prefill-ubatch-256", {})
            first, second = small.get("prefill") or {}, large.get("prefill") or {}
            if first.get("prefill_ms_per_token") and second.get("prefill_ms_per_token"):
                result["checks"]["prefill_ubatch_experiment"] = (
                    f"MEDIDO: 128 → {first['prefill_ms_per_token']} ms/token "
                    f"({first['fresh_tokens']} tokens), 256 → {second['prefill_ms_per_token']} ms/token "
                    f"({second['fresh_tokens']} tokens); nada muda de padrão sem ganho medido")
            else:
                result["checks"]["prefill_ubatch_experiment"] = (
                    "NOT_MEASURED: falta a métrica de pré-preenchimento em uma das etapas")
        # Medição no mesmo emulador, mesmas entradas e mesmo limite de tokens.
        device.generate(model, 0, "cpu-threads-auto", threads=0)
        result["checks"]["cpu_auto_threads"] = "PASS: política automática de threads executada"
        perf = performance_report(device.perf)
        (args.evidence / "performance.json").write_text(json.dumps(perf, ensure_ascii=False, indent=2))
        result["performance"] = perf
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
