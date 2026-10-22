"""`verify` is the only objective proof that a generated code is functional.

A six digit string proves nothing on its own. These tests pin the semantics:
the tool must accept exactly the observations Google could have produced with
that key, reject everything else, distinguish several stored keys, and explain
a clock skew instead of silently "confirming".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "family-link-codes"))

from flcodes import codes as codes_mod  # noqa: E402
from flcodes import verify as verify_mod  # noqa: E402

KEY_A = "AItest-only-key-a.abcdefghij"  # NOT a real secret
KEY_B = "AItest-only-key-b.klmnopqrst"  # NOT a real secret
MOMENT = 1_792_684_800  # exact hour boundary


def test_matching_key_is_confirmed_and_wrong_key_is_not():
    observation = codes_mod.generate_code(KEY_A, MOMENT + 600)
    observations = [verify_mod.Observation(observation.code, MOMENT + 600, "pai")]

    good = verify_mod.verify_key(KEY_A, observations, label="pai")
    assert good.confirmed is True
    assert good.matched == 1 and good.total == 1
    assert good.results[0].expected == observation.code

    bad = verify_mod.verify_key(KEY_B, observations, label="outra")
    assert bad.confirmed is False
    assert bad.matched == 0
    assert bad.results[0].expected != observation.code
    # the failed result still tells which window it expected
    assert bad.results[0].window == (MOMENT, MOMENT + 3600)


def test_several_observations_must_all_match():
    observations = [
        verify_mod.Observation(codes_mod.generate_code(KEY_A, MOMENT + index * 3600).code,
                              MOMENT + index * 3600)
        for index in range(4)
    ]
    verification = verify_mod.verify_key(KEY_A, observations)
    assert verification.confirmed is True and verification.matched == 4

    observations[2] = verify_mod.Observation("000000", MOMENT + 7200)
    spoiled = verify_mod.verify_key(KEY_A, observations)
    assert spoiled.confirmed is False
    assert spoiled.matched == 3
    assert [r.matched for r in spoiled.results] == [True, True, False, True]


def test_observations_in_any_hour_of_the_window_agree():
    # the same code must verify for every moment inside the hour
    code = codes_mod.generate_code(KEY_A, MOMENT).code
    for offset in (0, 1, 59, 1800, 3599):
        verification = verify_mod.verify_key(
            KEY_A, [verify_mod.Observation(code, MOMENT + offset)]
        )
        assert verification.confirmed is True


def test_tolerance_reports_clock_skew_instead_of_failing():
    observation = verify_mod.Observation(
        codes_mod.generate_code(KEY_A, MOMENT - 3600).code, MOMENT
    )
    strict = verify_mod.verify_key(KEY_A, [observation])
    assert strict.confirmed is False

    tolerant = verify_mod.verify_key(KEY_A, [observation], tolerance_hours=1)
    assert tolerant.confirmed is True
    assert tolerant.results[0].delta_hours == -1


def test_tolerance_does_not_invent_matches():
    observation = verify_mod.Observation("123456", MOMENT)
    fake = verify_mod.verify_key(KEY_A, [observation], tolerance_hours=2)
    # a random code may collide, but not for every key/moment in the sample
    assert fake.total == 1
    forged = [
        verify_mod.verify_key(KEY_A, [verify_mod.Observation("000001", MOMENT + d * 3600)],
                              tolerance_hours=1)
        for d in range(6)
    ]
    assert not all(v.confirmed for v in forged)


def test_verify_keys_picks_exactly_one_from_a_set():
    observations = [verify_mod.Observation(codes_mod.generate_code(KEY_B, MOMENT).code, MOMENT)]
    keys = [
        {"secret": KEY_A, "label": "a", "id": "1"},
        {"secret": KEY_B, "label": "b", "id": "2"},
    ]
    verifications = verify_mod.verify_keys(keys, observations)
    confirmed = [v.label for v in verifications if v.confirmed]
    assert confirmed == ["b"]

    document = verify_mod.report_document(verifications, observations)
    assert document["confirmed"] is True
    assert document["confirmed_labels"] == ["b"]
    text = json.dumps(document)
    assert KEY_A not in text and KEY_B not in text


def test_observation_validation():
    with pytest.raises(ValueError):
        verify_mod.Observation("12345", MOMENT)  # five digits
    with pytest.raises(ValueError):
        verify_mod.Observation("abcdef", MOMENT)
    assert verify_mod.Observation(" 123456 ", MOMENT).code == "123456"


def test_parse_observations_csv():
    text = "timestamp,code,note\n1792684800,123456,pai\n2026-10-22T15:00:00Z,654321,mãe\n"
    observations = verify_mod.parse_observations(text)
    assert [o.code for o in observations] == ["123456", "654321"]
    assert observations[0].timestamp == MOMENT
    assert observations[1].note == "mãe"
    assert observations[1].timestamp == pytest.approx(
        codes_mod.parse_timestamp("2026-10-22T15:00:00Z")
    )


def test_parse_observations_json_and_errors():
    document = [
        {"at": "1792684800", "code": 123456},
        {"time": MOMENT + 3600, "codigo": "654321", "device": "child"},
    ]
    observations = verify_mod.parse_observations(json.dumps(document))
    assert [o.code for o in observations] == ["123456", "654321"]
    assert observations[1].note == "child"

    nested = {"observations": [{"timestamp": MOMENT, "value": "111111"}]}
    assert verify_mod.parse_observations(json.dumps(nested))[0].code == "111111"

    with pytest.raises(ValueError):
        verify_mod.parse_observations("")
    with pytest.raises(ValueError):
        verify_mod.parse_observations("nada,util\n1,2")
    with pytest.raises(ValueError):
        verify_mod.parse_observations(json.dumps([{"code": "123456"}]))
