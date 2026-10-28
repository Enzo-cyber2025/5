@echo off
REM ============================================================
REM  Gera o executável Windows do RaceAI 2D (PyInstaller)
REM  Requer Python 3.11 64-bit.
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/5] preparando ambiente...
if not exist ".venv-build" python -m venv .venv-build
call .venv-build\Scripts\activate.bat

echo [2/5] instalando PyTorch 2.4.1 (CPU) + DirectML...
python -m pip install --upgrade pip
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
pip install --no-deps torch-directml==0.2.5.dev240914
pip install -r requirements-build.txt

echo [3/5] verificando backends...
python -c "import torch; print('torch', torch.__version__)" || goto :erro
python -c "import torch_directml; print('DirectML:', torch_directml.device_name(0))" || echo "(DirectML indisponivel - seguindo sem GPU)"

echo [4/5] testes...
python tests/run_tests.py || goto :erro

echo [5/5] gerando executavel...
pyinstaller raceai.spec --noconfirm --clean || goto :erro

echo.
echo Pronto: dist\RaceAI2D\RaceAI2D.exe
echo Para testar sem abrir janela: dist\RaceAI2D\RaceAI2D-console.exe --selftest
goto :fim

:erro
echo FALHA no build (codigo %errorlevel%)

:fim
endlocal
pause
