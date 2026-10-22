"""flcodes - Family Link parent access code generator for authorised testing.

Modules
-------
``codes``    TOTP generation (HMAC-SHA1, 60 s step anchored to the hour);
``secrets``  shared secret discovery from payloads, captures and dumps;
``rea``      REA acquisition layer (api, har, paste, scan, adb);
``store``    passphrase encrypted local secret store (ChaCha20-Poly1305);
``report``   code export and secret-free experiment reports.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
