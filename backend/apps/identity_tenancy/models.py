"""Identity, tenancy and administration models (TEN-001 to TEN-011)."""
from django.db import models
import uuid


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    tier = models.CharField(max_length=32, default="standard")
    accreditation_profile = models.JSONField(default=list)  # e.g. ["NQAS-DH","NABH-6"]
    db_mode = models.CharField(max_length=16, default="shared")  # shared | dedicated
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity.tenant"


class Facility(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="facilities", db_index=True)
    name = models.CharField(max_length=200)
    level = models.CharField(max_length=64)  # District Hospital, CHC, PHC...
    abdm_hip_id = models.CharField(max_length=64, null=True, blank=True)
    abdm_facility_id = models.CharField(max_length=64, null=True, blank=True)
    hfr_id = models.CharField(max_length=64, null=True, blank=True)
    abdm_registration_status = models.CharField(max_length=32, default="pending")
    address = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity.facility"


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="departments", db_index=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="departments", db_index=True)
    name = models.CharField(max_length=120)
    opd_enabled = models.BooleanField(default=False)
    ipd_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "identity.department"


class Ward(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="wards", db_index=True)
    name = models.CharField(max_length=120)
    type_tag = models.CharField(max_length=64)  # Medical, Surgical, Maternity, Paediatric, ICU, SNCU, NRC
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "identity.ward"


class Bed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds", db_index=True)
    bed_number = models.CharField(max_length=32)
    functional = models.BooleanField(default=True)
    occupied = models.BooleanField(default=False)

    class Meta:
        db_table = "identity.bed"


class ServiceUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="service_units", db_index=True)
    name = models.CharField(max_length=120)
    type_tag = models.CharField(max_length=64)  # OT, Labour Room, Laboratory, Radiology, Pharmacy, Blood Bank, Mortuary, CSSD

    class Meta:
        db_table = "identity.service_unit"


class StaffPosition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="staff_positions", db_index=True)
    designation = models.CharField(max_length=120)
    specialty = models.CharField(max_length=120, null=True, blank=True)
    sanctioned = models.IntegerField(default=0)
    in_position = models.IntegerField(default=0)

    class Meta:
        db_table = "identity.staff_position"
