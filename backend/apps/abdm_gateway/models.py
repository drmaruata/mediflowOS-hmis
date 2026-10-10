"""ABDM gateway models.

``ABHACallbackLog`` is the idempotency ledger for profile-share callbacks;
``ConsentEvent`` is the DPDP consent record those callbacks create (ABD-011).

Data minimisation (architecture doc section 8.4): the shared profile is written
once, to ``ABHACallbackLog.profile`` — a legacy column that predates the rule —
and is deliberately *not* copied into ``ConsentEvent``. That table holds the fact
and provenance of the consent (which patient, when, from which source app, for
what purpose, at which facility) plus ``raw_profile_hash``, a one-way digest
tying the record to the payload it came from. It has no name, ABHA, address or
demographic column, so a dump of it cannot become a patient register.
"""
import uuid

from django.db import models
from django.utils import timezone


class ABHACallbackLog(models.Model):
    """Idempotent log of ABDM profile-share callbacks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    request_id = models.CharField(max_length=128, unique=True, db_index=True)
    facility_abdm_id = models.CharField(max_length=64, db_index=True)
    ip = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    profile = models.JSONField(null=True)
    matched_patient_id = models.UUIDField(null=True, blank=True)
    token_issued = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)  # ok | rejected | duplicate | ambiguous
    # ABD-012: the link token, sealed. The column holds a ``v1:<iv>:<ciphertext>``
    # AES-256-GCM envelope under the same key stream that encrypts patient
    # identifiers (common.crypto + ``PATIENT_FIELDS_KEY``); the plaintext is
    # minted, stored here and never returned or logged. Width holds a v1 token
    # for the 43-character ``token_urlsafe(32)`` value with room to spare.
    # Nullable because existing rows were written before the token was stored,
    # and because a log row is created before the seal is written (expand-only).
    link_token_enc = models.CharField(max_length=255, null=True, blank=True)
    # ABD-009: when a scan matches several patients the callback links none of
    # them and queues for verification instead, and this column names the
    # candidates for the clerk who resolves it — a list of
    # ``{"patient_id": <uuid>, "reason": "demographic"}``. Data minimisation
    # (section 8.4): ids and a reason only, never a name, ABHA number or
    # demographic value, so this column cannot grow into a patient register.
    # Null on every other branch, exactly like ``link_token_enc`` above.
    match_candidates = models.JSONField(null=True)

    class Meta:
        db_table = "abdm.callback_log"
        indexes = [models.Index(fields=["tenant_id", "request_id"])]


class ConsentEvent(models.Model):
    """Record of a profile share granted through the gateway (ABD-011).

    The requirement names timestamp, source, purpose and facility; ``patient_id``
    and ``request_id`` say *whose* consent and *which* callback it came from, and
    ``raw_profile_hash`` binds the record to the exact payload without storing
    any of it (see the module docstring).

    ``(tenant_id, request_id)`` is unique on purpose. Idempotency is enforced by
    the view's early return on a replayed request ID, which happens before any
    write; this constraint is the second line of defence for a future code path
    that reaches the consent write twice. Two consent rows for one gateway
    request are two records of the same grant, and a DPDP audit cannot reconcile
    those.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    patient_id = models.UUIDField(db_index=True)
    request_id = models.CharField(max_length=128, db_index=True)
    source_app = models.CharField(max_length=64)
    purpose = models.CharField(max_length=64)
    facility_id = models.UUIDField(db_index=True)
    granted_at = models.DateTimeField(default=timezone.now, db_index=True)
    raw_profile_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "abdm.consent_event"
        indexes = [
            models.Index(fields=["tenant_id", "request_id"]),
            models.Index(fields=["tenant_id", "patient_id", "granted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "request_id"],
                name="abdm_consent_event_tenant_request_uniq",
            )
        ]

    def __str__(self) -> str:
        # Identifiers only: a consent row is audit material and no patient
        # attribute lives on this model to print.
        return f"ConsentEvent {self.request_id} ({self.source_app}/{self.purpose})"
