#!/usr/bin/env bash
# Build para Linux/macOS (sem DirectML): gera um executável CPU.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv-build 2>/dev/null || true
source .venv-build/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements-build.txt
python tests/run_tests.py
pyinstaller raceai.spec --noconfirm --clean
echo "Pronto: dist/RaceAI2D/RaceAI2D"
