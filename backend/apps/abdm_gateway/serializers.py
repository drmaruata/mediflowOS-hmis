"""ABDM gateway serializers."""
from rest_framework import serializers
from .models import ABHACallbackLog


class ABHACallbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ABHACallbackLog
        fields = "__all__"
        # link_token_enc is server-written only (ABD-012): the gateway posts a
        # profile share, never a link token, and the plaintext value is not
        # accepted anywhere in the API. match_candidates is server-written for
        # the same reason (ABD-009): it is the callback log's own record of
        # which patients a scan could have been, never a gateway input.
        read_only_fields = [
            "id",
            "timestamp",
            "tenant_id",
            "link_token_enc",
            "match_candidates",
        ]


class ConsentEventAckSerializer(serializers.Serializer):
    """The consent event echoed back to the gateway.

    Only the four attributes the architecture doc names (timestamp, source,
    purpose, facility) — deliberately not ``raw_profile_hash``, and never any
    patient attribute, because :class:`~apps.abdm_gateway.models.ConsentEvent`
    holds none. The acknowledgement is the one part of this flow that proxies
    and access logs see.
    """

    timestamp = serializers.DateTimeField(source="granted_at")
    source_app = serializers.CharField()
    purpose = serializers.CharField()
    facility_id = serializers.UUIDField()


class ABHACallbackAckSerializer(serializers.Serializer):
    """Acknowledgement returned to the ABDM gateway.

    ``link_token`` is not a field and must not become one (ABD-012): the link
    token is minted, sealed into ``link_token_enc`` for care-context linking and
    discarded in plaintext. Echoing it would put a credential into a response
    body that every proxy and access log along the way keeps.
    """
    status = serializers.CharField()
    token = serializers.CharField(required=False, allow_null=True)
    request_id = serializers.CharField()
    patient_id = serializers.UUIDField(required=False, allow_null=True)
    consent_event = ConsentEventAckSerializer(required=False, allow_null=True)
