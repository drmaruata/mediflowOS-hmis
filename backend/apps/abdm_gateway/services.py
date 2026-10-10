"""ABDM gateway services — resolving a shared profile to a patient (ABD-008, ABD-009).

The gateway hands over a profile it never checked against an identity
document, so "who is this?" has four honest answers: an exact ABHA match (a
strong identifier the scanning patient restated), a single demographic
candidate (weak evidence), several candidates (too weak to link anything), or
none (register provisional). This module answers that question and nothing
else; what each answer *means* for tokens, consent and the verification queue
is the callback view's business.
"""
from dataclasses import dataclass
from typing import Literal

from apps.patient_registry.models import Patient


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one shared profile inside one tenant.

    ``kind``:
      ``matched``    — exactly one patient; ``patient`` is set and ``matched_by``
                       records how strong the evidence was.
      ``candidates`` — several demographic matches; ``candidates`` holds them,
                       so linking any one of them would be a guess.
      ``none``       — nothing matched; the caller registers a provisional.

    ``matched_by`` exists because the two match strengths carry different
    standing: an exact ABHA match may link a record as-is, while a demographic
    match must leave that record in the verification queue. Re-deriving the
    strength in the view would mean a second ABHA probe there — the matching
    logic this module exists to hold in one place.
    """

    kind: Literal["matched", "candidates", "none"]
    patient: Patient | None = None
    candidates: tuple[Patient, ...] = ()
    matched_by: Literal["abha", "demographic"] | None = None


def resolve_profile(*, profile: dict, tenant_id: str) -> Resolution:
    """Match by ABHA number, then demographics (ABD-008, ABD-009).

    The ABHA probe crosses the REG-008 ``abha_number_idx`` digest via
    ``filter_by_abha`` — the gateway carries the plaintext number (the person
    scanned it), so exact-digest matching finds the encrypted row and never
    falls back to a ciphertext scan.

    The demographic search is deliberately weaker than
    :func:`apps.patient_registry.services.find_duplicates`: this answers "could
    this scan be one of our patients?" for the callback, not "should we warn
    the clerk?". Every probe is tenant-scoped from its first filter, so no
    result can ever cross a tenant boundary.
    """
    abha_number = profile.get("abhaNumber") or profile.get("healthId")
    if abha_number:
        try:
            return Resolution(
                kind="matched",
                patient=Patient.objects.filter_by_abha(tenant_id, abha_number).get(),
                matched_by="abha",
            )
        except Patient.DoesNotExist:
            pass

    # Candidate search by name + year of birth + gender
    demographics = profile.get("demographics") or {}
    name = demographics.get("name") or profile.get("name", "")
    year = demographics.get("yearOfBirth") or profile.get("yearOfBirth")
    gender = demographics.get("gender") or profile.get("gender")
    if name and year:
        candidates = Patient.objects.filter(
            tenant_id=tenant_id,
            demographics__name__icontains=name,
            demographics__year_of_birth=year,
        )
        if gender:
            candidates = candidates.filter(demographics__gender=gender)
        rows = list(candidates)
        if len(rows) == 1:
            return Resolution(
                kind="matched", patient=rows[0], matched_by="demographic"
            )
        if len(rows) >= 2:
            # ABD-009: several registrations fit the scan equally well, so the
            # resolution is "ask a human", not "pick one".
            return Resolution(kind="candidates", candidates=tuple(rows))
    return Resolution(kind="none")
