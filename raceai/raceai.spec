# -*- mode: python ; coding: utf-8 -*-
"""Especificação do PyInstaller para o RaceAI 2D.

Uso:  pyinstaller raceai.spec --noconfirm --clean
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

datas = [
    ("assets", "assets"),
    ("README.md", "."),
    ("MODS.md", "."),
]
if os.path.isdir("mods"):
    datas.append(("mods", "mods"))
if not os.path.isdir("modelos"):
    os.makedirs("modelos", exist_ok=True)
datas.append(("modelos", "modelos"))

hiddenimports = [
    "numpy",
    "pygame",
    "raceai",
    "raceai.app",
    "raceai.trainer",
    "raceai.autopilot",
    "raceai.ai.backend",
    "raceai.ai.ga",
    "raceai.ai.policy",
    "raceai.ai.model_io",
    "raceai.mods",
    "raceai.render",
    "raceai.ui",
    "torch",
    "torch_directml",
]

try:                                    # DLLs do torch (Windows)
    datas += collect_dynamic_libs("torch")
    datas += collect_data_files("torch", include_py_files=False)
except Exception:
    pass
try:
    datas += collect_dynamic_libs("torch_directml")
except Exception:
    pass

excludes = [
    "matplotlib", "scipy", "PIL", "tkinter", "notebook", "IPython",
    "pytest", "setuptools._distutils", "torchvision", "torchaudio",
    "torch._dynamo", "torch._inductor", "torch.distributions",
    "torch.testing", "torch.onnx._internal", "triton",
]

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RaceAI2D",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # janela gráfica; use --console para depurar
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.isfile("assets/icon.ico") else None,
)

# Segundo executável, com console: serve para depurar e para o CI
# (o de janela não mostra print()).
exe_console = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RaceAI2D-console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.isfile("assets/icon.ico") else None,
)

coll = COLLECT(
    exe,
    exe_console,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RaceAI2D",
)
