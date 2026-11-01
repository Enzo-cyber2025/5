#!/usr/bin/env python3
"""Real Android checks for live web search, zero sentinels, and an AI-proposed Termux command.
The Termux command is restricted to one exact, harmless marker write and is still
reviewed/confirmed in the app UI before the official Termux service receives it.
"""
import hashlib
import json
import os
import re
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

from test_mobile import MobileAndroid, APK
from test_inference_android import reply
from android_checks import PACKAGE, position

EVIDENCE = Path("evidence")
TEXT_MODEL = Path(".cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf")
TERMUX_APK = Path(os.environ.get("GGUF_TERMUX_TEST_APK", ".cache/termux-app-x86_64.apk"))
TERMUX_PACKAGE = "com.termux"
MARKER = "GGUF_TERMUX_HANDOFF_OK"
EXPECTED_COMMAND = "echo " + MARKER + " > /data/data/com.termux/files/home/gguftx-proof.txt"


def tool_row(d):
    root = ET.fromstring(d.ui())
    return next((n for n in root.iter("node")
                 if n.get("content-desc") == "Ferramentas da conversa"), None)


def tap_tool(d, label):
    for _ in range(8):
        xml = d.ui()
        point = position(xml, text=label, package={PACKAGE})
        if point:
            d.shell(f"input tap {point[0]} {point[1]}")
            return
        row = tool_row(d)
        if row is None:
            raise AssertionError("Linha de ferramentas não está aberta")
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", row.get("bounds", ""))
        if not match:
            raise AssertionError("Bounds da linha de ferramentas ausentes")
        left, top, right, bottom = map(int, match.groups())
        y = (top + bottom) // 2
        d.shell(f"input touchscreen swipe {right-12} {y} {left+12} {y} 350")
    raise AssertionError("Botão de ferramenta não ficou visível: " + label)


def set_termux_external_apps(d):
    d.adb("install", "-r", TERMUX_APK, timeout=180)
    d.shell("monkey -p com.termux 1", check=False)
    d.wait(lambda: d.shell("test -x /data/data/com.termux/files/usr/bin/bash && echo ready", check=False) == "ready",
           "bootstrap oficial do Termux pronto", timeout=300)
    uid = d.shell("stat -c %u /data/user/0/com.termux").strip()
    assert uid.isdigit(), "UID Termux ausente"
    prop = "/data/user/0/com.termux/files/home/.termux/termux.properties"
    d.shell("mkdir -p /data/user/0/com.termux/files/home/.termux")
    d.shell("printf 'allow-external-apps=true\\n' > " + prop)
    d.shell(f"chown -R {uid}:{uid} /data/user/0/com.termux/files/home/.termux && chmod 700 /data/user/0/com.termux/files/home/.termux && chmod 600 {prop} && restorecon -R /data/user/0/com.termux/files/home/.termux")
    d.shell("am force-stop com.termux")
    d.shell("monkey -p com.termux 1", check=False)
    d.wait(lambda: d.shell("test -x /data/data/com.termux/files/usr/bin/bash && echo ready", check=False) == "ready",
           "Termux reiniciado com allow-external-apps", timeout=60)
    assert d.shell("test -x /data/data/com.termux/files/usr/bin/bash && echo executable") == "executable"
    return uid


