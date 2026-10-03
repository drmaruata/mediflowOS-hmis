"""Management command to seed a test tenant, facility, and administrative user."""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.identity_tenancy.models import Tenant, Facility, Department, Role, UserMembership

class Command(BaseCommand):
    help = "Seeds initial tenant and admin user for local development"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command is only available when DEBUG=True.")

        password = os.environ.get("MEDIFLOW_SEED_ADMIN_PASSWORD")
        if not password:
            raise CommandError("Set MEDIFLOW_SEED_ADMIN_PASSWORD to create the admin user.")

        with transaction.atomic():
            # 1. Create a platform/admin role (not tenant-scoped)
            platform_role, _ = Role.objects.get_or_create(
                tenant=None,
                name="platform_admin",
                defaults={
                    "permissions": ["all"],
                    "allows_break_glass": True,
                    "require_mfa": False,  # Ease of dev
                }
            )

            # 2. Create the tenant
            tenant, _ = Tenant.objects.get_or_create(
                slug="test-hospital",
                defaults={
                    "name": "District Hospital / Main Campus",
                    "tier": "standard",
                    "accreditation_profile": ["NQAS-DH"]
                }
            )

            # 3. Create the facility
            facility, _ = Facility.objects.get_or_create(
                tenant=tenant,
                abdm_hip_id="HIP-TEST-001",
                defaults={
                    "name": "Main Campus",
                    "level": "District Hospital",
                }
            )

            # 4. Create an OPD department
            department, _ = Department.objects.get_or_create(
                tenant=tenant,
                name="General Medicine",
                defaults={
                    "facility": facility,
                    "opd_enabled": True,
                    "ipd_enabled": True,
                    "active": True,
                    "effective_from": "2026-01-01"
                }
            )

            # 5. Create an admin user account
            User = get_user_model()
            user = User.objects.filter(username="admin").first()
            if not user:
                user = User.objects.create_user(
                    username="admin",
                    password=password,
                    is_staff=True,
                    is_superuser=True
                )
                self.stdout.write(self.style.SUCCESS("Created user 'admin'"))

            # 6. Bind user to the platform role + tenant
            membership, created = UserMembership.objects.get_or_create(
                user=user,
                tenant=tenant,
                defaults={
                    "role": platform_role,
                    "active": True,
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS("Tenant membership created for 'admin'"))

            self.stdout.write(self.style.SUCCESS(
                f"Seed complete. Tenant: {tenant.slug}, Facility: {facility.abdm_hip_id}, User: admin"
            ))