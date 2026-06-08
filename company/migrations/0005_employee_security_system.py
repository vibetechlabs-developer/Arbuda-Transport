import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def set_default_owner_login_id(apps, schema_editor):
    Company_user = apps.get_model("company", "Company_user")
    for row in Company_user.objects.all():
        if not (row.owner_login_id or "").strip():
            row.owner_login_id = "admin"
            row.save(update_fields=["owner_login_id"])


def copy_password_to_owner_password(apps, schema_editor):
    Company_user = apps.get_model("company", "Company_user")
    for row in Company_user.objects.all():
        if not (row.owner_password or "").strip():
            row.owner_password = row.password
            row.save(update_fields=["owner_password"])


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0004_alter_company_user_mobile"),
    ]

    operations = [
        migrations.AddField(
            model_name="company_user",
            name="owner_login_id",
            field=models.CharField(default="admin", max_length=50),
        ),
        migrations.AddField(
            model_name="company_user",
            name="owner_password",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.RunPython(set_default_owner_login_id, migrations.RunPython.noop),
        migrations.RunPython(copy_password_to_owner_password, migrations.RunPython.noop),
        migrations.CreateModel(
            name="CompanySecuritySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ip_whitelist_enabled", models.BooleanField(default=False)),
                ("office_hours_enabled", models.BooleanField(default=False)),
                ("office_start", models.TimeField(default="10:00")),
                ("office_end", models.TimeField(default="19:00")),
                ("timezone", models.CharField(default="Asia/Kolkata", max_length=64)),
                ("working_days", models.CharField(default="0,1,2,3,4,5,6", max_length=20)),
                ("after_hours_grant_minutes", models.PositiveIntegerField(default=120)),
                ("pdf_password_inside", models.CharField(blank=True, default="", max_length=512)),
                ("pdf_password_outside", models.CharField(blank=True, default="", max_length=512)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="security_settings",
                        to="company.company_user",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(max_length=50)),
                ("display_name", models.CharField(max_length=100)),
                ("password", models.CharField(max_length=512)),
                ("is_active", models.BooleanField(default=True)),
                ("perm_dashboard", models.BooleanField(default=True)),
                ("perm_contract", models.BooleanField(default=False)),
                ("perm_dispatch", models.BooleanField(default=True)),
                ("perm_invoice_create", models.BooleanField(default=False)),
                ("perm_invoice_view", models.BooleanField(default=True)),
                ("perm_invoice_update", models.BooleanField(default=False)),
                ("perm_gc_note", models.BooleanField(default=True)),
                ("perm_reports", models.BooleanField(default=False)),
                ("perm_masters", models.BooleanField(default=False)),
                ("perm_summary", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="employees",
                        to="company.company_user",
                    ),
                ),
            ],
            options={
                "ordering": ["username"],
                "unique_together": {("company", "username")},
            },
        ),
        migrations.CreateModel(
            name="SecurityAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("LOGIN_SUCCESS", "Login success"),
                            ("LOGIN_FAILED", "Login failed"),
                            ("LOGOUT", "Logout"),
                            ("IP_BLOCKED", "IP blocked"),
                            ("OFFICE_HOURS_BLOCKED", "Office hours blocked"),
                            ("DOWNLOAD_BLOCKED", "Download blocked"),
                            ("PRINT_ATTEMPT", "Print attempt"),
                            ("HOTKEY_BLOCKED", "Hotkey blocked"),
                            ("SESSION_EXPIRED_OFFICE_HOURS", "Session expired (office hours)"),
                            ("PERMISSION_DENIED", "Permission denied"),
                            ("PREVIEW_REQUESTED", "Preview permission requested"),
                            ("PREVIEW_APPROVED", "Preview permission approved"),
                            ("PREVIEW_DENIED", "Preview permission denied"),
                            ("AFTER_HOURS_PREVIEW_BLOCKED", "After-hours preview blocked"),
                            ("LOCATION_PREVIEW_BLOCKED", "Outside-location preview blocked"),
                            ("PDF_PASSWORD_FAILED", "PDF password failed"),
                        ],
                        max_length=40,
                    ),
                ),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True)),
                ("path", models.CharField(blank=True, max_length=255)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="security_audit_events",
                        to="company.company_user",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_events",
                        to="company.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["company", "-created_at"], name="company_sec_company_0f3e0d_idx"),
                    models.Index(fields=["event_type", "-created_at"], name="company_sec_event_t_ee4b18_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AllowedIP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, max_length=100)),
                ("ip_address", models.CharField(max_length=45)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_ips",
                        to="company.company_user",
                    ),
                ),
            ],
            options={
                "ordering": ["label", "ip_address"],
            },
        ),
        migrations.CreateModel(
            name="AfterHoursPreviewRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "restriction_kind",
                    models.CharField(
                        choices=[
                            ("office_hours", "Outside office hours"),
                            ("outside_location", "Outside office location"),
                        ],
                        default="office_hours",
                        max_length=30,
                    ),
                ),
                ("document_type", models.CharField(max_length=40)),
                ("document_label", models.CharField(blank=True, max_length=255)),
                ("target_url_name", models.CharField(max_length=80)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("reason", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("denied", "Denied"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("reviewer_note", models.CharField(blank=True, max_length=255)),
                ("grant_expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="after_hours_preview_requests",
                        to="company.company_user",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="after_hours_preview_requests",
                        to="company.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-requested_at"],
            },
        ),
    ]
