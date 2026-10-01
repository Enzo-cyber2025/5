"""Mission-level game interactions (menus, dialogs, skill picks).

Mirrors the in-game flow the project automates:
  1. reach the delivery area and STOP;
  2. the game opens a dialog — the AI must select "Onde você precisa dele?";
  3. park (parking brake on) — job complete;
  4. on level-up the game asks for a new skill — the AI picks a RANDOM one
     (by design: keeps the company profile varied).

Shared by the Windows bridge (real key macros) and the tests. The Android
port carries the same lists in SimWorld.java.
"""

DELIVERY_DIALOG = [
    "Entregar no pátio",
    "Onde você precisa dele?",
    "Cancelar",
]

SKILLS = [
    "ADR",
    "Cargas Frágeis",
    "Distâncias Longas",
    "Cargas de Alto Valor",
    "Economia de Combustível",
    "Comboios Pesados",
]

SKILL_EVERY_N_JOBS = 2


def delivery_selection(options=DELIVERY_DIALOG):
    """Index of the delivery option the AI must choose."""
    for i, opt in enumerate(options):
        if "onde você precisa" in opt.lower():
            return i
    return 0


def menu_key_sequence(target_idx):
    """Keys pressed to navigate a menu: N x down, then confirm."""
    return ["down"] * target_idx + ["ok"]


def pick_random_skill(rng):
    """Random skill index (by design — varied company profile)."""
    return int(rng.integers(0, len(SKILLS)))
