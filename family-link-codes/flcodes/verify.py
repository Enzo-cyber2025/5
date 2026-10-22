"""Objective functional check: does the generated code equal a real one?

Generating six digits proves nothing by itself. The only offline proof that the
key, the algorithm and the *code validity* are right is a **code that Google
actually produced** for that key: read the parent access code in the Family Link
app (parent phone) or on the child device's lock screen, note the minute, and
compare.

`verify` mirrors Chromium's own validation loop
(`Authenticator::ValidateInRange`): it walks generation timestamps at the 1
minute granularity inside ``+/- drift`` around the observation and accepts a
match there. When the code validity (TTL) is unknown or wrong, it is discovered
from the observation itself (:func:`flcodes.codes.discover_validity`), which is
how the 600 s value in Google's own test data is reproduced.

A match proves:

* the shared secret is the right one for that family;
* the key bytes, the bucket counter and the truncation are right;
* the code validity in use is the one Google uses;
* the clock of this machine is aligned with Google's (within the drift).
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
    delta_seconds: int = 0
    window: tuple = ()
    validity: int = codes_mod.CODE_VALIDITY_SECONDS

    @property
    def delta_hours(self) -> int:
        """Whole hours of clock offset that the match needed (0 when exact)."""
        return int(self.delta_seconds // 3600)

    def as_dict(self) -> dict:
        return {
            "observed_at_utc": _iso(self.observation.timestamp),
            "observed_code": self.observation.code,
            "expected_code": self.expected,
            "matched": self.matched,
            "delta_seconds": self.delta_seconds,
            "validity": self.validity,
            "window_start_utc": _iso(self.window[0]) if self.window else None,
            "window_end_utc": _iso(self.window[1]) if self.window else None,
            "note": self.observation.note,
        }


@dataclass
class KeyVerification:
    label: str
    seed_id: str
    results: list = field(default_factory=list)
    validity: int = codes_mod.CODE_VALIDITY_SECONDS
    validity_discovered: bool = False
    validity_candidates: list = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        """More than one TTL reproduces the observations (e.g. 600 and 300)."""
        return len(self.validity_candidates) > 1

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
            "validity": self.validity,
            "validity_discovered": self.validity_discovered,
            "validity_candidates": list(self.validity_candidates),
            "ambiguous": self.ambiguous,
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


def _result_for(
    secret: str,
    observation: Observation,
    validity: int,
    drift: int,
    encoding: str,
    offset_minutes: int,
) -> ObservationResult:
    """Validate one observation exactly like Chromium's ValidateInRange does."""
    expected = codes_mod.generate_code(
        secret,
        observation.timestamp,
        offset_minutes=offset_minutes,
        encoding=encoding,
        validity=validity,
    )
    result = ObservationResult(
        observation=observation,
        expected=expected.code,
        matched=expected.code == observation.code,
        window=(expected.valid_from, expected.valid_to),
        validity=validity,
    )
    if result.matched or drift <= 0:
        return result
    # Walk generation timestamps inside +/- drift at the 1 minute granularity.
    drift = min(int(drift), 1800)
    start = int(observation.timestamp) - drift
    end = int(observation.timestamp) + drift
    cursor = (start // codes_mod.CODE_GRANULARITY_SECONDS) * codes_mod.CODE_GRANULARITY_SECONDS
    while cursor <= end:
        candidate = codes_mod.generate_code(
            secret,
            cursor,
            offset_minutes=offset_minutes,
            encoding=encoding,
            validity=validity,
        )
        if candidate.code == observation.code:
            result.matched = True
            result.delta_seconds = int(cursor - observation.timestamp)
            result.expected = candidate.code
            result.window = (candidate.valid_from, candidate.valid_to)
            return result
        cursor += codes_mod.CODE_GRANULARITY_SECONDS
    return result


def verify_key(
    secret: str,
    observations,
    label: str = "",
    seed_id: str = "",
    tolerance_hours: int = 0,
    encoding: str = "auto",
    offset_minutes: int = 0,
    validity: int | None = None,
    drift: int = 0,
    discover: bool = True,
) -> KeyVerification:
    """Compare every observation against this key."""
    observations = list(observations)
    if validities := ([validity] if validity else []):
        validity = validities[0]
    used = codes_mod.check_validity(validity or codes_mod.CODE_VALIDITY_SECONDS)
    # a legacy hour based tolerance is just a large clock drift
    drift = max(int(drift), int(tolerance_hours) * 3600)

    results = [
        _result_for(secret, observation, used, drift, encoding, offset_minutes)
        for observation in observations
    ]
    verification = KeyVerification(
        label=label or "key", seed_id=seed_id, results=results, validity=used
    )

    if discover and results and not all(result.matched for result in results):
        pairs = [(observation.code, observation.timestamp) for observation in observations]
        candidates = codes_mod.discover_validity(
            secret, pairs, encoding=encoding, offset_minutes=offset_minutes
        )
        verification.validity_candidates = candidates
        if used in candidates:
            # the configured TTL already fits: never "discover" a divisor of it
            verification.validity_candidates = [used]
        elif len(candidates) == 1:
            used = candidates[0]
            verification.validity = used
            verification.validity_discovered = True
            verification.results = [
                _result_for(secret, observation, used, drift, encoding, offset_minutes)
                for observation in observations
            ]
        elif candidates:
            # several TTLs fit the same observations; report, do not guess
            used = candidates[0]
            verification.validity = used
            verification.validity_discovered = True
            verification.results = [
                _result_for(secret, observation, used, drift, encoding, offset_minutes)
                for observation in observations
            ]
    return verification


def verify_keys(keys, observations, tolerance_hours: int = 0, encoding: str = "auto",
                drift: int = 0, discover: bool = True) -> list:
    """Verify a sequence of ``{"secret", "label", "id", "validity"}`` dicts."""
    return [
        verify_key(
            key["secret"],
            observations,
            label=key.get("label", ""),
            seed_id=key.get("id", ""),
            tolerance_hours=tolerance_hours,
            encoding=encoding,
            validity=key.get("validity"),
            drift=drift if drift else int(key.get("drift") or 0),
            discover=discover,
        )
        for key in keys
    ]


def report_document(verifications, observations, tolerance_hours: int = 0, drift: int = 0) -> dict:
    """Secret-free report of a verification run."""
    confirmed = [v for v in verifications if v.confirmed]
    return {
        "tool": "flcodes",
        "command": "verify",
        "created_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "tolerance_hours": tolerance_hours,
        "drift_seconds": drift,
        "observations": len(observations),
        "confirmed_labels": [v.label for v in confirmed],
        "confirmed": bool(confirmed),
        "keys": [v.as_dict() for v in verifications],
    }
