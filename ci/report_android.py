#!/usr/bin/env python3
"""Expose small Android reports via annotations (some API clients truncate at 4 KB)."""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def emit(title, text):
    # Multiple small messages are readable even through a 4096-character API cap.
    for i, start in enumerate(range(0, max(1, len(text)), 2800), 1):
        chunk = text[start:start + 2800].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::notice title=GGUF {title} {i}::{chunk}', flush=True)


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else 'evidence')
    summary = root / 'summary.json'
    emit('Android summary', summary.read_text() if summary.exists() else 'No Android summary produced')
    dumps = sorted(root.glob('ui-*.xml'))
    if dumps:
        nodes = ET.parse(dumps[-1]).iter('node')
        data = [{k: n.get(k) for k in ('text', 'content-desc', 'bounds', 'enabled')}
                for n in nodes if n.get('text') or n.get('content-desc')]
        emit('last UI', json.dumps(data, ensure_ascii=False))
    for p in sorted(root.glob('*-reply.txt')):
        emit(p.name, p.read_text()[:2800])
    commands = root / 'commands.log'
    if commands.exists():
        inputs = [x for x in commands.read_text(errors='replace').splitlines() if x.startswith('$ adb shell input')]
        emit('input commands', '\n'.join(inputs)[-5600:])
    # Keep the real abort + native stack before verbose capability JSON/system
    # task logs consume GitHub's per-step annotation quota.
    for name in ('runtime-regression.json', 'vulkan-crash-diagnostic.txt', 'vulkan-backend.txt', 'vulkan-capabilities.json'):
        p = root / name
        if p.exists():
            text = p.read_text(errors='replace')
            if 'crash' in name:
                text = '\n'.join(x for x in text.splitlines() if re.search(
                    r'Vulkan|vulkan|Fatal signal|Abort message:|F DEBUG|GGUF_REPAIR|GGUFChatNative', x))
                text = text[-8400:]
            if text.strip():
                emit(name, text[:8400])
    log = root / 'final-logcat.txt'
    if log.exists():
        lines = [line for line in log.read_text(errors='replace').splitlines()
                 if re.search(r'GGUFPairing|[EFW] AndroidRuntime|GGUFChatNative|GGUFNativeStderr|GGUF_REPAIR|FATAL EXCEPTION|Fatal signal|Abort message:|F DEBUG', line)]
        emit('app logcat', '\n'.join(lines[-45:])[-8000:])


if __name__ == '__main__':
    main()
