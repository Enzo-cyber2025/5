"""What the Play Store path needs from an account, checked before the boot.

The tool does not create Google accounts and never will: sign-up requires a
phone number, Google's anti-bot checks and the ToS all say no. What this module
does is the other half of the job — say, in twenty seconds and without booting
an emulator, whether the identity you supplied can actually sign the Play Store
in, and what to do when it cannot.
"""

from __future__ import annotations

import json
import os

FAIL = "fail"
WARN = "warn"
OK = "ok"


class Finding:
    """One line of the preflight, with the fix attached to it."""

    __slots__ = ("level", "message", "fix")

    def __init__(self, level: str, message: str, fix: str = "") -> None:
        self.level = level
        self.message = message
        self.fix = fix

    def as_dict(self) -> dict:
        return {"level": self.level, "message": self.message, "fix": self.fix}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Finding({self.level!r}, {self.message!r})"


PLACEHOLDER_HINTS = (
    "example.com", "example.org", "your@", "you@", "email@", "user@",
    "test@test", "changeme", "placeholder",
)
WEAK_PASSWORDS = ("password", "changeme", "123456", "qwerty", "secret", "test1234")


def _looks_like_placeholder(email: str) -> bool:
    lowered = email.strip().lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


def check(email: str | None = None, password: str | None = None) -> list[Finding]:
    """Judge the credentials without touching the network."""
    email = (email if email is not None else os.environ.get("FLCODES_GPLAY_EMAIL", "")).strip()
    password = password if password is not None else os.environ.get("FLCODES_GPLAY_PASSWORD", "")

    findings: list[Finding] = []

    if not email:
        findings.append(Finding(
            FAIL, "FLCODES_GPLAY_EMAIL is not set",
            "set it as a repository secret: bash tools/setup_play_secrets.sh"))
    elif "@" not in email or "." not in email.split("@")[-1]:
        findings.append(Finding(
            FAIL, f"{email!r} is not an email address",
            "the store signs in with the full Google address, not a username"))
    elif _looks_like_placeholder(email):
        findings.append(Finding(
            FAIL, f"{email!r} looks like a placeholder",
            "put the real address of the throwaway account here"))
    else:
        findings.append(Finding(OK, f"email: {email}"))

    if not password:
        findings.append(Finding(
            FAIL, "FLCODES_GPLAY_PASSWORD is not set",
            "the same secret pair as the email; see `flcodes account howto`"))
    elif len(password) < 8:
        findings.append(Finding(
            FAIL, "the password is shorter than 8 characters, no Google account accepts it",
            "check for a truncated copy (the shell eats `$` and `!`)"))
    elif password.strip().lower() in WEAK_PASSWORDS:
        findings.append(Finding(
            FAIL, "the password is a placeholder",
            "put the real one"))
    elif any(ch in password for ch in "$`\\"):
        findings.append(Finding(
            WARN, "the password contains a shell metacharacter ($ ` \\)",
            "quote it when exporting, or the shell will mangle it before gh sees it"))
    else:
        findings.append(Finding(OK, "password: set"))

    findings.append(Finding(
        WARN, "2-step verification blocks the emulator sign-in",
        "use an account with 2SV off, or one whose sign-in was already cleared "
        "on a real device; the store answers 'Verificar é você' otherwise"))
    findings.append(Finding(
        WARN, "a brand-new account is often challenged by device check",
        "sign in once on a phone/tablet first, wait a day, then use it here"))
    findings.append(Finding(
        OK, "the account needs nothing else: no card, no subscription, no Play credit"))

    return findings


def blocked(findings: list[Finding]) -> bool:
    return any(item.level == FAIL for item in findings)


def render(findings: list[Finding]) -> str:
    marks = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}
    lines = [f"{marks[item.level]} {item.message}" for item in findings]
    if blocked(findings):
        lines.append("")
        lines.append("verdict: the Play Store job would fail. Nothing was booted.")
        for item in findings:
            if item.fix:
                lines.append(f"  - {item.fix}")
    else:
        lines.append("")
        lines.append("verdict: usable. The job can sign the store in.")
    return "\n".join(lines)


def as_json(findings: list[Finding]) -> str:
    return json.dumps(
        {"usable": not blocked(findings),
         "findings": [item.as_dict() for item in findings]},
        indent=2, ensure_ascii=False)


HOWTO = """\
Uma conta só para o teste, sem violar nada

O que a ferramenta NÃO faz: criar conta Google. O cadastro exige telefone,
passa por anti-bot e é proibido pelos termos do Google — automatizar isso dá
conta banida no meio do experimento e resultado que não vale.

O que funciona, em ordem de esforço:

1. Conta descartável sua (3 minutos, caminho mais rápido)
   a. Abra uma janela anônima e crie a conta em accounts.google.com/signup.
   b. Use um número que você já tenha (o Google pede um para validar) e
      desligue a verificação em duas etapas depois do primeiro login.
   c. Entre nessa conta uma vez em um celular/tablet de verdade e abra a Play
      Store; espere ~1 dia. Conta recém-criada costuma cair em "Verificar é
      você" quando o login vem de um emulador.
   d. Publique as duas credenciais como secrets (nunca no chat, nunca em
      commit):
         bash family-link-codes/tools/setup_play_secrets.sh
      O script lê FLCODES_GPLAY_EMAIL/FLCODES_GPLAY_PASSWORD do seu ambiente,
      confere a forma, grava via `gh secret set` e não imprime a senha.

2. Conta que você já tem e não usa mais
   Melhor que a 1: já passou pelo device check. Só não use a conta principal —
   o experimento instala e desinstala apps e mexe em perfis.

3. Identidade criada por um admin, se você já tem domínio
   Cloud Identity Free / Workspace: o admin cria o usuário pela Directory API
   (users.insert), com 2SV desligável na política. É o único jeito de criar
   identidade Google por automação de forma legítima — e exige um domínio
   verificado seu, o que não é o caso aqui.

4. Nenhuma das anteriores: o teste segue sem Play Store
   O APK real 2.105 é o mesmo build publicado, já baixado e verificado por
   assinatura (sha256 ee2e1349…) sem credencial nenhuma; o job `play-store` é
   o único que fica de fora, e ele diz isso no PR em vez de fingir sucesso.

Depois de publicar os secrets, o job roda sozinho no próximo push:
  gh workflow run flcodes-emulator.yml     (ou simplesmente git push)
"""


def howto() -> str:
    return HOWTO