def test_web_search(d, model, chat):
    d.tap(desc="Alternar ferramentas", package={PACKAGE})
    tap_tool(d, "Busca")
    saved = next(c for c in d.read_json("chats.json") if c["id"] == chat["id"])
    assert saved.get("webSearch") is True, "Alternância de pesquisa web não persistiu no chat"
    d.tap(desc="Alternar ferramentas", package={PACKAGE})
    stages = []
    for stage, prompt in (
        # Android's `input text` shell command crashes on some non-ASCII characters.
        # Keep this Portuguese probe ASCII so the emulator tests search, not IME encoding.
        ("tool-search-pt", "Pesquise na web: qual a capital do Brasil? Traga uma fonte."),
        ("tool-search-en", "Search the web for the capital of Brazil and cite a source."),
    ):
        reply(d, chat, prompt, stage, timeout=240)
        log = d.adb("logcat", "-d")
        found = re.findall(r"GGUF_WEB_SEARCH status=ok results=([1-8])", log)
        citations = re.findall(r"GGUF_WEB_SEARCH_PROMPT citations=([1-8])", log)
        item = {"stage": stage, "prompt": prompt, "web_search_enabled": saved.get("webSearch"),
                "results": [int(x) for x in found], "prompt_citations": [int(x) for x in citations]}
        (EVIDENCE / f"{stage}-verification.json").write_text(json.dumps(item, ensure_ascii=False, indent=2))
        assert found and citations and int(found[-1]) > 0 and int(citations[-1]) > 0, \
            f"Pesquisa real sem resultados/citações: {stage}; veja logcat"
        stages.append(item)
    return stages


def request_permission_and_confirm(d):
    d.tap(desc="Alternar ferramentas", package={PACKAGE})
    tap_tool(d, "Termux")
    d.wait(lambda: position(d.ui(), text="Revisar comando do Termux", contains=True, package={PACKAGE}),
           "diálogo de revisão antes da execução")
    xml = d.ui()
    displayed_text = [node.get("text", "") for node in ET.fromstring(xml).iter("node")]
    assert EXPECTED_COMMAND in displayed_text, "Comando aprovado pelo modelo não foi exibido integralmente para revisão"
    d.capture("termux-command-review.png")
    d.tap(text="Abrir no Termux", package={PACKAGE})

    def permission_dialog():
        xml = d.ui()
        if "com.android.permissioncontroller" in xml or "permission" in xml.lower():
            for label in ("Allow", "While using the app", "Allow only while using the app", "Permitir"):
                point = position(xml, text=label, package=None, contains=True)
                if point:
                    return point
        return None

    point = d.wait(permission_dialog, "permissão Android RUN_COMMAND solicitada em runtime", timeout=25)
    d.shell(f"input tap {point[0]} {point[1]}")
    return d.wait(lambda: d.shell("pm check-permission com.termux.permission.RUN_COMMAND " + PACKAGE, check=False).strip() == "granted",
                  "permissão RUN_COMMAND concedida pelo usuário de teste", timeout=30)


def run_termux_handoff(d, model):
    chat = d.new_chat(model, 0, context_size=1024, threads=2)
    prompt = ("Return only one fenced bash code block, with exactly this harmless command and no other commands: "
              + EXPECTED_COMMAND)
    answer = reply(d, chat, prompt, "termux-ai-proposed-command", timeout=240)
    blocks = re.findall(r"```(?:bash|sh|shell)\s*\n(.*?)```", answer, flags=re.I | re.S)
    # The production bridge also supports one exact bare command from a compact
    # model, but never prose or multiline un-fenced text.
    selected = blocks[-1].strip() if blocks else answer.strip()
    assert selected == EXPECTED_COMMAND, "Comando do modelo diferente do sentinel inofensivo: " + repr(selected)
    latest = next(c for c in d.read_json("chats.json") if c["id"] == chat["id"])
    assert latest["messages"][-1]["role"] == "assistant" and latest["messages"][-1]["content"] == answer
    (EVIDENCE / "termux-ai-command.json").write_text(json.dumps({
        "model_sha256": hashlib.sha256(TEXT_MODEL.read_bytes()).hexdigest(),
        "chat_id": chat["id"], "prompt": prompt, "assistant_reply": answer,
        "selected_command": selected, "termux_apk_sha256": hashlib.sha256(TERMUX_APK.read_bytes()).hexdigest(),
        "termux_permission": "com.termux.permission.RUN_COMMAND", "confirmation_required": True,
    }, ensure_ascii=False, indent=2))
    request_permission_and_confirm(d)
    proof = "/data/data/com.termux/files/home/gguftx-proof.txt"
    d.wait(lambda: d.shell("cat " + proof, check=False).strip() == MARKER,
           "comando gerado pelo modelo executado no Termux real", timeout=60)
    (EVIDENCE / "termux-command-output.txt").write_text(d.shell("cat " + proof).strip() + "\n")
    d.capture("termux-command-completed.png")
    return {"status": "PASS", "permission": "granted at runtime", "command_source": "latest assistant message",
            "user_review_and_confirmation": True, "termux_package": TERMUX_PACKAGE, "output": MARKER}


