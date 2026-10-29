#!/usr/bin/env python3
# gerar_modelos_teste.py — cria arquivos de modelo em vários formatos para os
# testes do carregador universal. Roda em Python puro: **não precisa de torch
# nem de numpy** (é justamente a graça: aqui nós produzimos, à mão, um .pt com
# a mesma cara do que o torch.save gera).
#
#   python tests/gerar_modelos_teste.py
#
# Gera em tests/modelos_teste/:
#   rede.pt            formato do PyTorch (zip + pickle + storages)
#   rede_comprimida.pt o mesmo, mas com os registros comprimidos (deflate)
#   rede.npz           formato do NumPy
#   rede.safetensors   formato safetensors
#   rede.json          formato do próprio jogo
#   nao_e_rede.bin     bytes aleatórios (tem que ser recusado)
#   nao_e_rede.txt     texto (tem que ser recusado)
import json
import os
import struct
import sys
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "modelos_teste")

# rede 24 -> 8 -> 8 -> 2, com valores reconhecíveis (para o teste conferir)
DIMS = [24, 8, 8, 2]


def pesos_da_rede():
    """Pesos no layout do jogo: por camada, matriz (linha = saída) e bias."""
    pesos = []
    for l in range(len(DIMS) - 1):
        n_in, n_out = DIMS[l], DIMS[l + 1]
        for o in range(n_out):                      # matriz W[saída][entrada]
            for i in range(n_in):
                pesos.append((o * 0.01) + (i * 0.0001) + (l * 0.1))
        for o in range(n_out):                      # bias
            pesos.append(-0.5 + l * 0.25 + o * 0.001)
    return pesos


def camadas():
    """[(nome, shape, [valores]), ...] na ordem em que aparecem no arquivo."""
    saida = []
    for l in range(len(DIMS) - 1):
        n_in, n_out = DIMS[l], DIMS[l + 1]
        w = []
        for o in range(n_out):
            for i in range(n_in):
                w.append((o * 0.01) + (i * 0.0001) + (l * 0.1))
        saida.append(("%d.weight" % l, [n_out, n_in], w))
        b = [-0.5 + l * 0.25 + o * 0.001 for o in range(n_out)]
        saida.append(("%d.bias" % l, [n_out], b))
    return saida


# ------------------------------------------------------------------ .pt (torch)
class Escritor:
    """Escreve pickle à mão — precisamos emitir GLOBAL de módulos que não
    existem aqui (torch._utils), e o pickle padrão tentaria importá-los."""

    def __init__(self, protocolo=2):
        self.buf = bytearray()
        self.buf += b"\x80" + bytes([protocolo])       # PROTO
        self.memo = {}

    def _memoize(self, chave):
        if chave in self.memo:
            self.bin_put(self.memo[chave])
            return True
        idx = len(self.memo)
        self.memo[chave] = idx
        self.bin_put(idx)
        return False

    def bin_put(self, i):
        if i < 256:
            self.buf += b"q" + bytes([i])              # BINPUT
        else:
            self.buf += b"r" + struct.pack("<I", i)     # LONG_BINPUT

    def global_(self, modulo, nome):
        self.buf += b"c" + modulo.encode() + b"\n" + nome.encode() + b"\n"

    def unicode_(self, s):
        b = s.encode("utf-8")
        # BINUNICODE (4 bytes de tamanho) — "\x8c" é o SHORT_BINUNICODE
        # do protocolo 4, que usa 1 byte só
        self.buf += b"X" + struct.pack("<I", len(b)) + b

    def int_(self, v):
        if 0 <= v < 256:
            self.buf += b"K" + bytes([v])              # BININT1
        elif -0x80000000 <= v < 0x80000000:
            self.buf += b"J" + struct.pack("<i", v)     # BININT
        else:
            self.buf += b"\x8a" + struct.pack("<Q", v)  # LONG1

    def mark(self):
        self.buf += b"("

    def tuple_(self):
        self.buf += b"t"

    def empty_tuple(self):
        self.buf += b")"

    def empty_dict(self):
        self.buf += b"}"

    def reduce(self):
        self.buf += b"R"

    def setitem(self):
        self.buf += b"s"

    def none(self):
        self.buf += b"N"

    def stop(self):
        self.buf += b"."


