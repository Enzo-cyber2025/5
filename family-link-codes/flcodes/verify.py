"""Objective functional check: does the generated code equal a real one?

Generating six digits proves nothing by itself. The only offline proof that the
key and the algorithm are right is a **code that Google actually produced** for
that key: read the parent access code in the Family Link app (parent phone) or
on the child device's lock screen, note the minute, and compare.

`verify` does exactly that comparison for every stored key and reports which one
reproduces the observation. A match proves:

* the shared secret is the right one for that family;
* the key bytes, the hour anchored counter and the truncation are right;
* the clock of this machine is aligned with Google's (within the tolerance).

A mismatch proves the opposite, and the report says which window was expected
so a clock skew can be ruled out with ``--tolerance-hours``.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
from dataclasses import dataclass, field

from . import codes as codes_mod

__all__ = [
    "Observation",
    "ObservationResult",
    "KeyVerification",
    "parse_observations",
    "verify_key",
    "verify_keys",
    "report_document",
]

_TIME_KEYS = ("timestamp", "time", "at", "when", "ts")
_CODE_KEYS = ("code", "codigo", "código", "parent_access_code", "value")


@dataclass
class Observation:
    """A code that Google showed at a known moment."""

    code: str
    timestamp: float
    note: str = ""

    def __post_init__(self) -> None:
        self.code = str(self.code).strip()
        if not self.code.isdigit() or len(self.code) != 6:
            raise ValueError(f"code must be six digits, got {self.code!r}")
        self.timestamp = float(self.timestamp)


@dataclass
class ObservationResult:
    observation: Observation
    expected: str
    matched: bool
    delta_hours: int = 0
    window: tuple = ()

    def as_dict(self) -> dict:
        return {
            "observed_at_utc": _iso(self.observation.timestamp),
            "observed_code": self.observation.code,
            "expected_code": self.expected,
            "matched": self.matched,
            "delta_hours": self.delta_hours,
            "window_start_utc": _iso(self.window[0]) if self.window else None,
            "window_end_utc": _iso(self.window[1]) if self.window else None,
            "note": self.observation.note,
        }


@dataclass
class KeyVerification:
    label: str
    seed_id: str
    results: list = field(default_factory=list)

    @property
    def matched(self) -> int:
        return sum(1 for result in self.results if result.matched)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def confirmed(self) -> bool:
        """Every observation reproduced by this key."""
        return self.total > 0 and self.matched == self.total

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "seed_id": self.seed_id,
            "matched": self.matched,
            "total": self.total,
            "confirmed": self.confirmed,
            "results": [result.as_dict() for result in self.results],
        }


def _iso(timestamp: float) -> str:
    return _dt.datetime.fromtimestamp(timestamp, _dt.timezone.utc).isoformat()


def _coerce_timestamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return codes_mod.parse_timestamp(str(value))


def _from_mapping(entry: dict) -> Observation:
    code = next(
        (entry[key] for key in _CODE_KEYS if entry.get(key) not in (None, "")),
        None,
    )
    when = next(
        (entry[key] for key in _TIME_KEYS if entry.get(key) not in (None, "")),
        None,
    )
    if code is None:
        raise ValueError("observation is missing a code")
    if when is None:
        raise ValueError("observation is missing a timestamp")
    note = str(entry.get("note") or entry.get("device") or "")
    return Observation(code=str(code), timestamp=_coerce_timestamp(when), note=note)


def parse_observations(text: str) -> list:
    """Parse observations from CSV (``timestamp,code``) or a JSON document."""
    if not text or not text.strip():
        raise ValueError("no observations in the input")
    stripped = text.strip()

    if stripped.startswith("["):
        document = json.loads(stripped)
        if not isinstance(document, list):
            raise ValueError("JSON observations must be a list")
        return [_from_mapping(entry) for entry in document]
    if stripped.startswith("{"):
        document = json.loads(stripped)
        entries = document.get("observations", document.get("codes", []))
        return [_from_mapping(entry) for entry in entries]

    observations = []
    for row in csv.DictReader(io.StringIO(stripped)):
        if not row:
            continue
        clean = {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
        try:
            observations.append(_from_mapping(clean))
        except ValueError:
            continue
    if not observations:
        raise ValueError("could not parse any observation (need timestamp and code)")
    return observations


def verify_key(
    secret: str,
    observations,
    label: str = "",
    seed_id: str = "",
    tolerance_hours: int = 0,
    encoding: str = "auto",
    offset_minutes: int = 0,
) -> KeyVerification:
    """Compare every observation against this key."""
    verification = KeyVerification(label=label or "key", seed_id=seed_id)
    tolerance = max(0, int(tolerance_hours))
    for observation in observations:
        expected = codes_mod.generate_code(
            secret, observation.timestamp, offset_minutes=offset_minutes, encoding=encoding
        )
        result = ObservationResult(
            observation=observation,
            expected=expected.code,
            matched=expected.code == observation.code,
            window=(expected.valid_from, expected.valid_to),
        )
        if not result.matched and tolerance:
            for delta in range(1, tolerance + 1):
                for sign in (-1, 1):
                    shifted = codes_mod.generate_code(
                        secret,
                        observation.timestamp + sign * delta * codes_mod.CODE_VALIDITY_SECONDS,
                        offset_minutes=offset_minutes,
                        encoding=encoding,
                    )
                    if shifted.code == observation.code:
                        result.matched = True
                        result.delta_hours = sign * delta
                        break
                if result.matched:
                    break
        verification.results.append(result)
    return verification


def verify_keys(keys, observations, tolerance_hours: int = 0, encoding: str = "auto") -> list:
    """Verify a sequence of ``{"secret", "label", "id"}`` dicts."""
    return [
        verify_key(
            key["secret"],
            observations,
            label=key.get("label", ""),
            seed_id=key.get("id", ""),
            tolerance_hours=tolerance_hours,
            encoding=encoding,
        )
        for key in keys
    ]


def report_document(verifications, observations, tolerance_hours: int = 0) -> dict:
    """Secret-free report of a verification run."""
    confirmed = [v for v in verifications if v.confirmed]
    return {
        "tool": "flcodes",
        "command": "verify",
        "created_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "tolerance_hours": tolerance_hours,
        "observations": len(observations),
        "confirmed_labels": [v.label for v in confirmed],
        "confirmed": bool(confirmed),
        "keys": [v.as_dict() for v in verifications],
    }
