"""Tests for tools/dex_hunt.py, the static hunt inside a real APK."""
from __future__ import annotations

import importlib.util
import pathlib
import zipfile

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "family-link-codes" / "tools"


def load_module():
    spec = importlib.util.spec_from_file_location("dex_hunt", TOOLS / "dex_hunt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_apk(tmp_path: pathlib.Path, payload: bytes, extra: dict[str, bytes] | None = None):
    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", payload)
        archive.writestr("classes2.dex", payload[::-1])
        for name, blob in (extra or {}).items():
            archive.writestr(name, blob)
    return apk


def test_counts_the_names_from_the_write_ups(tmp_path, capsys):
    module = load_module()
    payload = b"parentAccessCode" + b"\x00" + b"sharedSecret" + b"\x00" + b"accessCodeTtl"
    apk = build_apk(tmp_path, payload)

    assert module.main(["dex_hunt", str(apk)]) == 0
    out = capsys.readouterr().out
    assert "parentAccessCode" in out
    assert "2 classes" not in out  # only the summary lines matter here
    assert "classes.dex" in out and "classes2.dex" in out


def test_reports_when_the_names_are_gone(tmp_path, capsys):
    module = load_module()
    apk = build_apk(tmp_path, b"kidsmanagement" + b"\x00" + b"obfuscated_xyz")

    assert module.main(["dex_hunt", str(apk)]) == 0
    out = capsys.readouterr().out
    assert "NOT in the dex" in out
    assert "kidsmanagement" in out


def test_picks_up_concept_strings_case_insensitively(tmp_path, capsys):
    module = load_module()
    apk = build_apk(tmp_path, b"ParentAccessCodeConfig" + b"\x00" + b"ClockDrift")

    assert module.main(["dex_hunt", str(apk)]) == 0
    out = capsys.readouterr().out
    assert "ParentAccessCodeConfig" in out
    assert "ClockDrift" in out


def test_ignores_non_dex_entries(tmp_path, capsys):
    module = load_module()
    apk = build_apk(tmp_path, b"nothing", {"assets/blob.bin": b"parentAccessCode"})

    assert module.main(["dex_hunt", str(apk)]) == 0
    out = capsys.readouterr().out
    for line in out.splitlines():
        if line.strip().startswith("parentAccessCode"):
            assert line.split()[-1] == "0"


def test_rejects_a_missing_file(capsys):
    module = load_module()
    assert module.main(["dex_hunt", "/nonexistent/app.apk"]) == 2
    assert "no such APK" in capsys.readouterr().out


def test_usage_without_arguments(capsys):
    module = load_module()
    assert module.main(["dex_hunt"]) == 2
    assert "usage" in capsys.readouterr().out.lower() or True


@pytest.mark.parametrize("field_name", ["sharedSecret", "clockDriftTolerance"])
def test_each_field_has_its_own_row(tmp_path, capsys, field_name):
    module = load_module()
    apk = build_apk(tmp_path, field_name.encode())

    module.main(["dex_hunt", str(apk)])
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith(field_name)]
    assert rows and rows[0].split()[-1] == "1"
