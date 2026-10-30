"""Shared test setup: make the ``flcodes`` package importable from the repo.

The package lives in ``family-link-codes/`` rather than at the root, and the CI
job runs plain ``pytest``. Putting the package on ``sys.path`` here means every
test file can simply ``from flcodes import ...`` with no environment setup.
"""
from __future__ import annotations

import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "family-link-codes"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
