"""
layout.py -- make content/cars/arb_rb20/ follow the vanilla Kunos car layout.

Reference: the Kunos "formula_k" open-wheel template (javirs200/acCar, GPL-3.0)
and the ks_mazda_mx5_nd2 car. A vanilla AC car folder is NOT just "data/" plus
a KN5: it also has animations/, sfx/, skins/, ui/, texture/, LOD KN5 files,
driver/camera INIs and shadow PNGs at the car root. This module writes those
standard files with original content (no third-party binary is copied).

Everything written here is vanilla: no CSP, no Lua, no data.acd.
"""
from __future__ import annotations

import math
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# -------------------------------------------------------------------- data INIs
DRIVER3D = """[MODEL]
NAME=driver
POSITION=0,0,0

[STEER_ANIMATION]
NAME=steer.ksanim
LOCK=200

[SHIFT_ANIMATION]
BLEND_TIME=100
POSITIVE_TIME=150
STATIC_TIME=10
NEGATIVE_TIME=150
PRELOAD_RPM=6000
INVERT_SHIFTING_HANDS=0

[HIDE_OBJECT_0]
NAME=DRIVER:HELMET

[HIDE_OBJECT_1]
NAME=DRIVER:GEO_Driver_FACE
"""

# Camera positions adapted from the Kunos formula_k F1 template.
CAMERAS = """[CAMERA_0]
POSITION=0,0.928,-0.347
FORWARD=0,-0.389,0.921
UP=0,0.921,0.389
FOV=60
EXPOSURE=41
EXTERNAL_SOUND=1

[CAMERA_1]
POSITION=0.531,0.511,-0.065
FORWARD=0.021,-0.342,0.939
UP=0.004,0.940,0.342
FOV=60
EXPOSURE=36
EXTERNAL_SOUND=1

[CAMERA_2]
POSITION=-0.251,0.739,-0.188
FORWARD=0.217,-0.393,0.894
UP=0.076,0.919,0.386
FOV=60
EXPOSURE=31
EXTERNAL_SOUND=1

[CAMERA_3]
POSITION=-0.295,0.983,-0.213
FORWARD=0.014,0.018,1.000
UP=0.018,0.999,-0.019
FOV=60
EXPOSURE=27
EXTERNAL_SOUND=0

[CAMERA_4]
POSITION=-0.440,0.964,0.042
FORWARD=0.822,-0.107,-0.559
UP=0.052,0.992,-0.113
FOV=60
EXPOSURE=8
EXTERNAL_SOUND=0

[CAMERA_5]
POSITION=0,1.210,-0.732
FORWARD=0,-0.205,-0.979
UP=0,0.979,-0.205
FOV=60
EXPOSURE=25
EXTERNAL_SOUND=1
"""

DASH_CAM = """[DASH_CAM]
POS=0.0018,0.651,0.129
EXP=35
"""

ESC_MODE = """[SETTINGS]
POSITION=0, 1.4, 3.2
FOV=45
"""

FUEL_CONS = """[FUEL_EVAL]
KM_PER_LITER=2.26
"""

THROTTLE = """0|0
1|1
"""

BLURRED = """; WHEEL INDEXES: 0=LF 1=RF 2=LR 3=RR
[OBJECT_0]
WHEEL_INDEX=0
NAME=RIM_LF
MIN_SPEED=0
MAX_SPEED=40

[OBJECT_1]
WHEEL_INDEX=1
NAME=RIM_RF
MIN_SPEED=0
MAX_SPEED=40

[OBJECT_2]
WHEEL_INDEX=2
NAME=RIM_LR
MIN_SPEED=0
MAX_SPEED=40

[OBJECT_3]
WHEEL_INDEX=3
NAME=RIM_RR
MIN_SPEED=0
MAX_SPEED=40
"""

PROVIEW = """[NODES]
RAIN_LIGHT=0
RAIN_LIGHT_WET=0
RAIN_LIGHT_L=0
RAIN_LIGHT_R=0
T_CAM=0
DASH_DRS=0
DASH_DRS_AVAIL=0
"""

SUSP_GRAPHICS = """; No overrides: vanilla suspension graphics are used.
"""

# Standard dash sections appended to the DRS LED configuration. DISPLAY_0
# points at a real mesh; ITEM_n are vanilla text readouts parented to STEER_HR.
DASH_EXTRA = """
[DISPLAY_0]
NAME=DASH_DISPLAY_MESH
EMISSIVE=2.1,6.0,2.1
INTENSITY=2.4

[ITEM_0]
PARENT=STEER_HR
POSITION=0.02,0.05,-0.125
TYPE=GEAR
SIZE=0.025
COLOR=10,10,10,255
INTENSITY=3.0
FONT=e92_big
VERSION=2
ALIGN=RIGHT

[ITEM_1]
PARENT=STEER_HR
POSITION=0.00,0.0485,-0.125
TYPE=RPM
SIZE=0.015
COLOR=11,11,11,255
INTENSITY=3.0
FONT=e92_big
VERSION=2
ALIGN=CENTER

[ITEM_2]
PARENT=STEER_HR
POSITION=-0.02,0.05,-0.125
TYPE=SPEED
SIZE=0.014
COLOR=10,10,10,255
INTENSITY=3.0
FONT=e92_big
VERSION=2
ALIGN=LEFT
UNITS=KMH
"""

