#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/enzc.py: compilador da linguagem ENZ
#
#  Linguagem C-like de inteiros (32 bits):
#    - tipos: int (e void em funções); vetores 1-D `int a[64];`
#    - globais, funções com até 6 parâmetros, chamadas
#    - if/else, while, break, return, blocos aninhados com escopo
#    - operadores: || && == != < > <= >= | ^ & << >> + - * / % = e
#      compostos (+= -= *= /= %=), unários - !
#    - literais decimais/hex, strings ("...") → ASCIZ no .data
#    - chamadas às 36 APIs do kernel por nome (rect, px, text, rand, ...)
#    - globais especiais win_w / win_h (preenchidas pelo runtime)
#
#  Handlers: void init(), void paint(), void tick(),
#            void key(int k), void mouse(int x, int y, int b, int p)
#
#  Saída: NASM x86-64 (org 0, app .ENZ cru) + arquivo .imports (nomes usados)
#
#  Uso: python3 tools/enzc.py entrada.enz saida.asm
# =============================================================================
import sys

API_IMPORTS = [
    "rect", "text", "blit", "title", "uptime", "file_open", "files_count",
    "file_name", "exec", "conout_read", "rand", "invalidate", "alloc", "free",
    "sysinfo", "time", "exit", "beep", "self", "px", "line", "grad", "round",
    "blend", "fs_open", "fs_list", "fs_read", "fs_write", "fs_creat",
    "fs_mkdir", "fs_unlink", "net_get", "swap_info", "swap_force", "hpet_ns",
    "tone",
]
API_IDX = {n: i + 1 for i, n in enumerate(API_IMPORTS)}

KEYWORDS = {"int", "void", "if", "else", "while", "return", "break"}

# ---------------------------- lexer -------------------------------------------

class Tok:
    def __init__(self, kind, val, line):
        self.kind = kind      # id, num, str, op, kw, eof
        self.val = val
        self.line = line

    def __repr__(self):
        return f"{self.kind}({self.val!r})"


def lex(src):
    toks = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                err(line, "comentário de bloco sem fim")
            line += src.count("\n", i, j)
            i = j + 2
            continue
        if c.isdigit():
            j = i
            if src.startswith("0x", i) or src.startswith("0X", i):
                j = i + 2
                while j < n and src[j] in "0123456789abcdefABCDEF":
                    j += 1
                toks.append(Tok("num", int(src[i:j], 16), line))
            else:
                while j < n and src[j].isdigit():
                    j += 1
                toks.append(Tok("num", int(src[i:j]), line))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(Tok("kw" if w in KEYWORDS else "id", w, line))
            i = j
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\n":
                    err(line, "string sem fechar")
                if src[j] == "\\":
                    j += 1
                    esc = src[j] if j < n else ""
                    v = {"n": 10, "t": 9, "0": 0, "\\": 92, '"': 34}.get(esc)
                    if v is None:
                        buf.extend(esc.encode("utf-8"))
                    else:
                        buf.append(v)
                else:
                    buf.extend(src[j].encode("utf-8"))
                j += 1
            if j >= n:
                err(line, "string sem fechar")
            toks.append(Tok("str", bytes(buf), line))
            i = j + 1
            continue
        for op in ("<<", ">>", "==", "!=", "<=", ">=", "&&", "||",
                   "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
                   "<<=", ">>="):
            if src.startswith(op, i):
                toks.append(Tok("op", op, line))
                i += len(op)
                break
        else:
            if c in "+-*/%<>=!&|^(){}[];,!":
                toks.append(Tok("op", c, line))
                i += 1
            else:
                err(line, f"caractere inesperado {c!r}")
    toks.append(Tok("eof", None, line))
    return toks


def err(line, msg):
    print(f"enzc: linha {line}: {msg}", file=sys.stderr)
    sys.exit(1)

# ---------------------------- AST ---------------------------------------------
# nós = tuplas (tipo, ...)

