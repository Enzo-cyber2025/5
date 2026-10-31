from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "apk-fix/assets"
EXPECTED = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}


def test_launcher_icons_exist_in_all_android_density_sizes():
    for density, expected_size in EXPECTED.items():
        path = ASSETS / f"gguftx-logo-{density}.png"
        data = path.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (expected_size, expected_size)


def test_mobile_build_replaces_each_launcher_density():
    build = (ROOT / "apk-fix/build_mobile.py").read_text()
    for density in EXPECTED:
        assert f"res/mipmap-{density}/ic_launcher.png" in build
        assert f"gguftx-logo-{density}.png" in build
    assert "if n in LAUNCHER_ICONS:data=LAUNCHER_ICONS[n].read_bytes()" in build
