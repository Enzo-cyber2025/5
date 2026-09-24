"""Uma classe aninhada não pode esconder um auxiliar da classe externa.

O compilador do CI reprovou a rodada 36021292419 com:

    CodeBlocks.java:87: error: method panel in class Stream cannot be applied to
    given types; required: no arguments, found: Context

A classe aninhada `Stream` declara `panel()` sem argumentos; a chamada
`panel(c)` dentro dela então deixa de encontrar o auxiliar `panel(Context)` da
classe externa, embora ele exista. Nenhuma ferramenta local compila Java aqui,
mas a estrutura dá para ser lida: este teste reproduz a regra de resolução do
javac — um nome declarado na classe aninhada esconde o auxiliar externo de mesmo
nome, e a chamada só compila se casar com uma aridade declarada ali mesmo — e
reprova a rodada antes de gastar um ciclo inteiro de emulador.
"""
from pathlib import Path

import pytest

javalang = pytest.importorskip('javalang')

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / 'apk-fix/java/com/ggufchat/app').glob('*.java'))


def _argc(method):
    return len(method.parameters or [])


def _declared(cls):
    names = {}
    for method in cls.methods:
        names.setdefault(method.name, set()).add(_argc(method))
    return names


def _collect(node, out):
    if not isinstance(node, javalang.tree.Node):
        return
    if isinstance(node, javalang.tree.MethodInvocation) and not node.qualifier:
        out.append((node.member, len(node.arguments or [])))
    for child in node.children:
        if isinstance(child, (list, tuple)):
            for item in child:
                _collect(item, out)
        else:
            _collect(child, out)


def shadowed_calls(text):
    """Chamadas sem qualificador que um método da classe aninhada esconde."""
    tree = javalang.parse.parse(text)
    top = tree.types[0]
    found = []

    def dive(cls, nested):
        names = _declared(cls) if nested else {}
        calls = []
        for child in cls.body:
            if isinstance(child, javalang.tree.ClassDeclaration):
                dive(child, True)
            else:
                _collect(child, calls)
        if nested:
            for name, argc in calls:
                if name in names and argc not in names[name]:
                    found.append((cls.name, name, argc))

    dive(top, False)
    return sorted(set(found))


def test_detector_reproduces_the_ci_failure():
    broken = '''
public class A {
    private static int size(String s){return 0;}
    static final class B {
        int size(){return 1;}
        void go(){ int x = size("s"); }
    }
}
'''
    assert shadowed_calls(broken) == [('B', 'size', 1)]


def test_detector_accepts_a_call_that_matches_the_nested_declaration():
    healthy = '''
public class A {
    private static int size(String s){return 0;}
    static final class B {
        int size(int n){return 1;}
        void go(){ int x = size(1); }
    }
}
'''
    assert shadowed_calls(healthy) == []


def test_detector_rejects_a_hiding_name_even_when_outer_would_fit():
    # javac esconde por nome: a existência de size(String) na classe externa não
    # salva a chamada. É este o caso que reprovou a rodada 36021292419.
    hidden = '''
public class A {
    private static int size(String s){return 0;}
    static final class B {
        int size(){return 1;}
        void go(){ int x = size("s"); }
    }
}
'''
    assert shadowed_calls(hidden) == [('B', 'size', 1)]


def test_no_nested_class_hides_an_outer_helper():
    assert SOURCES, 'fontes do aplicativo ausentes'
    offenders = {path.name: shadowed_calls(path.read_text()) for path in SOURCES}
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert offenders == {}, f'auxiliar externo escondido por classe aninhada: {offenders}'
