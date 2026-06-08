from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


class Company_user(models.Model):
    company_name = models.CharField(max_length=100)
    gst_number = models.CharField(max_length=24, unique=True)
    email = models.CharField(max_length=50, unique=True)
    mobile = models.BigIntegerField()
    password = models.CharField(max_length=3128)
    company_profile_status = models.BooleanField(default=False)
    owner_login_id = models.CharField(max_length=50, default="admin")
    owner_password = models.CharField(max_length=512, blank=True, default="")

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def set_owner_password(self, raw_password):
        self.owner_password = make_password(raw_password)

    def check_owner_password(self, raw_password):
        if (self.owner_password or "").startswith("pbkdf2_sha256$"):
            return check_password(raw_password, self.owner_password)
        return self.check_password(raw_password)

    def effective_owner_login_id(self) -> str:
        return (self.owner_login_id or "admin").strip().lower()

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.company_name


class Company_profile(models.Model):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)

    pan_number = models.CharField(max_length=10, unique=True)

    address = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=20, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    pincode = models.CharField(max_length=6, blank=True, null=True)
    logo = models.FileField(upload_to="company_logos/", blank=True, null=True)

    def __str__(self):
        return str(self.company_id)


class CompanySecuritySettings(models.Model):
    company = models.OneToOneField(
        Company_user,
        on_delete=models.CASCADE,
        related_name="security_settings",
    )
    ip_whitelist_enabled = models.BooleanField(default=False)
    office_hours_enabled = models.BooleanField(default=False)
    office_start = models.TimeField(default="10:00")
    office_end = models.TimeField(default="19:00")
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    working_days = models.CharField(max_length=20, default="0,1,2,3,4,5,6")
    after_hours_grant_minutes = models.PositiveIntegerField(default=120)
    pdf_password_inside = models.CharField(max_length=512, blank=True, default="")
    pdf_password_outside = models.CharField(max_length=512, blank=True, default="")
    # Fernet-encrypted open password (used when building password-protected PDF files)
    pdf_open_inside_enc = models.TextField(blank=True, default="")
    pdf_open_outside_enc = models.TextField(blank=True, default="")
    # When True, every downloaded PDF uses the outside password (even at office) so shared files stay protected at home.
    pdf_files_always_use_outside_password = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_pdf_password_inside(self, raw_password: str):
        from erp.utils.pdf_protection import encrypt_pdf_secret

        if raw_password:
            self.pdf_password_inside = make_password(raw_password)
            self.pdf_open_inside_enc = encrypt_pdf_secret(raw_password)
        else:
            self.pdf_password_inside = ""
            self.pdf_open_inside_enc = ""

    def set_pdf_password_outside(self, raw_password: str):
        from erp.utils.pdf_protection import encrypt_pdf_secret

        if raw_password:
            self.pdf_password_outside = make_password(raw_password)
            self.pdf_open_outside_enc = encrypt_pdf_secret(raw_password)
        else:
            self.pdf_password_outside = ""
            self.pdf_open_outside_enc = ""

    def get_pdf_open_password(self, zone: str) -> str:
        from erp.utils.pdf_protection import decrypt_pdf_secret

        token = self.pdf_open_inside_enc if zone == "inside" else self.pdf_open_outside_enc
        if not token:
            return ""
        try:
            return decrypt_pdf_secret(token)
        except Exception:
            return ""

    def check_pdf_password_inside(self, raw_password: str) -> bool:
        if not (self.pdf_password_inside or "").startswith("pbkdf2_sha256$"):
            return True
        return check_password(raw_password, self.pdf_password_inside)

    def check_pdf_password_outside(self, raw_password: str) -> bool:
        if not (self.pdf_password_outside or "").startswith("pbkdf2_sha256$"):
            return True
        return check_password(raw_password, self.pdf_password_outside)

    def pdf_password_required(self, zone: str) -> bool:
        if zone == "inside":
            return (self.pdf_password_inside or "").startswith("pbkdf2_sha256$")
        return (self.pdf_password_outside or "").startswith("pbkdf2_sha256$")

    def __str__(self):
        return f"Security settings for {self.company_id}"


class AllowedIP(models.Model):
    company = models.ForeignKey(
        Company_user,
        on_delete=models.CASCADE,
        related_name="allowed_ips",
    )
    label = models.CharField(max_length=100, blank=True)
    ip_address = models.CharField(max_length=45)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "ip_address"]

    def __str__(self):
        return self.label or self.ip_address


