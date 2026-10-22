"""The Family Link parent access code must match an independent TOTP oracle.

The generator is the core of the tool: if the counter, the key bytes or the
truncation are wrong the code is simply rejected by the device. The oracle in
this file is written from RFC 4226/6238 directly (HMAC-SHA1 over the big endian
counter, dynamic truncation, mod 1e6) plus the hour anchoring that Family Link
uses, so a change in the implementation cannot silently agree with itself.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "family-link-codes"))

from flcodes import codes  # noqa: E402

SEED = "AItest-only-shared-secret.abcdefghij"  # NOT a real secret


def oracle(secret: str, timestamp: int, key_mode: str = "raw") -> str:
    """Independent implementation: hour anchored 60 s TOTP, HMAC-SHA1."""
    if key_mode == "base32":
        key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    else:
        key = secret.encode("utf-8")
    hour_start = (timestamp // 3600) * 3600
    counter = hour_start // 60
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{number % 1000000:06d}"


def test_matches_independent_oracle_on_random_moments():
    rng = random.Random(20261022)
    moments = [rng.randrange(1_500_000_000, 1_900_000_000) for _ in range(400)]
    for moment in moments:
        expected = oracle(SEED, moment)
        assert codes.generate_code(SEED, moment).code == expected


def test_matches_oracle_across_hour_boundaries():
    base = 1_700_002_800  # exact hour boundary
    for delta in (-3600, -3599, -61, -60, -1, 0, 1, 59, 60, 3599, 3600):
        moment = base + delta
        assert codes.generate_code(SEED, moment).code == oracle(SEED, moment)


def test_code_is_stable_inside_the_hour_and_changes_on_the_hour():
    start = 1_700_002_800
    codes_in_hour = {codes.generate_code(SEED, start + offset).code for offset in range(0, 3600, 137)}
    assert len(codes_in_hour) == 1
    assert codes.generate_code(SEED, start - 1).code != codes.generate_code(SEED, start).code
    assert codes.generate_code(SEED, start + 3599).code != codes.generate_code(SEED, start + 3600).code


def test_window_covers_exactly_one_hour_and_is_contiguous():
    previous_end = None
    for hour_index in range(24):
        moment = 1_700_000_000 + hour_index * 3600
        code = codes.generate_code(SEED, moment)
        assert code.valid_to - code.valid_from == codes.CODE_VALIDITY_SECONDS
        assert code.valid_from <= moment < code.valid_to
        assert code.counter == code.valid_from // 60
        if previous_end is not None:
            assert code.valid_from == previous_end
        previous_end = code.valid_to


def test_code_is_six_digits_and_depends_on_the_secret():
    moment = 1_700_000_000
    first = codes.generate_code(SEED, moment).code
    second = codes.generate_code(SEED + "x", moment).code
    assert len(first) == 6 and first.isdigit()
    assert first != second
    assert any(
        len({codes.generate_code(f"{SEED}{suffix}", moment).code for suffix in "abcdefghij"}) > 5
        for _ in range(1)
    )


def test_half_hour_timezone_offset_moves_the_boundary():
    moment = 1_700_002_800
    plain = codes.generate_code(SEED, moment)
    shifted = codes.generate_code(SEED, moment, offset_minutes=330)  # UTC+05:30
    assert shifted.valid_from == moment - 1800  # :30 boundary in UTC
    assert shifted.valid_from != plain.valid_from
    assert shifted.valid_to - shifted.valid_from == 3600
    # 30 minutes later the shifted schedule rolls over while the plain one does not
    later = codes.generate_code(SEED, moment + 1800, offset_minutes=330)
    assert later.valid_from == moment + 1800
    assert codes.generate_code(SEED, moment + 1800).valid_from == plain.valid_from


def test_secret_normalisation_accepts_real_world_pastes():
    assert codes.normalize_secret(f'  "{SEED}"  ') == SEED
    assert codes.normalize_secret(f"secret={SEED}") == SEED
    uri = f"otpauth://totp/FamilyLink?secret={SEED}&period=3600"
    assert codes.normalize_secret(uri) == SEED
    assert codes.normalize_secret("") == ""
    with pytest.raises(ValueError):
        codes.secret_key("   ")


def test_encoding_modes_are_distinct_and_validated():
    # a real Family Link secret is raw, even when its characters are base32-ish
    family_link = "AITESTONLY" + "2" * (-len("AITESTONLY") % 8)
    assert len(family_link) % 8 == 0 and family_link.startswith("AI")
    assert codes.secret_key(family_link) == family_link.encode()
    assert codes.secret_key(family_link, encoding="raw") == family_link.encode()
    assert codes.secret_key(family_link, encoding="base32") != family_link.encode()

    # an explicitly base32 secret is decoded, and matches the oracle in that mode
    base32_secret = "MZXW6YTBOI======"
    assert codes.secret_key(base32_secret) == b"foobar"
    assert codes.secret_key(base32_secret, encoding="raw") == base32_secret.encode()
    assert codes.generate_code(base32_secret, 1_700_000_000, encoding="base32").code == oracle(
        base32_secret, 1_700_000_000, key_mode="base32"
    )
    with pytest.raises(ValueError):
        codes.secret_key("not-base32!", encoding="base32")
    with pytest.raises(ValueError):
        codes.secret_key(SEED, encoding="hex")


def test_day_generation_covers_every_hour_once():
    day = dt.date(2026, 10, 22)
    tz = dt.timezone(dt.timedelta(hours=-3))  # America/Sao_Paulo, no DST since 2019
    pairs = codes.codes_for_day(SEED, day, tz=tz)
    assert 24 <= len(pairs) <= 25
    local_dates = {moment.astimezone(tz).date() for moment, _code in pairs}
    assert local_dates == {day}
    assert len({code.valid_from for _moment, code in pairs}) == len(pairs)
    for moment, code in pairs:
        assert code.valid_from <= int(moment.timestamp()) < code.valid_to


def test_timestamp_parsing_accepts_epoch_and_iso():
    assert codes.parse_timestamp("1700002800") == 1_700_002_800
    iso = "2026-10-22T15:00:00+00:00"
    assert codes.parse_timestamp(iso) == dt.datetime.fromisoformat(iso).timestamp()
    assert codes.parse_timestamp("2026-10-22T15:00:00Z") == codes.parse_timestamp(iso)
    with pytest.raises(ValueError):
        codes.parse_timestamp("not a timestamp")
    with pytest.raises(ValueError):
        codes.parse_timestamp("  ")


def test_code_record_is_json_safe_and_never_holds_the_secret():
    code = codes.generate_code(SEED, 1_700_000_000)
    record = code.as_dict()
    assert set(record) == {"code", "valid_from", "valid_to", "counter"}
    assert SEED not in repr(record)
    assert isinstance(code.seconds_remaining, int)
