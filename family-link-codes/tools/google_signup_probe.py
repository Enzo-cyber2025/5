"""Attempt one Google sign-up in a real browser, and report the exact wall.

The point is evidence, not magic: this drives the ordinary sign-up form exactly
as a person would, stops at the first screen it cannot fill honestly, and writes
down which screen that was. It does not solve captchas, does not use phone
numbers, does not spoof fingerprints or proxies — if Google demands any of those,
that is the answer, and the answer gets published.

    python3 tools/google_signup_probe.py --out-dir out/signup

Exit codes: 0 account created, 5 stopped at a wall (see the JSON), 1 error.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import string
import sys
import time

FIRST = ["Marina", "Tomas", "Helena", "Rafael", "Clara", "Otavio", "Bianca", "Igor"]
LAST = ["Almeida", "Ferreira", "Nogueira", "Barbosa", "Teixeira", "Moreira", "Prado"]

WALLS = [
    ("stuck-form", r"^$never^$"),
    ("phone", r"phone number|verify your phone|telefone|n[uú]mero de telefone|"
              r"we'?ll send a verification code|text message"),
    ("captcha", r"captcha|not a robot|recaptcha|prove you'?re not a robot|"
                r"unusual traffic|try again later|automated queries"),
    ("browser", r"couldn'?t sign you in|browser or app may not be secure|"
                r"this browser or app may not be secure|cookies"),
    ("blocked", r"couldn'?t create|não foi possível criar|can'?t be used to create|"
                r"not available|too many accounts|disabled"),
    ("terms", r"privacy and terms|i agree|concordo"),
    ("done", r"welcome|you'?re all set|bem-vindo|add a profile picture|"
             r"personalize your google experience"),
]

OPTION_WORDS = {
    "month": ["May", "Maio", "June", "Janeiro"],
    "gender": ["Rather not say", "Prefiro não informar", "Female", "Feminino", "Male"],
}
STEP_INPUTS = {
    "given": r"first name|nome",
    "family": r"last name|sobrenome",
    "user": r"username|nome de usuário",
    "pass": r"^password$|senha",
    "confirm": r"confirm",
}


def classify(text: str) -> str:
    lowered = text.lower()
    for name, pattern in WALLS:
        if re.search(pattern, lowered):
            return name
    return ""


def random_identity() -> dict:
    given = random.choice(FIRST)
    family = random.choice(LAST)
    suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(7))
    password = (
        random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
        + "".join(random.choice(string.ascii_lowercase) for _ in range(6))
        + "".join(random.choice("23456789") for _ in range(4))
        + random.choice("!@#$%^&*")
        + "Zq"
    )
    return {
        "given": given,
        "family": family,
        "username": f"{given.lower()}.{family.lower()}{suffix}",
        "email_domain": "gmail.com",
        "password": password,
        "birthday": {"month": "5", "day": "12", "year": "1991"},
        "gender": "1",
    }


def page_text(page) -> str:
    try:
        return page.inner_text("body")[:6000]
    except Exception:  # pragma: no cover - page torn down mid-read
        return ""


def fill_visible(page, identity: dict) -> list:
    """Fill every text field on the current step, by hint. Returns what was filled."""
    filled = []
    fields = page.locator("input:visible")
    count = fields.count()
    for index in range(count):
        field = fields.nth(index)
        try:
            kind = (field.get_attribute("type") or "text").lower()
            hint = " ".join(filter(None, [
                field.get_attribute("aria-label") or "",
                field.get_attribute("name") or "",
                field.get_attribute("id") or "",
                field.get_attribute("autocomplete") or "",
            ])).lower()
        except Exception:  # pragma: no cover - element detached
            continue
        if kind in {"hidden", "submit", "button", "checkbox", "radio"}:
            continue
        value = None
        if re.search(STEP_INPUTS["confirm"], hint) or "confirm" in hint:
            value = identity["password"]
        elif kind == "password" or re.search(STEP_INPUTS["pass"], hint):
            value = identity["password"]
        elif re.search(STEP_INPUTS["given"], hint):
            value = identity["given"]
        elif re.search(STEP_INPUTS["family"], hint):
            value = identity["family"]
        elif re.search(STEP_INPUTS["user"], hint) or kind == "email":
            value = identity["username"]
        if value is None:
            continue
        try:
            field.click(timeout=2000)
            field.fill(value, timeout=3000)
            filled.append({"hint": hint[:60], "kind": kind})
        except Exception:  # pragma: no cover - race with the wizard
            continue
    return filled


def _pick_option(page, label_pattern: str, options: list) -> bool:
    """The wizard's Month/Gender are Material comboboxes, not <select>.

    Click the box (role=combobox or the labelled div), then the option in the
    listbox that appears. Each strategy is tried because the markup changed
    between wizard revisions.
    """
    opened = False
    for locator in (
        lambda: page.get_by_role("combobox", name=re.compile(label_pattern, re.I)).first,
        lambda: page.locator(f'[aria-label*="{label_pattern}" i][role="combobox"], '
                             f'[jsname][role="combobox"]').first,
        lambda: page.get_by_label(re.compile(label_pattern, re.I)).first,
    ):
        try:
            element = locator()
            if element.count() == 0:
                continue
            element.click(timeout=3000)
            opened = True
            break
        except Exception:
            continue
    if not opened:
        return False
    page.wait_for_timeout(700)
    for name in options:
        for locator in (
            lambda: page.get_by_role("option", name=re.compile(f"^{name}$", re.I)).first,
            lambda: page.get_by_role("menuitem", name=re.compile(f"^{name}$", re.I)).first,
            lambda: page.locator(f'li:has-text("{name}")').first,
            lambda: page.locator(f'[role="option"]:has-text("{name}")').first,
        ):
            try:
                element = locator()
                if element.count() and element.is_visible():
                    element.click(timeout=3000)
                    return True
            except Exception:
                continue
    return False


def select_birthday(page, identity: dict) -> list:
    """Fill the birthday/gender screen; returns what actually got set."""
    done = []
    for label, value in (("Day", identity["birthday"]["day"]),
                         ("Year", identity["birthday"]["year"])):
        for locator in (
            lambda: page.get_by_label(re.compile(f"^{label}$", re.I)).first,
            lambda: page.get_by_placeholder(re.compile(f"^{label}$", re.I)).first,
            lambda: page.get_by_role("textbox", name=re.compile(label, re.I)).nth(0),
        ):
            try:
                element = locator()
                if element.count() == 0:
                    continue
                element.click(timeout=2000)
                element.fill(value, timeout=3000)
                done.append(label.lower())
                break
            except Exception:
                continue
    if _pick_option(page, "Month", OPTION_WORDS["month"]):
        done.append("month")
    if _pick_option(page, "Gender", OPTION_WORDS["gender"]):
        done.append("gender")
    return done


def click_next(page) -> bool:
    for label in ("Next", "Avançar", "Próxima", "Próximo", "I agree", "Concordo",
                  "Create account", "Criar conta", "Save", "Continuar"):
        try:
            button = page.get_by_role("button", name=re.compile(label, re.I)).first
            if button.count() and button.is_visible():
                button.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


def run(out_dir: pathlib.Path, headless: bool) -> int:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    identity = random_identity()
    steps = []
    created = False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(
            "https://accounts.google.com/signup/v2/createaccount"
            "?flowName=GlifWebSignIn&flowEntry=SignUp&hl=en",
            wait_until="domcontentloaded", timeout=60000,
        )
        page.wait_for_timeout(4000)

        previous = ""
        stuck = 0
        for attempt in range(1, 11):
            page.screenshot(path=str(out_dir / f"step-{attempt:02d}.png"), full_page=True)
            text = page_text(page)
            (out_dir / f"step-{attempt:02d}.txt").write_text(text, encoding="utf-8", errors="replace")
            verdict = classify(text)
            filled = fill_visible(page, identity)
            picked = select_birthday(page, identity)
            clicked = click_next(page)
            steps.append({
                "step": attempt,
                "verdict": verdict,
                "filled": filled,
                "picked": picked,
                "clicked_next": clicked,
                "heading": text.strip().splitlines()[0][:120] if text.strip() else "",
            })
            print(f"step {attempt}: verdict={verdict or '-'} filled={len(filled)} next={clicked}")

            if verdict == "done":
                created = True
                break
            if verdict in {"phone", "captcha", "browser", "blocked"}:
                break
            # A screen that keeps asking the same thing is a form we cannot fill;
            # three identical rounds is enough to call it.
            stuck = stuck + 1 if text == previous else 0
            previous = text
            if stuck >= 2:
                steps[-1]["verdict"] = "stuck-form"
                print(f"step {attempt}: the same screen keeps asking "
                      f"({steps[-1]['heading'][:60]!r}); stopping here")
                break
            page.wait_for_timeout(4000)

        page.screenshot(path=str(out_dir / "final.png"), full_page=True)
        (out_dir / "final.txt").write_text(page_text(page), encoding="utf-8", errors="replace")
        context.close()
        browser.close()

    last = steps[-1]["verdict"] if steps else ""
    result = {
        "created": created,
        "verdict": "created" if created else (last or "unknown"),
        "email": f"{identity['username']}@{identity['email_domain']}" if created else "",
        "steps": steps,
    }
    if created:
        result["password"] = identity["password"]
        (out_dir / "credentials.json").write_text(
            json.dumps({"email": result["email"], "password": identity["password"]}), encoding="utf-8")
        (out_dir / "credentials.json").chmod(0o600)

    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("created", "verdict", "email")}, indent=2))
    print(f"artifacts: {out_dir}")
    return 0 if created else 5


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="out/signup")
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args(argv)
    random.seed(time.time_ns())
    out_dir = pathlib.Path(args.out_dir)
    try:
        return run(out_dir, headless=not args.headful)
    except Exception as exc:  # pragma: no cover - network/browser failures
        message = f"{type(exc).__name__}: {exc}"
        print(f"probe failed: {message}", file=sys.stderr)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(json.dumps({
            "created": False, "verdict": "probe-error", "email": "",
            "error": message[:2000], "steps": [],
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
