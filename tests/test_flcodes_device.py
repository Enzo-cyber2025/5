"""The no-root device workflow, driven through a fake ``adb``.

The sandbox has no QEMU, no Android system image and no /dev/kvm, so the device
side is simulated the way adb would behave: the stub answers ``devices``,
``getprop``, ``pm list packages``, ``pm path``, ``pull`` and ``backup`` — and for
``backup`` it writes a real ``ANDROID BACKUP`` container (same bytes the device
produces), so everything downstream is the production code path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "family-link-codes"))

from flcodes import abe, device  # noqa: E402
from test_flcodes_abe import PACKAGE, SECRET, build_backup  # noqa: E402

FAKE_ADB = r'''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path

config = json.loads(Path(os.environ["FAKE_ADB_CONFIG"]).read_text())
args = [a for a in sys.argv[1:]]
serial = ""
if args[:1] == ["-s"]:
    serial, args = args[1], args[2:]
log = Path(config["log"])
with log.open("a") as handle:
    handle.write(json.dumps({"serial": serial, "args": args}) + "\n")

devices = config.get("devices", ["emulator-5554"])
if args == ["devices"]:
    print("List of devices attached")
    for name in devices:
        print(name + "\tdevice")
    sys.exit(0)

if args[:2] == ["shell", "getprop"]:
    print(config.get("props", {}).get(args[2], ""))
    sys.exit(0)

if args[:3] == ["shell", "pm", "list"] and args[3] == "packages":
    for package in config.get("packages", []):
        print("package:" + package)
    sys.exit(0)

if args[:3] == ["shell", "pm", "path"]:
    package = args[3]
    if package not in config.get("packages", []):
        sys.exit(1)
    for remote in config.get("apk_paths", {}).get(package, []):
        print("package:" + remote)
    sys.exit(0)

if args[:1] == ["pull"]:
    remote, local = args[1], args[2]
    source = Path(config.get("device_fs", "")) / remote.lstrip("/")
    if not source.exists():
        print("adb: error: failed to stat remote object", file=sys.stderr)
        sys.exit(1)
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, local)
    print("1 file pulled.")
    sys.exit(0)

if args[:1] == ["backup"]:
    target = Path(args[args.index("-f") + 1])
    payload = Path(config["backup_fixture"])
    if config.get("empty_backup"):
        payload.write_bytes(b"") if not payload.exists() else None
        target.write_bytes(b"")
    else:
        shutil.copyfile(payload, target)
    print("WARNING: adb backup is deprecated", file=sys.stderr)
    sys.exit(0)

print("fake adb: unsupported " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


@pytest.fixture()
def fake_device(tmp_path, monkeypatch):
    """Install the stub as ``adb`` on PATH and describe a connected phone."""
    tools = tmp_path / "bin"
    tools.mkdir()
    adb = tools / "adb"
    adb.write_text(FAKE_ADB)
    adb.chmod(adb.stat().st_mode | stat.S_IEXEC)

    device_fs = tmp_path / "device_fs"
    apk_dir = device_fs / "data" / "app" / "~~abc" / PACKAGE
    apk_dir.mkdir(parents=True)
    (apk_dir / "base.apk").write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    (apk_dir / "split_config.arm64_v8a.apk").write_bytes(b"PK\x03\x04" + b"\x00" * 16)

    backup_fixture = build_backup(tmp_path / "device.ab")

    config = {
        "log": str(tmp_path / "adb.log"),
        "devices": ["emulator-5554"],
        "props": {
            "ro.product.model": "sdk_gphone64_x86_64",
            "ro.build.version.release": "14",
            "ro.build.version.sdk": "34",
            "ro.debuggable": "0",
        },
        "packages": [PACKAGE, "com.other.app"],
        "apk_paths": {
            PACKAGE: [
                f"/data/app/~~abc/{PACKAGE}/base.apk",
                f"/data/app/~~abc/{PACKAGE}/split_config.arm64_v8a.apk",
            ]
        },
        "device_fs": str(device_fs),
        "backup_fixture": str(backup_fixture),
    }
    config_path = tmp_path / "adb.json"
    config_path.write_text(json.dumps(config))

    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_ADB_CONFIG", str(config_path))
    return {"config": config, "config_path": config_path, "tmp": tmp_path}


def test_device_info_reads_props_and_packages(fake_device):
    info = device.info()
    assert info.props["ro.product.model"] == "sdk_gphone64_x86_64"
    assert info.props["ro.build.version.sdk"] == "34"
    assert info.debuggable is False
    assert info.packages == [PACKAGE]
    assert any(path.endswith("base.apk") for path in info.apk_paths)


def test_device_info_without_family_link(tmp_path, monkeypatch, fake_device):
    config = json.loads(fake_device["config_path"].read_text())
    config["packages"] = ["com.other.app"]
    fake_device["config_path"].write_text(json.dumps(config))
    info = device.info()
    assert info.packages == []
    assert any("not installed" in note for note in info.notes)


def test_device_backup_writes_a_real_container(fake_device):
    target = fake_device["tmp"] / "out" / "familylink.ab"
    result = device.backup(PACKAGE, target)
    assert result["ok"] is True
    assert result["bytes"] > 0
    assert result["header"]["encryption"] == "none"
    assert abe.is_android_backup(target)
    result_apps = abe.list_apps(target)
    assert PACKAGE in result_apps


def test_device_backup_reports_an_empty_container(fake_device):
    config = json.loads(fake_device["config_path"].read_text())
    config["empty_backup"] = True
    fake_device["config_path"].write_text(json.dumps(config))
    result = device.backup(PACKAGE, fake_device["tmp"] / "empty.ab")
    assert result["ok"] is False
    assert "allowBackup" in result["reason"]


def _run_cli(*argv, home: Path):
    env = dict(os.environ)
    env.update({"FLCODES_HOME": str(home), "FLCODES_PASSPHRASE": "test-pass"})
    return subprocess.run(
        [sys.executable, "-m", "flcodes", *argv],
        cwd=str(Path(__file__).resolve().parent.parent / "family-link-codes"),
        capture_output=True, text=True, env=env, timeout=180,
    )


def test_cli_device_backup_scans_and_saves(fake_device):
    home = fake_device["tmp"] / "home"
    out = fake_device["tmp"] / "fl.ab"
    result = _run_cli(
        "device", "backup", "--out", str(out), "--scan", "--save", "--label", "phone",
        home=home, **{},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "confirmation" in result.stdout
    assert "AIte" in result.stdout
    assert "ttl=600s" in result.stdout
    gen = _run_cli("gen", "--label", "phone", "--time", "1792684800", "--json", home=home)
    assert json.loads(gen.stdout)["validity"] == 600


def test_cli_device_apk_pulls_the_splits(fake_device):
    home = fake_device["tmp"] / "home"
    out = fake_device["tmp"] / "apk-out"
    result = _run_cli("device", "apk", "--out", str(out), home=home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "base.apk" in result.stdout
    assert (out / "base.apk").exists()
    assert (out / "split_config.arm64_v8a.apk").exists()


def test_cli_device_info_reports_the_phone(fake_device):
    home = fake_device["tmp"] / "home"
    result = _run_cli("device", "info", home=home)
    assert result.returncode == 0, result.stderr
    assert "sdk_gphone64_x86_64" in result.stdout
    assert PACKAGE in result.stdout


def test_fake_adb_never_needs_root(fake_device):
    """Every adb call the tool makes must be root-free."""
    home = fake_device["tmp"] / "home"
    _run_cli("device", "info", home=home)
    _run_cli("device", "backup", "--out", str(fake_device["tmp"] / "b.ab"), home=home)
    calls = [
        json.loads(line)["args"]
        for line in Path(fake_device["config"]["log"]).read_text().splitlines()
    ]
    assert calls
    forbidden = {"su", "run-as", "root", "remount", "pull"}  # pull is expected, see below
    for args in calls:
        assert not ({"su", "run-as", "root", "remount"} & set(args)), args
        # only `pull` may write outside the app's own container
        if "pull" in args:
            assert "base.apk" in " ".join(args) or "split" in " ".join(args), args