class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self, k=0):
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, kind, val=None):
        t = self.next()
        if t.kind != kind or (val is not None and t.val != val):
            want = val if val is not None else kind
            err(t.line, f"esperava {want!r}, veio {t.val!r}")
        return t

    def accept(self, kind, val=None):
        t = self.peek()
        if t.kind == kind and (val is None or t.val == val):
            return self.next()
        return None

    # ---- topo ----
    def program(self):
        globs = []
        funcs = []
        while self.peek().kind != "eof":
            t = self.peek()
            if t.kind == "kw" and t.val in ("int", "void"):
                # função ou global
                ret = self.next()
                name = self.expect("id").val
                if self.accept("op", "("):
                    funcs.append(self.func_rest(ret.val, name))
                else:
                    if ret.val == "void":
                        err(t.line, "global void não existe")
                    globs.append(self.glob_rest(name))
            else:
                err(t.line, f"esperava declaração, veio {t.val!r}")
        return globs, funcs

    def func_rest(self, ret, name):
        params = []
        if not self.accept("op", ")"):
            while True:
                self.expect("kw", "int")
                pn = self.expect("id").val
                params.append(pn)
                if not self.accept("op", ","):
                    break
            self.expect("op", ")")
        body = self.block()
        return (name, ret, params, body)

    def glob_rest(self, name):
        # int name[N]; | int name = expr; | int name;
        if self.accept("op", "["):
            sz = self.expect("num").val
            self.expect("op", "]")
            self.expect("op", ";")
            init = None
            return (name, sz, init)
        init = None
        if self.accept("op", "="):
            init = self.expr()
        self.expect("op", ";")
        return (name, None, init)

    def block(self):
        self.expect("op", "{")
        stmts = []
        while not self.accept("op", "}"):
            stmts.append(self.stmt())
        return ("block", stmts)

    def stmt(self):
        t = self.peek()
        if t.kind == "kw":
            if t.val == "int":
                self.next()
                name = self.expect("id").val
                if self.accept("op", "["):
                    sz = self.expect("num").val
                    self.expect("op", "]")
                    self.expect("op", ";")
                    return ("decl_arr", name, sz)
                init = None
                if self.accept("op", "="):
                    init = self.expr()
                self.expect("op", ";")
                return ("decl", name, init)
            if t.val == "if":
                self.next()
                self.expect("op", "(")
                cond = self.expr()
                self.expect("op", ")")
                a = self.stmt()
                b = None
                if self.accept("kw", "else"):
                    b = self.stmt()
                return ("if", cond, a, b)
            if t.val == "while":
                self.next()
                self.expect("op", "(")
                cond = self.expr()
                self.expect("op", ")")
                body = self.stmt()
                return ("while", cond, body)
            if t.val == "return":
                self.next()
                e = None
                if not (self.peek().kind == "op" and self.peek().val == ";"):
                    e = self.expr()
                self.expect("op", ";")
                return ("return", e)
            if t.val == "break":
                self.next()
                self.expect("op", ";")
                return ("break",)
        if self.accept("op", "{"):
            stmts = []
            while not self.accept("op", "}"):
                stmts.append(self.stmt())
            return ("block", stmts)
        if self.accept("op", ";"):
            return ("block", [])
        # atribuição: id = expr; | id [ expr ] = expr;
        if t.kind == "id":
            nxt = self.peek(1)
            if nxt.kind == "op" and nxt.val == "=":
                self.next()
                self.next()
                rhs = self.expr()
                self.expect("op", ";")
                return ("expr", ("assign", t.val, None, rhs, t.line))
            if nxt.kind == "op" and nxt.val == "[":
                save = self.pos
                self.next()
                self.next()
                idx = self.expr()
                if self.accept("op", "]") and self.accept("op", "="):
                    rhs = self.expr()
                    self.expect("op", ";")
                    return ("expr", ("assign", t.val, idx, rhs, t.line))
                self.pos = save        # não era atribuição
        e = self.expr()
        self.expect("op", ";")
        return ("expr", e)

    # ---- expressões (precedência crescente) ----
    def expr(self):
        return self.binop(0)

    LVLS = [
        [("||",)], [("&&",)], [("==", "!=")], [("<", ">", "<=", ">=")],
        [("|",)], [("^",)], [("&",)], [("<<", ">>")],
        [("+", "-")], [("*", "/", "%")],
    ]

    def binop(self, lvl):
        if lvl >= len(self.LVLS):
            return self.unary()
        ops = self.LVLS[lvl][0] if isinstance(self.LVLS[lvl], list) else self.LVLS[lvl]
        a = self.binop(lvl + 1)
        while True:
            t = self.peek()
            if t.kind == "op" and t.val in ops:
                self.next()
                b = self.binop(lvl + 1)
                a = ("bin", t.val, a, b, t.line)
            elif (t.kind == "op" and lvl == 8
                  and t.val in ("+=", "-=", "*=", "/=", "%=", "&=", "|=",
                                "^=", "<<=", ">>=")):
                self.next()
                b = self.binop(lvl + 1)
                a = ("aug", t.val.rstrip("="), a, b, t.line)
            else:
                return a

    def unary(self):
        t = self.peek()
        if t.kind == "op" and t.val == "-":
            self.next()
            return ("neg", self.unary())
        if t.kind == "op" and t.val == "!":
            self.next()
            return ("not", self.unary())
        return self.primary()

    def primary(self):
        t = self.next()
        if t.kind == "num":
            return ("num", t.val)
        if t.kind == "str":
            return ("str", t.val)
        if t.kind == "op" and t.val == "(":
            e = self.expr()
            self.expect("op", ")")
            return e
        if t.kind == "id":
            if self.accept("op", "("):
                args = []
                if not self.accept("op", ")"):
                    while True:
                        args.append(self.expr())
                        if not self.accept("op", ","):
                            break
                    self.expect("op", ")")
                return ("call", t.val, args, t.line)
            if self.accept("op", "["):
                idx = self.expr()
                self.expect("op", "]")
                return ("idx", t.val, idx, t.line)
            return ("var", t.val, t.line)
        err(t.line, f"expressão inesperada: {t.val!r}")

