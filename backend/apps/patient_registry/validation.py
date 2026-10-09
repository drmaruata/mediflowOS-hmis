"""Shared validation primitives for the patient registry.

The registration serializer (REG-007) and the duplicate detector (REG-003) must
agree on what a mobile number *is*: the serializer validates and canonicalises
the stored value, and the detector's database prefilter compares against that
same stored form. Keeping one implementation here is what stops the two from
drifting — they previously differed for a leading-zero 10-digit input.
"""
import re

#: Canonical stored mobile: 10-digit Indian national number, first digit 6-9.
#: Deliberately *not* ``+91``-anchored because the stored form is the bare
#: national number; a leading ``+91``/``91``/``0`` is stripped by
#: :func:`normalise_mobile` before the match.
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def normalise_mobile(value) -> str:
    """Reduce a mobile to its canonical bare 10-digit national form.

    Strips every non-digit, then a leading trunk ``0`` or a ``91`` country
    prefix, leaving the national number. ``"+91 98765 43210"``,
    ``"098765 43210"`` and ``"9876543210"`` all reduce to ``"9876543210"``.

    The stored shape must be canonical because the duplicate prefilter is a
    substring lookup on the *stored* value; a formatted row and a bare probe
    would not meet through it (REG-003). Callers validate the result with
    :data:`MOBILE_RE`.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits[-10:] if len(digits) > 10 else digits
