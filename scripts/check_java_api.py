#!/usr/bin/env python3
"""Local API gate: no javac in this sandbox, so this is the next best thing.

The hosted CI compiles every helper with the real javac; here we only have a
JRE. Two CI rounds were spent on a single misspelled/nonexistent Android API
(`GradientDrawable.getStrokeWidth()`), which a compiler catches instantly.

This script parses every `apk-fix/java/**/*.java` with javalang, collects the
method names that are actually called, and checks each one against:
  * every member name declared in `android.jar` (constant-pool UTF8 strings of
    the platform classes, read straight from the jar);
  * the app classes decoded from the base APK;
  * the helper sources themselves (their own methods and inherited members).

A name found nowhere is reported as a probable compile error. It is a heuristic
(no type inference), so it is a smoke alarm, not a replacement for javac.
"""
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'apk-fix/java'
ANDROID_JAR = ROOT / '.cache/android-platforms/android-33/android.jar'
DECODED = ROOT / '.cache/original-decoded/smali'
UTF8 = re.compile(rb'[\x20-\x7e]{3,}', re.A)


def jar_member_names(jar):
    names = set()
    with zipfile.ZipFile(jar) as archive:
        for entry in archive.namelist():
            if not entry.endswith('.class'):
                continue
            for token in UTF8.findall(archive.read(entry)):
                text = token.decode('ascii', 'ignore')
                # Method names, field names and descriptors all live in the pool.
                for piece in re.split(r'[();\[\]/]', text):
                    if piece and piece.isidentifier():
                        names.add(piece)
    return names


def smali_member_names(root):
    names = set()
    if not root.is_dir():
        return names
    for path in root.rglob('*.smali'):
        for line in path.read_text(errors='ignore').splitlines():
            line = line.strip()
            if line.startswith('.method'):
                match = re.search(r'([A-Za-z0-9_$<>]+)\(', line)
                if match:
                    names.add(match.group(1))
            elif line.startswith('.field'):
                match = re.search(r'([A-Za-z0-9_$]+):', line)
                if match:
                    names.add(match.group(1))
    return names


def called_members(sources):
    sys.path.insert(0, str(ROOT / '.venv/lib/python3.11/site-packages'))
    import javalang
    calls = {}
    for path in sources:
        tree = javalang.parse.parse(path.read_text())
        for _, node in tree.filter(javalang.tree.MethodInvocation):
            calls.setdefault(node.member, set()).add(path.name)
    return calls


def main():
    jar = sys.argv[1] if len(sys.argv) > 1 else ANDROID_JAR
    sources = sorted(SOURCES.rglob('*.java'))
    if not sources:
        raise SystemExit('nenhuma fonte Java encontrada')
    known = jar_member_names(Path(jar)) | smali_member_names(DECODED)
    calls = called_members(sources)
    known |= set(calls)  # os próprios helpers chamam uns aos outros
    known |= {'toString', 'equals', 'hashCode', 'length', 'append', 'get', 'size',
              'put', 'add', 'remove', 'contains', 'isEmpty', 'valueOf', 'values',
              'name', 'ordinal', 'run', 'call', 'invoke', 'apply', 'iterator'}
    missing = {name: files for name, files in calls.items() if name not in known}
    print(f'fontes: {len(sources)} | chamadas distintas: {len(calls)} | membros conhecidos: {len(known)}')
    for name, files in sorted(missing.items()):
        print(f'PROVÁVEL ERRO: {name}() em {", ".join(sorted(files))}')
    if missing:
        raise SystemExit(f'{len(missing)} nome(s) sem nenhuma declaração conhecida')
    print('nenhum nome desconhecido chamado pelas fontes')


if __name__ == '__main__':
    main()