def pickle_torch(camadas, chaves_storage):
    """Pickle de um OrderedDict com tensores _rebuild_tensor_v2, igual ao torch."""
    e = Escritor()
    # OrderedDict vazio
    e.global_("collections", "OrderedDict")
    e.empty_tuple()
    e.reduce()
    e._memoize("odict")

    for (nome, shape, valores), chave in zip(camadas, chaves_storage):
        e.unicode_(nome)
        # torch._utils._rebuild_tensor_v2(storage, offset, size, stride, grad, hooks)
        e.global_("torch._utils", "_rebuild_tensor_v2")
        e.mark()
        # storage vem como id persistente: ('storage', tipo, chave, local, numel).
        # O pickle salva o tupla primeiro e só depois o BINPERSID (que consome
        # o topo da pilha) — é assim que o torch faz.
        e.mark()
        e.unicode_("storage")
        e.unicode_("FloatStorage")
        e.unicode_(chave)
        e.unicode_("cpu")
        e.int_(len(valores))
        e.tuple_()
        e.buf += b"Q"                                  # BINPERSID
        e.int_(0)                                      # storage_offset
        e.mark()
        for d in shape:
            e.int_(d)
        e.tuple_()                                     # size
        e.mark()
        # strides linha-a-linha (contíguo): stride[i] = produto das dimensões
        # seguintes — é o que o torch grava para um Linear
        for i in range(len(shape)):
            st = 1
            for d in shape[i + 1:]:
                st *= d
            e.int_(st)
        e.tuple_()
        e.buf += b"\x89"                               # NEWFALSE (requires_grad)
        e.empty_dict()                                 # backward_hooks
        e.tuple_()
        e.reduce()
        e.setitem()
    e.stop()
    return bytes(e.buf)


def escrever_pt(caminho, comprimir=False):
    cs = camadas()
    chaves = [str(i) for i in range(len(cs))]
    pkl = pickle_torch(cs, chaves)
    modo = zipfile.ZIP_DEFLATED if comprimir else zipfile.ZIP_STORED
    with zipfile.ZipFile(caminho, "w", modo) as z:
        z.writestr("rede/data.pkl", pkl)
        for (nome, shape, valores), chave in zip(cs, chaves):
            z.writestr("rede/data/%s" % chave, struct.pack("<%df" % len(valores), *valores))
        z.writestr("rede/version", "3\n")
    return caminho


# ------------------------------------------------------------------ .npz (numpy)
def cabecalho_npy(shape):
    d = {"descr": "<f4", "fortran_order": False, "shape": tuple(shape)}
    texto = repr(d).encode("latin1")
    while (len(texto) + 10 + 1) % 64 != 0:
        texto = texto[:-1] + b" " + texto[-1:] if False else texto + b" "
        # preenche com espaços até o cabeçalho fechar em múltiplo de 64
        if (len(texto) + 10 + 1) % 64 == 0:
            break
    texto = texto.rstrip(b" ")
    while (len(texto) + 10 + 1) % 64 != 0:
        texto += b" "
    return b"\x93NUMPY" + bytes([1, 0]) + struct.pack("<H", len(texto) + 1) + texto + b"\n"


def escrever_npz(caminho):
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_STORED) as z:
        for i, (nome, shape, valores) in enumerate(camadas()):
            z.writestr("%d.npy" % i,
                       cabecalho_npy(shape) + struct.pack("<%df" % len(valores), *valores))
    return caminho


# ------------------------------------------------------------------ safetensors
def escrever_safetensors(caminho):
    cabeca = {}
    dados = bytearray()
    for nome, shape, valores in camadas():
        inicio = len(dados)
        dados += struct.pack("<%df" % len(valores), *valores)
        cabeca[nome] = {"dtype": "F32", "shape": shape,
                        "data_offsets": [inicio, len(dados)]}
    meta = json.dumps(cabeca, sort_keys=True).encode("utf-8")
    with open(caminho, "wb") as f:
        f.write(struct.pack("<Q", len(meta)))
        f.write(meta)
        f.write(bytes(dados))
    return caminho


# ------------------------------------------------------------------ lixo (recusar)
def escrever_lixo(caminho, texto):
    with open(caminho, "wb" if not texto else "w") as f:
        if texto:
            f.write("isto nao é uma rede neural, é só um texto\n")
        else:
            f.write(bytes((i * 37 + 11) % 256 for i in range(4096)))
    return caminho


def main():
    os.makedirs(DESTINO, exist_ok=True)
    feitos = [
        escrever_pt(os.path.join(DESTINO, "rede.pt")),
        escrever_pt(os.path.join(DESTINO, "rede_comprimida.pt"), comprimir=True),
        escrever_npz(os.path.join(DESTINO, "rede.npz")),
        escrever_safetensors(os.path.join(DESTINO, "rede.safetensors")),
        escrever_lixo(os.path.join(DESTINO, "nao_e_rede.bin"), False),
        escrever_lixo(os.path.join(DESTINO, "nao_e_rede.txt"), True),
    ]
    # o nosso formato JSON, para comparar
    json_path = os.path.join(DESTINO, "rede.json")
    with open(json_path, "w") as f:
        json.dump({"obs_dim": DIMS[0], "act_dim": DIMS[-1], "hidden": DIMS[1:-1],
                   "weights": pesos_da_rede(),
                   "meta": {"gerado_por": "gerar_modelos_teste.py"}}, f)
    feitos.append(json_path)
    for p in feitos:
        print("  %-40s %6d bytes" % (os.path.basename(p), os.path.getsize(p)))

    # confere que o .pt que geramos tem a cara de um .pt de verdade
    with zipfile.ZipFile(os.path.join(DESTINO, "rede.pt")) as z:
        print("  entradas do zip:", z.namelist())
    return 0


if __name__ == "__main__":
    sys.exit(main())