class Employee(models.Model):
    company = models.ForeignKey(
        Company_user,
        on_delete=models.CASCADE,
        related_name="employees",
    )
    username = models.CharField(max_length=50)
    display_name = models.CharField(max_length=100)
    password = models.CharField(max_length=512)
    is_active = models.BooleanField(default=True)
    perm_dashboard = models.BooleanField(default=True)
    perm_contract = models.BooleanField(default=False)
    perm_dispatch = models.BooleanField(default=True)
    perm_invoice_create = models.BooleanField(default=False)
    perm_invoice_view = models.BooleanField(default=True)
    perm_invoice_update = models.BooleanField(default=False)
    perm_gc_note = models.BooleanField(default=True)
    perm_reports = models.BooleanField(default=False)
    perm_masters = models.BooleanField(default=False)
    perm_summary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["company", "username"]]
        ordering = ["username"]

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.company_id})"

    def permissions_dict(self):
        return {
            "dashboard": self.perm_dashboard,
            "contract": self.perm_contract,
            "dispatch": self.perm_dispatch,
            "invoice_create": self.perm_invoice_create,
            "invoice_view": self.perm_invoice_view,
            "invoice_update": self.perm_invoice_update,
            "gc_note": self.perm_gc_note,
            "reports": self.perm_reports,
            "masters": self.perm_masters,
            "summary": self.perm_summary,
        }


class SecurityAuditEvent(models.Model):
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    IP_BLOCKED = "IP_BLOCKED"
    OFFICE_HOURS_BLOCKED = "OFFICE_HOURS_BLOCKED"
    DOWNLOAD_BLOCKED = "DOWNLOAD_BLOCKED"
    PRINT_ATTEMPT = "PRINT_ATTEMPT"
    HOTKEY_BLOCKED = "HOTKEY_BLOCKED"
    SESSION_EXPIRED_OFFICE_HOURS = "SESSION_EXPIRED_OFFICE_HOURS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PREVIEW_REQUESTED = "PREVIEW_REQUESTED"
    PREVIEW_APPROVED = "PREVIEW_APPROVED"
    PREVIEW_DENIED = "PREVIEW_DENIED"
    AFTER_HOURS_PREVIEW_BLOCKED = "AFTER_HOURS_PREVIEW_BLOCKED"
    LOCATION_PREVIEW_BLOCKED = "LOCATION_PREVIEW_BLOCKED"
    PDF_PASSWORD_FAILED = "PDF_PASSWORD_FAILED"
    PDF_PASSWORD_REVEALED = "PDF_PASSWORD_REVEALED"

    EVENT_TYPE_CHOICES = [
        (LOGIN_SUCCESS, "Login success"),
        (LOGIN_FAILED, "Login failed"),
        (LOGOUT, "Logout"),
        (IP_BLOCKED, "IP blocked"),
        (OFFICE_HOURS_BLOCKED, "Office hours blocked"),
        (DOWNLOAD_BLOCKED, "Download blocked"),
        (PRINT_ATTEMPT, "Print attempt"),
        (HOTKEY_BLOCKED, "Hotkey blocked"),
        (SESSION_EXPIRED_OFFICE_HOURS, "Session expired (office hours)"),
        (PERMISSION_DENIED, "Permission denied"),
        (PREVIEW_REQUESTED, "Preview permission requested"),
        (PREVIEW_APPROVED, "Preview permission approved"),
        (PREVIEW_DENIED, "Preview permission denied"),
        (AFTER_HOURS_PREVIEW_BLOCKED, "After-hours preview blocked"),
        (LOCATION_PREVIEW_BLOCKED, "Outside-location preview blocked"),
        (PDF_PASSWORD_FAILED, "PDF password failed"),
        (PDF_PASSWORD_REVEALED, "PDF password revealed (Super Admin)"),
    ]

    company = models.ForeignKey(
        Company_user,
        on_delete=models.CASCADE,
        related_name="security_audit_events",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=40, choices=EVENT_TYPE_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["company", "-created_at"],
                name="company_sec_company_0f3e0d_idx",
            ),
            models.Index(
                fields=["event_type", "-created_at"],
                name="company_sec_event_t_ee4b18_idx",
            ),
        ]

    def __str__(self):
        return f"{self.event_type} @ {self.created_at}"


class AfterHoursPreviewRequest(models.Model):
    KIND_OFFICE_HOURS = "office_hours"
    KIND_OUTSIDE_LOCATION = "outside_location"

    RESTRICTION_KIND_CHOICES = [
        (KIND_OFFICE_HOURS, "Outside office hours"),
        (KIND_OUTSIDE_LOCATION, "Outside office location"),
    ]

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (DENIED, "Denied"),
    ]

    company = models.ForeignKey(
        Company_user,
        on_delete=models.CASCADE,
        related_name="after_hours_preview_requests",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="after_hours_preview_requests",
    )
    restriction_kind = models.CharField(
        max_length=30,
        choices=RESTRICTION_KIND_CHOICES,
        default=KIND_OFFICE_HOURS,
    )
    document_type = models.CharField(max_length=40)
    document_label = models.CharField(max_length=255, blank=True)
    target_url_name = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    requested_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.CharField(max_length=255, blank=True)
    grant_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.employee.username} – {self.document_type} ({self.status})"

    def grant_is_active(self) -> bool:
        if self.status != self.APPROVED or not self.grant_expires_at:
            return False
        return self.grant_expires_at > timezone.now()
