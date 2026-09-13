"""Run translated REAL APK classes on the JVM; Native/JSON are explicit test doubles.

Not an Android emulator, not a native inference test. Run via scripts/test_host.sh.
The same regression expectations can be run on the original jar to reproduce bugs.
"""
import os
from pathlib import Path
import struct

import pytest

JAR = os.environ.get("GGUF_TEST_JAR")
pytestmark = pytest.mark.skipif(not JAR, reason="Use scripts/test_host.sh for real APK/JVM regressions")


@pytest.fixture(scope="module")
def classes():
    import jpype
    import jdk4py
    jpype.startJVM(str(jdk4py.JAVA_HOME / "lib/server/libjvm.so"), "-Xverify:all",
                  classpath=[os.environ["GGUF_TEST_DOUBLES_JAR"], JAR], convertStrings=True)
    return {name: jpype.JClass("com.ggufchat.app." + name)
            for name in ["EngineManager", "ModelInfo", "Chat", "Native"]}


@pytest.fixture(autouse=True)
def reset(classes):
    engine, native = classes["EngineManager"], classes["Native"]
    engine.release()
    native.calls = native.destroys = 0
    native.failGpu = native.failAll = False
    native.mmproj = native.error = None
    yield
    engine.release()


@pytest.fixture
def files(tmp_path):
    # Header-only fixtures are intentionally used with a native TEST DOUBLE.
    result = []
    for name in ["model.gguf", "mmproj.gguf", "other.gguf"]:
        p = tmp_path / name
        p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 0))
        result.append(str(p))
    return result


@pytest.mark.parametrize("path", ["/models/vision-mmproj.gguf", "/modelos/projetor com espaços.gguf"])
def test_modelinfo_projector_roundtrip(classes, path):
    model = classes["ModelInfo"]()
    model.mmprojPath = path
    model.multimodal = True
    restored = classes["ModelInfo"].fromJson(model.toJson())
    assert restored.mmprojPath == path
    assert restored.multimodal


@pytest.mark.parametrize("path", [None, "", "null"])
def test_modelinfo_null_paths_normalized(classes, path):
    model = classes["ModelInfo"]()
    model.mmprojPath = path
    assert classes["ModelInfo"].fromJson(model.toJson()).mmprojPath is None


@pytest.mark.parametrize("projector", [None, "/models/vision-projector.gguf"])
def test_chat_roundtrip_preserves_model_and_projector(classes, projector):
    chat = classes["Chat"]("/models/llama.gguf", projector)
    for _ in range(3):
        chat = classes["Chat"].fromJson(chat.toJson())
        assert chat.modelPath == "/models/llama.gguf"
        assert chat.mmprojPath == projector


@pytest.mark.parametrize("path", [None, "", "null"])
def test_chat_null_paths_normalized(classes, path):
    chat = classes["Chat"](path, path)
    restored = classes["Chat"].fromJson(chat.toJson())
    assert restored.modelPath is None
    assert restored.mmprojPath is None


def test_projector_reaches_native(classes, files):
    classes["EngineManager"].load(files[0], files[1], 1024, 2, 0, True)
    assert classes["Native"].mmproj == files[1]


@pytest.mark.parametrize("projector", [None, "", "null"])
def test_native_gets_null_for_absent_projector(classes, files, projector):
    classes["EngineManager"].load(files[0], projector, 1024, 2, 0, True)
    assert classes["Native"].mmproj is None


def test_identical_configuration_reuses_handle(classes, files):
    engine, native = classes["EngineManager"], classes["Native"]
    first = engine.load(files[0], files[1], 1024, 2, 0, True)
    assert engine.load(files[0], files[1], 1024, 2, 0, True) == first
    assert native.calls == 1
    assert native.destroys == 0


@pytest.mark.parametrize("options", [(2048, 2, 0, True), (1024, 4, 0, True),
                                     (1024, 2, -1, True), (1024, 2, 0, False)])
def test_each_configuration_change_reloads(classes, files, options):
    engine, native = classes["EngineManager"], classes["Native"]
    engine.load(files[0], None, 1024, 2, 0, True)
    engine.load(files[0], None, *options)
    assert native.calls == 2
    assert native.destroys == 1


def test_changing_projector_reloads(classes, files):
    engine, native = classes["EngineManager"], classes["Native"]
    engine.load(files[0], files[1], 1024, 2, 0, True)
    engine.load(files[0], files[2], 1024, 2, 0, True)
    assert native.calls == 2
    assert native.mmproj == files[2]


def test_cpu_fallback_preserves_requested_cache_key(classes, files):
    engine, native = classes["EngineManager"], classes["Native"]
    native.failGpu = True
    first = engine.load(files[0], files[1], 1024, 2, -1, True)
    assert native.calls == 2 and native.gpu == 0
    assert native.mmproj == files[1]
    assert engine.load(files[0], files[1], 1024, 2, -1, True) == first
    assert native.calls == 2
    engine.load(files[0], files[1], 1024, 2, 0, True)
    assert native.calls == 3


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "short", "bad-magic", "bad-version"])
def test_invalid_model_rejected_before_native(classes, tmp_path, kind):
    p = tmp_path / "invalid.gguf"
    if kind == "directory":
        p.mkdir()
    elif kind != "missing":
        payload = {"empty": b"", "short": b"GGUF", "bad-magic": b"XXXX" + bytes(20),
                   "bad-version": b"GGUF" + struct.pack("<IQQ", 99, 0, 0)}[kind]
        p.write_bytes(payload)
    with pytest.raises(Exception, match="GGUF"):
        classes["EngineManager"].load(str(p), None, 1024, 2, 0, True)
    assert classes["Native"].calls == 0


def test_bad_projector_does_not_destroy_good_engine(classes, files):
    engine, native = classes["EngineManager"], classes["Native"]
    good = engine.load(files[0], None, 1024, 2, 0, True)
    with pytest.raises(Exception, match="GGUF"):
        engine.load(files[0], "/nonexistent-projector.gguf", 1024, 2, 0, True)
    assert engine.currentHandle() == good
    assert native.destroys == 0


def test_native_load_failure_releases_old_handle_and_can_retry(classes, files):
    engine, native = classes["EngineManager"], classes["Native"]
    engine.load(files[0], None, 1024, 2, 0, True)
    native.failAll = True
    with pytest.raises(Exception):
        engine.load(files[2], None, 1024, 2, 0, True)
    assert engine.currentHandle() == 0
    native.failAll = False
    assert engine.load(files[2], None, 1024, 2, 0, True) != 0


def test_generation_success(classes):
    import jpype
    jpype.JClass("com.ggufchat.app.GenerationResult").check(True, 1)


@pytest.mark.parametrize("message", [None, "", "Erro nativo de teste"])
def test_generation_false_is_error_not_success(classes, message):
    import jpype
    classes["Native"].error = message
    checker = jpype.JClass("com.ggufchat.app.GenerationResult")
    with pytest.raises(Exception, match=message or "Geração interrompida"):
        checker.check(False, 1)