# ---------------------------- codegen -----------------------------------------

class Gen:
    def __init__(self, globs, funcs):
        self.globs = globs
        self.funcs = {f[0]: f for f in funcs}
        self.used_api = set()
        self.strings = []            # [(label, bytes)]
        self.glabels = {}            # global name -> label
        self.out = []
        self.lbl = 0
        # escopo
        self.scopes = [{}]           # name -> ("local", off) / ("param", i)
        self.cur_fn = None
        self.local_off = 0
        self.loop_end = []
        self.ret_lbl = None

    def emit(self, s):
        self.out.append("        " + s)

    def emitl(self, s):
        self.out.append(s)

    def label(self):
        self.lbl += 1
        return f"L{self.lbl}"

    # ---- símbolos ----
    def declare(self, name, words=1):
        self.local_off += words * 4
        self.scopes[-1][name] = ("local", self.local_off)
        return self.local_off

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    # ---- programa ----
    def run(self):
        self.emitl("BITS 64")
        self.emitl("org 0")
        self.emitl("default rel")
        self.emitl("")
        self.emitl("; gerado por tools/enzc.py — app .ENZ (sdk 2)")
        self.emitl("")
        self.emitl("api_ptr: dq 0")
        self.emitl("win_w:   dd 480")
        self.emitl("win_h:   dd 320")
        data_bytes = 16                      # api_ptr(8) + win_w(4) + win_h(4)
        for g in self.globs:
            name, size, init = g
            if name in ("win_w", "win_h", "api_ptr"):
                err(0, f"global reservada: {name}")
            if size is not None:
                self.glabels[name] = f"g_{name}"
                self.emitl(f"g_{name}: times {size} dd 0")
                data_bytes += size * 4
            else:
                self.glabels[name] = f"g_{name}"
                iv = init[1] if (init and init[0] == "num") else 0
                self.emitl(f"g_{name}: dd {iv & 0xFFFFFFFF}")
                data_bytes += 4
        self.entry_rva = 64 + data_bytes     # RVA no arquivo .ENZ (header 64 B)
        self.emitl("")
        self.emitl("entry:")
        self.emit("push rbx")
        self.emit("push rbp")
        self.emit("push r12")
        self.emit("push r13")
        self.emit("push r14")
        self.emit("push r15")
        self.emit("mov [api_ptr], rdi")
        self.emit("mov rax, [rsi]")
        handlers = []
        for ev, code in (("init", 1), ("paint", 2), ("mouse", 3),
                         ("key", 4), ("tick", 5)):
            if ev in self.funcs:
                handlers.append((ev, code))
        for ev, code in handlers:
            self.emit(f"cmp eax, {code}")
            self.emit(f"je .{ev}")
        self.emit("jmp .out")
        for ev, _code in handlers:
            self.emitl(f".{ev}:")
            if ev == "init":
                self.emit("mov eax, [rsi+16]")
                self.emit("mov [win_w], eax")
                self.emit("mov eax, [rsi+24]")
                self.emit("mov [win_h], eax")
            if ev == "mouse":
                self.emit("mov edi, [rsi+16]")
                self.emit("mov esi, [rsi+24]")
                self.emit("mov edx, [rsi+32]")
                self.emit("mov ecx, [rsi+40]")
            if ev == "key":
                self.emit("mov edi, [rsi+16]")
            self.emit(f"call f_{ev}")
            self.emit("jmp .out")
        self.emitl(".out:")
        self.emit("pop r15")
        self.emit("pop r14")
        self.emit("pop r13")
        self.emit("pop r12")
        self.emit("pop rbp")
        self.emit("pop rbx")
        self.emit("ret")
        self.emitl("")
        # funções
        for f in self.funcs.values():
            self.gen_func(f)
        # strings
        if self.strings:
            self.emitl("; ---- strings ----")
            for lb, data in self.strings:
                q = ",".join(str(b) for b in data) + ",0"
                self.emitl(f"{lb}: db {q}")
        return "\n".join(self.out) + "\n"

    def fname(self, n):
        return f"f_{n}"

    # ---- funções ----
    def gen_func(self, f):
        name, ret, params, body = f
        if len(params) > 6:
            err(0, f"{name}: máximo de 6 parâmetros")
        self.cur_fn = name
        self.scopes = [{}]
        for i, p in enumerate(params):
            self.scopes[-1][p] = ("param", i)
        self.local_off = 0
        self.ret_lbl = self.label()
        self.emitl(f"; ---- {name} ----")
        self.emitl(self.fname(name) + ":")
        self.emit("push rbp")
        self.emit("mov rbp, rsp")
        # primeiro passa para achar tamanho? geramos em 2 passadas:
        # passada 1: declaração de locais (varre corpo)
        self.collect_locals(body)
        if self.local_off:
            self.emit(f"sub rsp, {((self.local_off + 15) // 16) * 16}")
        self.gen(body)
        self.emitl(f"{self.ret_lbl}:")
        self.emit("mov rsp, rbp")
        self.emit("pop rbp")
        self.emit("ret")
        self.emitl("")

    def collect_locals(self, node):
        # declara todos os locais do corpo no escopo único da função
        # (estilo C antigo: sem sombreamento entre blocos)
        def walk(n):
            if not isinstance(n, tuple):
                return
            if n[0] == "decl":
                self.declare(n[1])
            elif n[0] == "decl_arr":
                if n[2] > 4096:
                    err(0, "vetor grande demais (máx 4096)")
                self.declare(n[1], n[2])
            elif n[0] == "block":
                for s in n[1]:
                    walk(s)
            elif n[0] == "if":
                walk(n[2])
                if n[3]:
                    walk(n[3])
            elif n[0] == "while":
                walk(n[2])
        walk(node)

    # ---- statements ----
    def gen(self, node):
        k = node[0]
        if k == "block":
            self.scopes.append({})
            for s in node[1]:
                self.gen(s)
            self.scopes.pop()
        elif k == "decl":
            off = self.redeclare(node[1])
            if node[2]:
                self.gen_expr(node[2])
                self.emit(f"mov [rbp - {off}], eax")
        elif k == "decl_arr":
            self.redeclare_arr(node[1], node[2])
            off = self.scopes[-1][node[1]][1]
            # zera
            lb = self.label()
            self.emit(f"lea rcx, [rbp - {off}]")
            self.emit("xor edx, edx")
            self.emitl(f"{lb}:")
            self.emit(f"cmp edx, {node[2] * 4}")
            self.emit("jae .zend" + lb[1:])
            self.emit(f"mov dword [rcx + rdx], 0")
            self.emit("add edx, 4")
            self.emit(f"jmp {lb}")
            self.emitl(f".zend{lb[1:]}:")
        elif k == "if":
            self.gen_expr(node[1])
            le = self.label()
            self.emit("test eax, eax")
            self.emit(f"jz {le}")
            self.gen(node[2])
            if node[3]:
                ld = self.label()
                self.emit(f"jmp {ld}")
                self.emitl(f"{le}:")
                self.gen(node[3])
                self.emitl(f"{ld}:")
            else:
                self.emitl(f"{le}:")
        elif k == "while":
            lc = self.label()
            ld = self.label()
            self.emitl(f"{lc}:")
            self.gen_expr(node[1])
            self.emit("test eax, eax")
            self.emit(f"jz {ld}")
            self.loop_end.append(ld)
            self.gen(node[2])
            self.loop_end.pop()
            self.emit(f"jmp {lc}")
            self.emitl(f"{ld}:")
        elif k == "return":
            if node[1]:
                self.gen_expr(node[1])
            else:
                self.emit("xor eax, eax")
            self.emit(f"jmp {self.ret_lbl}")
        elif k == "break":
            if not self.loop_end:
                err(0, "break fora de while")
            self.emit(f"jmp {self.loop_end[-1]}")
        elif k == "expr":
            self.gen_expr(node[1])
        else:
            err(0, f"statement desconhecido {k}")

    def redeclare(self, name):
        # procura declaração feita em collect_locals no escopo atual
        for s in reversed(self.scopes):
            if name in s:
                return s[name][1]
        # declara agora (não estava — impossível, coletor cobre tudo)
        return self.declare(name)

    def redeclare_arr(self, name, size):
        for s in reversed(self.scopes):
            if name in s:
                return s[name][1]
        return self.declare(name, size)

    # ---- expressões ----
    def gen_expr(self, e):
        k = e[0]
        if k == "num":
            v = e[1] & 0xFFFFFFFF
            if v >= 0x80000000:
                self.emit(f"mov eax, {v - 0x100000000}")
            else:
                self.emit(f"mov eax, {v}")
        elif k == "str":
            lb = f"s{len(self.strings)}"
            self.strings.append((lb, e[1]))
            self.emit(f"lea rax, [{lb}]")
        elif k == "var":
            self.load_var(e[1], e[2])
        elif k == "idx":
            self.addr_of(e)
            self.emit("mov eax, [rax]")
        elif k == "neg":
            self.gen_expr(e[1])
            self.emit("neg eax")
        elif k == "not":
            self.gen_expr(e[1])
            self.emit("test eax, eax")
            self.emit("setz al")
            self.emit("movzx eax, al")
        elif k == "bin":
            self.gen_bin(e)
        elif k == "aug":
            self.gen_aug(e)
        elif k == "assign":
            _, name, idx, rhs, line = e
            if idx is None:
                self.addr_of(("var", name, line))
            else:
                self.addr_of(("idx", name, idx, line))
            self.emit("push rax")
            self.gen_expr(rhs)
            self.emit("pop rcx")
            self.emit("mov [rcx], eax")
        elif k == "call":
            self.gen_call(e)
        else:
            err(0, f"expressão desconhecida {k}")

    def gen_bin(self, e):
        _, op, a, b, line = e
        if op == "&&":
            lf, ld = self.label(), self.label()
            self.gen_expr(a)
            self.emit("test eax, eax")
            self.emit(f"jz {lf}")
            self.gen_expr(b)
            self.emit("test eax, eax")
            self.emit(f"jz {lf}")
            self.emit("mov eax, 1")
            self.emit(f"jmp {ld}")
            self.emitl(f"{lf}:")
            self.emit("xor eax, eax")
            self.emitl(f"{ld}:")
            return
        if op == "||":
            lt, ld = self.label(), self.label()
            self.gen_expr(a)
            self.emit("test eax, eax")
            self.emit(f"jnz {lt}")
            self.gen_expr(b)
            self.emit("test eax, eax")
            self.emit(f"jnz {lt}")
            self.emit("xor eax, eax")
            self.emit(f"jmp {ld}")
            self.emitl(f"{lt}:")
            self.emit("mov eax, 1")
            self.emitl(f"{ld}:")
            return
        self.gen_expr(a)
        self.emit("push rax")
        self.gen_expr(b)
        self.emit("mov ecx, eax")
        self.emit("pop rax")
        if op == "+":
            self.emit("add eax, ecx")
        elif op == "-":
            self.emit("sub eax, ecx")
        elif op == "*":
            self.emit("imul eax, ecx")
        elif op == "/":
            self.emit("cdq")
            self.emit("idiv ecx")
        elif op == "%":
            self.emit("cdq")
            self.emit("idiv ecx")
            self.emit("mov eax, edx")
        elif op == "&":
            self.emit("and eax, ecx")
        elif op == "|":
            self.emit("or eax, ecx")
        elif op == "^":
            self.emit("xor eax, ecx")
        elif op == "<<":
            self.emit("shl eax, cl")
        elif op == ">>":
            self.emit("sar eax, cl")
        elif op in ("==", "!=", "<", ">", "<=", ">="):
            self.emit("cmp eax, ecx")
            cc = {"==": "e", "!=": "ne", "<": "l", ">": "g",
                  "<=": "le", ">=": "ge"}[op]
            self.emit(f"set{cc} al")
            self.emit("movzx eax, al")
        else:
            err(line, f"operador desconhecido {op}")

    def gen_aug(self, e):
        _, op, lhs, rhs, line = e
        if lhs[0] not in ("var", "idx"):
            err(line, "alvo de atribuição inválido")
        self.addr_of(lhs)
        self.emit("push rax")
        self.gen_expr(rhs)
        self.emit("mov ecx, eax")
        self.emit("pop rdx")
        self.emit("mov eax, [rdx]")
        if op == "+":
            self.emit("add eax, ecx")
        elif op == "-":
            self.emit("sub eax, ecx")
        elif op == "*":
            self.emit("imul eax, ecx")
        elif op == "/":
            self.emit("cdq")
            self.emit("idiv ecx")
        elif op == "%":
            self.emit("cdq")
            self.emit("idiv ecx")
            self.emit("mov eax, edx")
        elif op == "&":
            self.emit("and eax, ecx")
        elif op == "|":
            self.emit("or eax, ecx")
        elif op == "^":
            self.emit("xor eax, ecx")
        elif op == "<<":
            self.emit("shl eax, cl")
        elif op == ">>":
            self.emit("sar eax, cl")
        self.emit("mov [rdx], eax")

    def load_var(self, name, line):
        sym = self.lookup(name)
        if sym:
            kind, v = sym
            if kind == "param":
                self.emit(f"mov eax, [rbp + {16 + v * 8}]")
            else:
                self.emit(f"mov eax, [rbp - {v}]")
            return
        if name in self.glabels:
            self.emit(f"mov eax, [{self.glabels[name]}]")
            return
        if name in ("win_w", "win_h"):
            self.emit(f"mov eax, [{name}]")
            return
        if name in API_IDX:
            # chamar API sem argumentos
            self.call_api(name, [], line)
            return
        err(line, f"símbolo desconhecido: {name}")

    def addr_of(self, node):
        """endereço do lvalue em RAX"""
        if node[0] == "var":
            name, line = node[1], node[2]
            sym = self.lookup(name)
            if sym:
                kind, v = sym
                if kind == "param":
                    self.emit(f"lea rax, [rbp + {16 + v * 8}]")
                else:
                    self.emit(f"lea rax, [rbp - {v}]")
                return
            if name in self.glabels:
                self.emit(f"lea rax, [{self.glabels[name]}]")
                return
            err(line, f"símbolo desconhecido: {name}")
        if node[0] == "idx":
            name, idx, line = node[1], node[2], node[3]
            self.gen_expr(idx)
            self.emit("mov rcx, rax")
            sym = self.lookup(name)
            if sym:
                kind, v = sym
                if kind == "param":
                    err(line, "não indexa parâmetro")
                self.emit(f"lea rdx, [rbp - {v}]")
            elif name in self.glabels:
                self.emit(f"lea rdx, [{self.glabels[name]}]")
            else:
                err(line, f"vetor desconhecido: {name}")
            self.emit("lea rax, [rdx + rcx*4]")
            return
        err(0, "lvalue inválido")

    def gen_call(self, e):
        _, name, args, line = e
        if len(args) > 6:
            err(line, "máximo de 6 argumentos")
        if name in self.funcs:
            self.emit("; args")
            for a in args:
                self.gen_expr(a)
                self.emit("push rax")
            regs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
            for r in reversed(regs[:len(args)]):
                self.emit(f"pop {r}")
            self.emit(f"call {self.fname(name)}")
            return
        if name == "len" and len(args) == 1 and args[0][0] == "str":
            self.emit(f"mov eax, {len(args[0][1])}")
            return
        if name in API_IDX:
            self.call_api(name, args, line)
            return
        err(line, f"função desconhecida: {name}")

    def call_api(self, name, args, line):
        idx = API_IDX[name]
        self.used_api.add(name)
        for a in args:
            self.gen_expr(a)
            self.emit("push rax")
        regs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
        for r in reversed(regs[:len(args)]):
            self.emit(f"pop {r}")
        self.emit("mov rax, [api_ptr]")
        self.emit(f"call [rax + 8*{idx}]")

# ---------------------------- main --------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("uso: enzc.py entrada.enz saida.asm", file=sys.stderr)
        sys.exit(1)
    src = open(sys.argv[1], encoding="utf-8").read()
    toks = lex(src)
    globs, funcs = Parser(toks).program()
    if "paint" not in [f[0] for f in funcs]:
        err(0, "o programa precisa de pelo menos void paint()")
    g = Gen(globs, funcs)
    asm = g.run()
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(asm)
    impfile = sys.argv[2].rsplit(".", 1)[0] + ".imports"
    with open(impfile, "w") as f:
        f.write(",".join(n for n in API_IMPORTS if n in g.used_api))
    entfile = sys.argv[2].rsplit(".", 1)[0] + ".entry"
    with open(entfile, "w") as f:
        f.write(str(g.entry_rva))
    print(f"enzc: {sys.argv[2]} — {len(funcs)} funções, "
          f"{len(g.used_api)} imports, {len(g.strings)} strings")


if __name__ == "__main__":
    main()
