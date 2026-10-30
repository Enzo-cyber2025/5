# RaceAI 2D (C++) — build simples com g++/MinGW (sem cmake).
#
#   make            compila tudo (treinador, testes e, no Windows, o jogo)
#   make test       roda a suíte de testes
#   make game       compila o jogo com interface (somente Windows)
#   make check-win  checa tipos/sintaxe da interface Win32 (usando um shim)
#   make clean      limpa
CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -pthread
CORE     := src/core/*.cpp
APP      := src/app/app_state.cpp src/app/conteudo.cpp
CLI      := tools/train_cli.cpp
BIN      := build

# Detecção da plataforma por `uname` (mais confiável que $(OS) no MSYS2).
UNAME_S := $(shell uname -s 2>/dev/null)
ifneq (,$(findstring MINGW,$(UNAME_S)))
  PLAT    := windows
  EXE     := .exe
  LIBS    := -lgdi32 -luser32 -lcomctl32 -lcomdlg32
  GAME    := $(BIN)/raceai.exe
  TESTLIBS:= $(LIBS)
else ifneq (,$(findstring MSYS,$(UNAME_S)))
  PLAT    := windows
  EXE     := .exe
  LIBS    := -lgdi32 -luser32 -lcomctl32 -lcomdlg32
  GAME    := $(BIN)/raceai.exe
  TESTLIBS:= $(LIBS)
else
  PLAT    := unix
  EXE     :=
  LIBS    := -ldl
  GAME    :=
  TESTLIBS:= -ldl
endif

# O .exe precisa abrir em qualquer Windows: nada de depender de DLL do MinGW
# (libgcc_s_seh-1.dll, libstdc++-6.dll, libwinpthread-1.dll). Ligando tudo
# estaticamente o executável fica autossuficiente de verdade.
STATIC   := -static -static-libgcc -static-libstdc++

STUB     := $(BIN)/libstubpython.so
# variante que devolve None em vez de nullptr (igual ao CPython de verdade)
STUBNONE := $(BIN)/libstubpython_none.so

all: $(BIN)/raceai_train$(EXE) $(BIN)/raceai_tests$(EXE) $(BIN)/raceai_tests_app$(EXE) \
     $(BIN)/raceai_integrado$(EXE) $(BIN)/raceai_pytest$(EXE) $(GAME)

# ------------------------------------------------------------------ binários
$(BIN)/raceai_train$(EXE): tools/train_cli.cpp $(CORE)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) tools/train_cli.cpp $(CORE) -o $@ $(LIBS)

$(BIN)/raceai_tests$(EXE): tests/test_core.cpp $(CORE)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) -DRACEAI_WITH_PYTHON tests/test_core.cpp $(CORE) -o $@ $(TESTLIBS)

$(BIN)/raceai_tests_app$(EXE): tests/test_app.cpp $(CORE) $(APP)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) -DRACEAI_WITH_PYTHON tests/test_app.cpp $(CORE) $(APP) -o $@ $(TESTLIBS)

$(BIN)/raceai_integrado$(EXE): tests/test_integrado.cpp $(CORE) $(APP)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) -DRACEAI_WITH_PYTHON tests/test_integrado.cpp $(CORE) $(APP) -o $@ $(TESTLIBS)

$(BIN)/raceai_pytest$(EXE): tools/py_selftest.cpp $(CORE) $(APP)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) tools/py_selftest.cpp $(CORE) $(APP) -o $@ $(LIBS)

# empacotador: grava pistas/carros/modelos/python dentro do próprio .exe
$(BIN)/empacotar$(EXE): tools/empacotar.cpp src/app/conteudo.cpp
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) -Isrc tools/empacotar.cpp src/app/conteudo.cpp -o $@

# jogo com interface (Win32 + GDI): nada de bibliotecas externas
# (-Isrc: a interface inclui <core/...> pelo caminho completo)
# O -DRACEAI_SEM_MAIN tira o main() do treinador: o jogo chama o mesmo código
# quando é iniciado com argumentos (um executável só, dois modos).
$(BIN)/raceai.exe: src/app/main.cpp $(CORE) $(APP) $(CLI) $(BIN)/empacotar$(EXE)
	@mkdir -p $(BIN)
	$(CXX) $(CXXFLAGS) -Isrc -mwindows -DRACEAI_SEM_MAIN $(STATIC) src/app/main.cpp $(CORE) $(APP) $(CLI) -o $@ $(LIBS)
	@./$(BIN)/empacotar$(EXE) $@ assets modelos python || echo "aviso: sem conteudo para embutir" 

game: $(GAME)

# ------------------------------------------------------------------ testes
$(STUB): tests/stub_python.cpp
	@mkdir -p $(BIN)
	$(CXX) -std=c++17 -O2 -fPIC -shared tests/stub_python.cpp -o $@

$(STUBNONE): tests/stub_python.cpp
	@mkdir -p $(BIN)
	$(CXX) -std=c++17 -O2 -fPIC -shared -DSTUB_PYTHON_NONE tests/stub_python.cpp -o $@

test: $(BIN)/raceai_tests$(EXE) $(BIN)/raceai_tests_app$(EXE) $(BIN)/raceai_integrado$(EXE)
	./$(BIN)/raceai_tests$(EXE)
	./$(BIN)/raceai_tests_app$(EXE)
	./$(BIN)/raceai_integrado$(EXE)

# mesmo que `test`, mas usando o stub do CPython para exercitar a ponte Python
test-py: $(STUB) $(STUBNONE)
	RACEAI_STUB_PYTHON=./$(STUB) ./$(BIN)/raceai_tests$(EXE)
	RACEAI_STUB_PYTHON=./$(STUB) ./$(BIN)/raceai_tests_app$(EXE)
	RACEAI_STUB_PYTHON=./$(STUB) ./$(BIN)/raceai_integrado$(EXE)
	@echo "--- agora com o stub que devolve None (igual ao CPython) ---"
	RACEAI_STUB_PYTHON=./$(STUBNONE) ./$(BIN)/raceai_tests$(EXE)
	RACEAI_STUB_PYTHON=./$(STUBNONE) ./$(BIN)/raceai_tests_app$(EXE)
	RACEAI_STUB_PYTHON=./$(STUBNONE) ./$(BIN)/raceai_integrado$(EXE)

# prova que o CPython de verdade funciona (Windows: python/python311.dll)
test-python-real: $(BIN)/raceai_pytest$(EXE)
	./$(BIN)/raceai_pytest$(EXE)

check-win:
	$(CXX) -std=c++17 -fsyntax-only -Wall -Wextra -Itests/winshim -Isrc src/app/main.cpp
	@echo "interface Win32: tipos e sintaxe ok"

clean:
	rm -rf $(BIN)

.PHONY: all test test-py test-python-real check-win game clean
