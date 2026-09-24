#!/usr/bin/env python3
"""Compila os ajudantes Java com o javac de verdade, quando ele existe neste host.

O CI compila tudo no `build_mobile.py`; aqui a ideia é descobrir antes da fila que
um arquivo novo não compila (foi assim que rodadas passadas foram gastas). Onde
não há javac nem `android.jar`, o script diz SKIP e sai 0 — falta de material não
é falha de código.

Uso: python3 scripts/check_java_compile.py [--android <jar>]
Variáveis: JAVAC, JAVA_HOME (o javac de $JAVA_HOME/bin é usado se existir).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'apk-fix/java'
DEFAULT_JARS = [ROOT / '.cache/android-platforms/android-33/android.jar',
                ROOT / '.cache/android-platforms/android-35/android.jar',
                Path(os.environ.get('ANDROID_HOME', '/nonexistent')) / 'platforms/android-35/android.jar']


def find_javac():
    explicit = os.environ.get('JAVAC')
    if explicit and Path(explicit).is_file():
        return explicit
    from_path = shutil.which('javac')
    if from_path:
        return from_path
    home = os.environ.get('JAVA_HOME')
    if home and (Path(home) / 'bin/javac').is_file():
        return str(Path(home) / 'bin/javac')
    return None


def document_jars():
    """Jarras de anexos (PDF/DOCX) já baixadas, se estiverem em cache."""
    cached = sorted((ROOT / '.cache/document-libs').glob('*.jar'))
    return [jar for jar in cached if jar.name != 'pdfbox.jar']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android', type=Path, help='android.jar do SDK')
    arguments = parser.parse_args()
    javac = find_javac()
    if not javac:
        print('SKIP: nenhum javac neste host')
        return 0
    if arguments.android:
        android = arguments.android
    else:
        android = next((jar for jar in DEFAULT_JARS if jar.is_file()), None)
    if android is None:
        print('SKIP: android.jar não encontrado (.cache/android-platforms)')
        return 0
    sources = sorted(SOURCES.rglob('*.java'))
    if not sources:
        print('SKIP: nenhum fonte em apk-fix/java')
        return 0
    classpath = [str(android)] + [str(jar) for jar in document_jars()]
    with tempfile.TemporaryDirectory() as work:
        command = [javac, '--release', '8', '-classpath', os.pathsep.join(classpath),
                   '-d', work, *map(str, sources)]
        result = subprocess.run(command, capture_output=True, text=True)
        errors = [line for line in result.stderr.splitlines() if ': error:' in line]
        for line in errors[:40]:
            print(line)
        if result.returncode:
            print(f'FALHA: {len(errors)} erro(s) de compilação em {len(sources)} arquivo(s)')
            return 1
    print(f'java: compila ({len(sources)} arquivos, --release 8, javac={javac})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
