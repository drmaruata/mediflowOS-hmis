"""Quality OS models (QOS-001 to QOS-074)."""
from django.db import models
import uuid


class Framework(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)  # NQAS | NABH | CUSTOM
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "quality.framework"


class FrameworkEdition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE, related_name="editions")
    edition = models.CharField(max_length=64)  # e.g. "2025"
    effective_from = models.DateField()
    status = models.CharField(max_length=16, default="current")

    class Meta:
        db_table = "quality.framework_edition"


class IndicatorSourceDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE, related_name="source_documents")
    document_name = models.CharField(max_length=200)
    document_version = models.CharField(max_length=64)
    source_uri = models.URLField(null=True)
    content_hash = models.CharField(max_length=128)
    imported_at = models.DateTimeField(auto_now_add=True)
    licensing_status = models.CharField(max_length=32, default="pending")

    class Meta:
        db_table = "quality.source_document"


class IndicatorDef(models.Model):
    """Versioned indicator definition - the authoritative source record."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    edition = models.ForeignKey(FrameworkEdition, on_delete=models.CASCADE, related_name="indicators")
    source_document = models.ForeignKey(IndicatorSourceDocument, on_delete=models.PROTECT, related_name="indicators")
    source_code = models.CharField(max_length=64, null=True)
    source_sno = models.IntegerField(null=True)
    source_locator = models.CharField(max_length=128, null=True)
    standard_ref = models.CharField(max_length=64, null=True)  # e.g. PSQ 3a
    scope_type = models.CharField(max_length=32)  # overall | department | specialty
    scope_code = models.CharField(max_length=64, null=True)
    name = models.CharField(max_length=200)
    dimension = models.CharField(max_length=64, null=True)
    unit = models.CharField(max_length=32)
    direction = models.CharField(max_length=16, null=True)  # higher-is-better | lower-is-better
    periodicity = models.CharField(max_length=32)  # Monthly | Yearly | Continuous
    definition = models.TextField()
    numerator_spec = models.JSONField(null=True)
    denominator_spec = models.JSONField(null=True)
    formula_operator = models.CharField(max_length=64, null=True)
    calculation_mode = models.CharField(max_length=32, default="auto")  # auto | manual | hybrid
    sampling_required = models.BooleanField(default=False)
    sampling_method = models.CharField(max_length=128, null=True)
    sample_size_spec = models.JSONField(null=True)
    reporting_lag_days = models.IntegerField(null=True)
    source_of_data = models.CharField(max_length=200, null=True)
    system_capture_guide = models.TextField(null=True)
    applicability = models.JSONField(null=True)
    definition_version = models.IntegerField(default=1)
    status = models.CharField(max_length=16, default="active")

    class Meta:
        db_table = "quality.indicator_def"


class IndicatorValue(models.Model):
    """Snapshot of an indicator value for a period."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    facility_id = models.UUIDField(db_index=True)
    department_id = models.UUIDField(null=True, db_index=True)
    indicator = models.ForeignKey(IndicatorDef, on_delete=models.PROTECT, related_name="values")
    definition_version = models.IntegerField()
    period_start = models.DateField(db_index=True)
    period_end = models.DateField(db_index=True)
    numerator = models.FloatField(null=True)
    denominator = models.FloatField(null=True)
    value = models.FloatField(null=True)
    status = models.CharField(max_length=16, default="draft")  # draft | provisional | locked | superseded | n/a
    computed_at = models.DateTimeField(null=True)
    data_quality_flags = models.JSONField(default=list)

    class Meta:
        db_table = "quality.indicator_value"
        indexes = [models.Index(fields=["tenant_id", "indicator_id", "period_start"])]


class CAPA(models.Model):
    """Corrective and preventive action."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    source_type = models.CharField(max_length=32)  # alert | incident | audit | complaint | manual
    source_ref = models.CharField(max_length=128)
    title = models.CharField(max_length=400)
    severity = models.CharField(max_length=16)
    owner = models.UUIDField()
    due_date = models.DateField()
    status = models.CharField(max_length=32, default="raised")  # raised | rca | action_plan | implementation | verification | closed
    rca_method = models.CharField(max_length=32, null=True)  # 5-why | fishbone
    root_causes = models.JSONField(null=True)
    corrective_actions = models.JSONField(null=True)
    preventive_actions = models.JSONField(null=True)
    effectiveness_indicator_id = models.UUIDField(null=True)
    effectiveness_check_date = models.DateField(null=True)
    closed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "quality.capa"


class QualityFact(models.Model):
    """Append-only quality fact inputs from domain events."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    source_module = models.CharField(max_length=64)  # ipd | opd | emergency | icu | lis | ...
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quality.fact"