# Standard skin metadata (Kunos formula_k skins/<skin>/ui_skin.json).
UI_SKIN = """{
  "skinname": "ARB RB20 2024",
  "drivername": "",
  "country": "",
  "team": "",
  "number": "1",
  "priority": 1
}
"""

# Only the shared Kunos common bank is referenced. No proprietary FMOD bank
# is redistributed; AC falls back to its own audio for everything else.
GUIDS = """{47dcf37a-6a8d-4ef6-9f82-2e0398fa69f9} bank:/common
"""

SOUND_NOTE = """Nenhum banco FMOD proprietario e redistribuido neste projeto.
O AC usa o banco comum (sfx/GUIDs.txt) e seu fallback de audio.
Isso nao afeta a fisica nem a compatibilidade vanilla.
"""


# ------------------------------------------------------------------ steer.ksanim
STEER_NODE = "STEER_HR"
STEER_HINGE_Y = 0.545
STEER_HINGE_Z = 1.002


def steer_frames(count=101, lock_deg=100.0):
    """Kunos-style steer animation: centre pose at the middle keyframe.

    Rotation about the column (Z) around the wheel centre H is stored as
    R plus t = H - R*H, because the mesh vertices live in car space.
    """
    import features
    frames = []
    for i in range(count):
        theta = math.radians(-lock_deg + 2.0 * lock_deg * i / (count - 1))
        c, s = math.cos(theta), math.sin(theta)
        q = (0.0, 0.0, math.sin(theta / 2.0), math.cos(theta / 2.0))
        hy = STEER_HINGE_Y
        # R about Z: (x*c-y*s, x*s+y*c, z); H=(0,hy,hz)
        t = (hy * s, hy * (1.0 - c), 0.0)
        frames.append((q, t, (1.0, 1.0, 1.0)))
    return frames


# ------------------------------------------------------------------ shadow PNGs
def _make_images(car_dir):
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("  layout: Pillow unavailable, skipping generated PNGs")
        return

    # Ground shadow projector (Kunos body_shadow.png is a soft grey blob).
    img = Image.new("L", (256, 512), 0)
    d = ImageDraw.Draw(img)
    d.ellipse((36, 40, 220, 472), fill=150)
    img = img.filter(ImageFilter.GaussianBlur(26))
    img.save(os.path.join(car_dir, "body_shadow.png"))

    for i in range(4):
        t = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(t).ellipse((8, 8, 56, 56), fill=170)
        t.filter(ImageFilter.GaussianBlur(8)).save(
            os.path.join(car_dir, "tyre_%d_shadow.png" % i))

    texture = os.path.join(car_dir, "texture")
    os.makedirs(texture, exist_ok=True)
    Image.new("RGB", (256, 128), (4, 8, 12)).save(
        os.path.join(texture, "display.png"))
    Image.new("RGB", (256, 128), (0, 0, 0)).save(
        os.path.join(texture, "display_off.png"))
    # Standard small livery placeholder next to the DDS skin textures.
    skin = os.path.join(car_dir, "skins", "default")
    os.makedirs(skin, exist_ok=True)
    Image.new("RGBA", (64, 64), (13, 24, 56, 255)).save(
        os.path.join(skin, "livery.png"))


def apply(car_dir):
    """Write the standard Kunos car-layout files into an existing car_dir."""
    import features
    data = os.path.join(car_dir, "data")
    for name, text in (
        ("driver3d.ini", DRIVER3D), ("cameras.ini", CAMERAS),
        ("dash_cam.ini", DASH_CAM), ("escmode.ini", ESC_MODE),
        ("fuel_cons.ini", FUEL_CONS), ("throttle.lut", THROTTLE),
        ("blurred_objects.ini", BLURRED), ("proview_nodes.ini", PROVIEW),
        ("suspension_graphics.ini", SUSP_GRAPHICS),
    ):
        w(os.path.join(data, name), text)

    # Vanilla digital dash readouts, appended after the DRS LED sections.
    p = os.path.join(data, "digital_instruments.ini")
    cur = ""
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            cur = f.read()
    w(p, cur.rstrip() + "\n" + DASH_EXTRA)

    w(os.path.join(car_dir, "skins", "default", "ui_skin.json"), UI_SKIN)
    w(os.path.join(car_dir, "sfx", "GUIDs.txt"), GUIDS)
    w(os.path.join(car_dir, "sfx", "LEIA-ME-SOM.txt"), SOUND_NOTE)

    features.write_ksanim(os.path.join(car_dir, "animations", "steer.ksanim"),
                          STEER_NODE, steer_frames())
    _make_images(car_dir)

    # Kunos keeps logo.png at the car root as well as under ui/.
    src = os.path.join(car_dir, "ui", "logo.png")
    if os.path.exists(src):
        shutil.copyfile(src, os.path.join(car_dir, "logo.png"))

    print("  layout: Kunos-standard folders/files (driver3d, cameras, "
          "sfx/GUIDs, ui_skin, steer.ksanim, LOD-ready shadows)")
