"""Turn the sign-up probe's result.json into a job summary and an annotation.

Kept out of the workflow file on purpose: a heredoc inside `run: |` is how the
earlier job broke its own YAML.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

MEANING = {
    "phone": "Google demanded a phone number — that is the wall the tool will not fake.",
    "captcha": "Google served an anti-bot check — solving it is out of scope, by design.",
    "browser": "Google refused the browser/session itself (not a credential problem).",
    "blocked": "Google refused to create the account from this network.",
    "terms": "The wizard stopped on the terms screen; the form never advanced.",
    "done": "An account was created.",
    "created": "An account was created.",
    "unknown": "The probe did not get a verdict (page never loaded?).",
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="out/signup")
    parser.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.dir)
    result_path = directory / "result.json"
    lines = ["### Sign-up probe", ""]
    created = False

    if not result_path.exists():
        lines.append("- the probe produced no result; the browser never got a page")
        verdict = "unknown"
    else:
        data = json.loads(result_path.read_text())
        verdict = data.get("verdict", "unknown")
        created = bool(data.get("created")) or verdict in {"done", "created"}
        lines.append(f"- verdict: **{verdict}** — {MEANING.get(verdict, 'see the screenshots')}")
        if data.get("email"):
            lines.append(f"- account: `{data['email']}` (password in the artifact, 0600)")
        lines.append("")
        lines.append("| step | what the page said | fields filled | advanced |")
        lines.append("|---|---|---|---|")
        for step in data.get("steps", []):
            lines.append(f"| {step['step']} | `{step['verdict'] or 'form filled'}` "
                         f"| {len(step['filled'])} | {step['clicked_next']} |")
        if (directory / "credentials.json").exists():
            lines.append("")
            lines.append("**An account exists.** Download the `signup-account` artifact, then:")
            lines.append("")
            lines.append("```bash")
            lines.append("FLCODES_GPLAY_EMAIL=$(python3 -c \"import json;print(json.load(open('credentials.json'))['email'])\") \\")
            lines.append("FLCODES_GPLAY_PASSWORD=$(python3 -c \"import json;print(json.load(open('credentials.json'))['password'])\") \\")
            lines.append("  bash family-link-codes/tools/play_run.sh")
            lines.append("```")

    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write(text)

    if created:
        print("::warning title=account-created::the probe created an account; download the signup-account artifact")
    else:
        print(f"::warning title=signup-wall::Google stopped the sign-up at: {verdict}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