def main():
    EVIDENCE.mkdir(exist_ok=True)
    summary = {"status": "FAIL", "scope": "live-web-search-model-proposed-termux-command-zero-context-and-output",
               "checks": {}, "environment": "Android emulator API 35; official Termux APK v0.118.3 x86_64"}
    d = MobileAndroid("emulator-5554", EVIDENCE)
    try:
        assert d.shell("getprop ro.kernel.qemu") == "1"
        d.adb("root", check=False); d.adb("wait-for-device", timeout=60)
        assert d.shell("id -u") == "0", "Root de teste do emulador indisponível"
        d.shell("wm size 720x1280"); d.shell("wm density 240")
        # The emulator's Pixel Launcher becomes unresponsive under native model
        # setup; every other physical-flow harness disables it before app launch.
        d.shell("pm disable-user --user 0 com.google.android.apps.nexuslauncher", check=False)
        # Exercise the app before Termux's first-run bootstrap stresses the launcher.
        d.adb("install", "-r", "-g", APK, timeout=180)
        assert d.shell("pm clear " + PACKAGE) == "Success"
        d.grant_test_notifications(); d.launch()
        model = d.provision_model(TEXT_MODEL)
        chat = d.new_chat(model, 0, context_size=1024, threads=2)
        summary["checks"]["live_web_search_en_and_pt"] = test_web_search(d, model, chat)

        # Exercise the literal zero values through the real preference/chat/JNI/native path.
        zero_chat = d.new_chat(model, 0, context_size=0, threads=2, n_predict=0)
        answer = reply(d, zero_chat, "Reply with only: OK", "zero-context-zero-output", timeout=240)
        chats = d.read_json("chats.json")
        saved = next(c for c in chats if c["id"] == zero_chat["id"])
        log = d.adb("logcat", "-d")
        budget = re.search(r"GGUF_OUTPUT_BUDGET requested=0 effective=([1-9][0-9]*) available_context=([1-9][0-9]*)", log)
        prompt = re.search(r"GGUF_PROMPT_CACHE input_tokens=([1-9][0-9]*)", log)
        assert saved.get("contextSize") == 0 and saved.get("nPredict") == 0
        assert budget and prompt, "Native zero-sentinel values not observed in a loaded real model"
        model_context = int(prompt.group(1)) + int(budget.group(2))
        assert int(budget.group(1)) == int(budget.group(2)), "Zero output did not use all remaining model context"
        summary["checks"]["zero_uses_model_context_and_remaining_output_budget"] = {
            "status": "PASS", "context_setting": 0, "output_setting": 0,
            "model_context_loaded": model_context, "prompt_tokens": int(prompt.group(1)),
            "output_budget": int(budget.group(1)), "available_context": int(budget.group(2)),
            "answer": answer, "meaning": "maximum finite model context, not infinity",
        }

        # Install/bootstrap Termux only after the web and zero-sentinel checks,
        # so a launcher issue cannot erase evidence for checks already completed.
        summary["checks"]["termux_official_apk_bootstrapped"] = {
            "status": "PASS", "package": TERMUX_PACKAGE, "uid": set_termux_external_apps(d)
        }
        # Fresh text-only chat; model must author the harmless shell command.
        d.shell("pm revoke " + PACKAGE + " com.termux.permission.RUN_COMMAND", check=False)
        termux = run_termux_handoff(d, model)
        summary["checks"]["model_proposed_command_confirmed_and_executed_in_official_termux"] = termux
        summary["status"] = "PASS"
    except Exception as ex:
        summary["error"] = str(ex)
        (EVIDENCE / "tool-integrations-failure.txt").write_text(traceback.format_exc())
        traceback.print_exc()
    finally:
        (EVIDENCE / "tool-integrations-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if summary["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
