from __future__ import annotations

import re

# Standard Indian GSTIN format (15 chars) with checksum as per ISO 7064 (MOD 36,2)
GSTIN_REGEX = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)

_GSTIN_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_CHAR_TO_VAL = {c: i for i, c in enumerate(_GSTIN_CHARSET)}


def validate_gstin(gstin: str) -> bool:
    """
    Validate Indian GSTIN (Goods and Services Tax Identification Number).

    Rules:
    - Exactly 15 characters
    - Must match the official GSTIN pattern
    - Last character is a checksum using ISO 7064 MOD 36,2 on the first 14 chars
    """
    if not gstin:
        return False

    gstin = gstin.strip().upper()

    if not GSTIN_REGEX.match(gstin):
        return False

    data, check_char = gstin[:-1], gstin[-1]

    # ISO 7064 MOD 36,2 checksum implementation
    factor = 2
    total = 0
    modulus = 36

    for char in reversed(data):
        if char not in _GSTIN_CHAR_TO_VAL:
            return False
        code_point = _GSTIN_CHAR_TO_VAL[char]
        addend = factor * code_point

        # Sum of digits in base-36 representation
        addend = (addend // modulus) + (addend % modulus)
        total += addend

        factor = 1 if factor == 2 else 2

    remainder = total % modulus
    check_code_point = (modulus - remainder) % modulus
    expected_check_char = _GSTIN_CHARSET[check_code_point]

    return check_char == expected_check_char

