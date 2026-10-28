"""The last leg of the chain: a captured response -> secret -> code."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from flcodes import proto as proto_mod

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "family-link-codes" / "tools"


def load_tool():
    spec = importlib.util.spec_from_file_location("response_to_code",
                                                  TOOLS / "response_to_code.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_response_carries_a_secret():
    tool = load_tool()
    blob = tool.synthetic_response()
    found = proto_mod.find_secret_fields(blob)
    assert found, "the synthetic response must contain the secret"
    assert found[0][1] == tool.TEST_SECRET


def test_the_chain_runs_end_to_end(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")

    assert tool.main(["response_to_code", "--synthetic"]) == 0
    out = capsys.readouterr().out
    assert "secret found at" in out
    assert "PASS: a captured response yields a secret" in out
    assert '"code":' in out


def test_the_secret_is_masked_by_default(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")

    tool.main(["response_to_code", "--synthetic"])
    out = capsys.readouterr().out
    assert tool.TEST_SECRET not in out
    assert "AIzaSy…01" in out


def test_print_secret_reveals_it(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")

    tool.main(["response_to_code", "--synthetic", "--print-secret"])
    assert tool.TEST_SECRET in capsys.readouterr().out


def test_a_base64_body_is_accepted(tmp_path, monkeypatch, capsys):
    import base64

    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")
    body = tmp_path / "capture.b64"
    body.write_bytes(base64.b64encode(tool.synthetic_response()))

    assert tool.main(["response_to_code", "--response", str(body), "--base64"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_message_without_a_secret_says_so(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")
    body = tmp_path / "empty.bin"
    body.write_bytes(b"\x08\x01")

    assert tool.main(["response_to_code", "--response", str(body)]) == 1
    assert "no secret-shaped field" in capsys.readouterr().out


def test_the_code_it_makes_is_the_one_the_app_would_show(tmp_path, monkeypatch, capsys):
    """Same secret, same window: the generator must agree with itself."""
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")

    from flcodes import codes as codes_mod

    expected = codes_mod.generate_code(tool.TEST_SECRET, validity=600)
    tool.main(["response_to_code", "--synthetic"])
    out = capsys.readouterr().out
    assert f'"code": "{expected.code}"' in out


def test_help_without_arguments(capsys):
    tool = load_tool()
    assert tool.main(["response_to_code"]) == 2
    assert "usage" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("ttl", [60, 300, 3600])
def test_the_ttl_comes_from_the_response(tmp_path, monkeypatch, capsys, ttl):
    tool = load_tool()
    monkeypatch.setenv("FLCODES_HOME", str(tmp_path))
    monkeypatch.setenv("FLCODES_PASSPHRASE", "test")
    body = tmp_path / "resp.bin"
    body.write_bytes(tool.synthetic_response(ttl=ttl))

    tool.main(["response_to_code", "--response", str(body)])
    assert f"validity from the response: {ttl}s" in capsys.readouterr().out
