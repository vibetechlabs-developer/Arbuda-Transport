import ipaddress

from django.contrib import messages
from django.urls import resolve
from django.utils import timezone

from company.models import (
    AfterHoursPreviewRequest,
    AllowedIP,
    CompanySecuritySettings,
    Company_user,
    Employee,
    SecurityAuditEvent,
)


def get_session_company_id(request) -> int:
    """Return company id from session (company_info dict)."""
    info = request.session.get("company_info")
    if isinstance(info, dict):
        return int(info["company_id"])
    if isinstance(info, int):
        return info
    raise KeyError("company_info not in session")


def get_session_company(request) -> Company_user:
    return Company_user.objects.get(id=get_session_company_id(request))

# URL name -> permission key on Employee.permissions_dict()
URL_PERMISSION_MAP = {
    "dashboard": "dashboard",
    "new-contract-view": "contract",
    "new-contract-form": "contract",
    "update-contract-form": "contract",
    "dispatch-view": "dispatch",
    "dispatch-form": "dispatch",
    "dispatch-update": "dispatch",
    "view-dispatch-invoice": "invoice_view",
    "create-dispatch-invoice": "invoice_create",
    "update-dispatch-invoice": "invoice_update",
    "generate-invoice-pdf": "invoice_view",
    "download-generate-invoice-pdf": "invoice_view",
    "view-gc-note": "gc_note",
    "download-gc-pdf": "gc_note",
    "client-report-view": "reports",
    "outstanding-report-view": "reports",
    "download-report": "reports",
    "download-distance-master-pdf": "reports",
    "rate-master-view": "masters",
    "rout-view": "masters",
    "rout-update": "masters",
    "product-master-view": "masters",
    "summary-view": "summary",
    "generate-summary-pdf": "summary",
}

# Pages employees may hit without a module permission (security APIs, logout)
EMPLOYEE_EXEMPT_URL_NAMES = {
    "company-logout",
    "security-office-hours-status",
    "security-audit-beacon",
}

# PDF / preview endpoints that need Super Admin approval outside office hours
PDF_PREVIEW_URL_NAMES = {
    "generate-invoice-pdf",
    "download-generate-invoice-pdf",
    "download-gc-pdf",
    "generate-summary-pdf",
    "download-report",
    "download-our-report",
    "download-distance-master-pdf",
}

# Employee pages allowed outside office hours (no PDF preview without grant)
OUTSIDE_OFFICE_HOURS_ALLOWED_URL_NAMES = EMPLOYEE_EXEMPT_URL_NAMES | {
    "dashboard",
    "preview-permission-request",
    "preview-permission-my",
    "preview-permission-run",
    "pdf-access-verify",
}

# Employee pages allowed when IP is outside office network
OUTSIDE_LOCATION_ALLOWED_URL_NAMES = OUTSIDE_OFFICE_HOURS_ALLOWED_URL_NAMES

OWNER_ONLY_URL_NAMES = {
    "employee-manage",
    "employee-create",
    "employee-edit",
    "employee-deactivate",
    "security-settings",
    "security-audit-log",
    "preview-permission-manage",
    "company-profile",
    "company-update-profile",
    "internal-report",
    "download-our-report",
}

PDF_ZONE_INSIDE = "inside"
PDF_ZONE_OUTSIDE = "outside"
PDF_SESSION_TTL_MINUTES = 480


def get_user_role(request) -> str:
    return request.session.get("user_role", "owner")


def is_owner(request) -> bool:
    return get_user_role(request) == "owner"


def is_employee(request) -> bool:
    return get_user_role(request) == "employee"


def get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def get_or_create_security_settings(company: Company_user) -> CompanySecuritySettings:
    settings_obj, created = CompanySecuritySettings.objects.get_or_create(company=company)
    if created:
        ensure_default_pdf_passwords(settings_obj)
    elif not settings_obj.pdf_password_required(PDF_ZONE_INSIDE) and not settings_obj.pdf_password_required(
        PDF_ZONE_OUTSIDE
    ):
        ensure_default_pdf_passwords(settings_obj)
    return settings_obj


def ensure_default_pdf_passwords(settings_obj: CompanySecuritySettings) -> tuple[str, str]:
    """Create distinct inside/outside PDF open passwords if none exist."""
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    inside = "".join(secrets.choice(alphabet) for _ in range(10))
    outside = "".join(secrets.choice(alphabet) for _ in range(10))
    while outside == inside:
        outside = "".join(secrets.choice(alphabet) for _ in range(10))
    settings_obj.set_pdf_password_inside(inside)
    settings_obj.set_pdf_password_outside(outside)
    settings_obj.save(
        update_fields=[
            "pdf_password_inside",
            "pdf_password_outside",
            "pdf_open_inside_enc",
            "pdf_open_outside_enc",
        ]
    )
    return inside, outside


def pdf_password_status(settings_obj: CompanySecuritySettings) -> dict:
    return {
        "inside_set": settings_obj.pdf_password_required(PDF_ZONE_INSIDE),
        "outside_set": settings_obj.pdf_password_required(PDF_ZONE_OUTSIDE),
        "inside_revealable": bool(settings_obj.get_pdf_open_password(PDF_ZONE_INSIDE)),
        "outside_revealable": bool(settings_obj.get_pdf_open_password(PDF_ZONE_OUTSIDE)),
    }


def reveal_stored_pdf_password(settings_obj: CompanySecuritySettings, zone: str) -> str | None:
    """Return stored PDF open password for Super Admin display, or None if not recoverable."""
    if zone not in (PDF_ZONE_INSIDE, PDF_ZONE_OUTSIDE):
        return None
    if not settings_obj.pdf_password_required(zone):
        return None
    return settings_obj.get_pdf_open_password(zone) or None


def count_pending_preview_requests(company: Company_user) -> int:
    return AfterHoursPreviewRequest.objects.filter(
        company=company,
        status=AfterHoursPreviewRequest.PENDING,
    ).count()


def get_pending_preview_requests(company: Company_user, limit: int = 10):
    return (
        AfterHoursPreviewRequest.objects.filter(
            company=company,
            status=AfterHoursPreviewRequest.PENDING,
        )
        .select_related("employee")
        .order_by("-requested_at")[:limit]
    )


def location_policy_enabled(company: Company_user) -> bool:
    settings_obj = get_or_create_security_settings(company)
    return bool(settings_obj.ip_whitelist_enabled)


def get_location_access_summary(company: Company_user, client_ip: str) -> dict:
    settings_obj = get_or_create_security_settings(company)
    enabled = bool(settings_obj.ip_whitelist_enabled)
    at_office = is_ip_allowed_for_company(company, client_ip) if enabled else True
    return {
        "enabled": enabled,
        "at_office": at_office,
        "requires_permission": enabled and not at_office,
        "current_ip": client_ip,
    }


def location_permission_message(company: Company_user) -> str:
    settings_obj = get_or_create_security_settings(company)
    if not settings_obj.ip_whitelist_enabled:
        return "Office location (IP whitelist) is not enforced."
    return (
        "You are outside the office network. Request Super Admin approval before using modules or PDFs. "
        "Outside-location PDFs use a different password than inside the office."
    )


def queue_preview_permission(
    request,
    *,
    target_url_name: str = "",
    document_type: str = "access",
    document_label: str = "Access request",
    payload: dict | None = None,
    restriction_kind: str | None = None,
):
    from company.models import AfterHoursPreviewRequest

    request.session["pending_preview"] = {
        "target_url_name": target_url_name or "",
        "document_type": document_type or "access",
        "document_label": document_label,
        "payload": payload or {},
        "restriction_kind": restriction_kind or AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
    }
    request.session.modified = True


def ip_matches(client_ip: str, allowed: str) -> bool:
    allowed = (allowed or "").strip()
    if not allowed or not client_ip:
        return False
    try:
        if "/" in allowed:
            network = ipaddress.ip_network(allowed, strict=False)
            return ipaddress.ip_address(client_ip) in network
        return client_ip == allowed
    except ValueError:
        return False


def is_ip_allowed_for_company(company: Company_user, client_ip: str) -> bool:
    settings_obj = get_or_create_security_settings(company)
    if not settings_obj.ip_whitelist_enabled:
        return True
    active_ips = AllowedIP.objects.filter(company=company, is_active=True)
    if not active_ips.exists():
        return False
    return any(ip_matches(client_ip, row.ip_address) for row in active_ips)


def _working_days_set(settings_obj: CompanySecuritySettings) -> set[int]:
    raw = (settings_obj.working_days or "0,1,2,3,4,5,6").split(",")
    days = set()
    for part in raw:
        part = part.strip()
        if part.isdigit():
            days.add(int(part))
    return days if days else {0, 1, 2, 3, 4, 5, 6}


def is_within_office_hours(company: Company_user) -> bool:
    settings_obj = get_or_create_security_settings(company)
    if not settings_obj.office_hours_enabled:
        return True

    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(settings_obj.timezone)
    except Exception:
        tz = timezone.get_current_timezone()

    now_local = timezone.now().astimezone(tz)
    if now_local.weekday() not in _working_days_set(settings_obj):
        return False

    current_time = now_local.time()
    start = settings_obj.office_start
    end = settings_obj.office_end
    if start <= end:
        return start <= current_time <= end
    # Overnight window (e.g. 22:00 - 06:00)
    return current_time >= start or current_time <= end


def log_security_event(
    *,
    company: Company_user,
    event_type: str,
    request=None,
    employee: Employee | None = None,
    details: dict | None = None,
):
    ip_address = None
    user_agent = ""
    path = ""
    if request is not None:
        ip_address = get_client_ip(request) or None
        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:500]
        path = (request.path or "")[:255]

    SecurityAuditEvent.objects.create(
        company=company,
        employee=employee,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        path=path,
        details=details or {},
    )


def employee_default_redirect_url(permissions: dict) -> str:
    """First allowed module URL name for an employee."""
    order = [
        ("dashboard", "dashboard"),
        ("dispatch", "dispatch-view"),
        ("invoice_view", "view-dispatch-invoice"),
        ("invoice_create", "create-dispatch-invoice"),
        ("contract", "new-contract-view"),
        ("gc_note", "view-gc-note"),
        ("reports", "client-report-view"),
        ("masters", "rate-master-view"),
        ("summary", "summary-view"),
    ]
    for perm_key, url_name in order:
        if permissions.get(perm_key):
            return url_name
    return "company-logout"


def office_hours_enforced(company: Company_user) -> bool:
    settings_obj = get_or_create_security_settings(company)
    return bool(settings_obj.office_hours_enabled)


def _format_time_12h(t) -> str:
    try:
        return t.strftime("%I:%M %p").lstrip("0")
    except AttributeError:
        return str(t)


def get_office_hours_summary(company: Company_user) -> dict:
    """Human-readable office window + whether preview permission is required now."""
    settings_obj = get_or_create_security_settings(company)
    enabled = bool(settings_obj.office_hours_enabled)
    within = is_within_office_hours(company) if enabled else True
    return {
        "enabled": enabled,
        "within": within,
        "start": _format_time_12h(settings_obj.office_start),
        "end": _format_time_12h(settings_obj.office_end),
        "start_24": settings_obj.office_start.strftime("%H:%M"),
        "end_24": settings_obj.office_end.strftime("%H:%M"),
        "timezone": settings_obj.timezone,
        "preview_requires_permission": enabled and not within,
    }


def office_hours_permission_message(company: Company_user) -> str:
    summary = get_office_hours_summary(company)
    if not summary["enabled"]:
        return "Office hours are not enforced."
    return (
        f"Office hours are {summary['start']} to {summary['end']} ({summary['timezone']}). "
        f"Outside this window, PDF preview requires Super Admin approval."
    )


def employee_has_active_preview_grant(
    company: Company_user,
    employee_id: int,
    *,
    restriction_kind: str | None = None,
) -> bool:
    qs = AfterHoursPreviewRequest.objects.filter(
        company=company,
        employee_id=employee_id,
        status=AfterHoursPreviewRequest.APPROVED,
        grant_expires_at__gt=timezone.now(),
    )
    if restriction_kind:
        qs = qs.filter(restriction_kind=restriction_kind)
    return qs.exists()


def get_employee_preview_grants(company: Company_user, employee_id: int | None) -> dict:
    """Active Super Admin approvals for office-hours and outside-location."""
    if not employee_id:
        return {"office_hours": False, "outside_location": False, "any": False}
    office_hours = employee_has_active_preview_grant(
        company,
        employee_id,
        restriction_kind=AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
    )
    outside_location = employee_has_active_preview_grant(
        company,
        employee_id,
        restriction_kind=AfterHoursPreviewRequest.KIND_OUTSIDE_LOCATION,
    )
    return {
        "office_hours": office_hours,
        "outside_location": outside_location,
        "any": office_hours or outside_location,
    }


def employee_allowed_url_names_outside_restrictions(
    employee_info: dict,
    *,
    has_office_hours_grant: bool,
    has_location_grant: bool,
) -> set[str]:
    """
    URLs an employee may open when outside office hours or outside office IP.
    With an active grant, include their permitted modules and PDF endpoints.
    """
    allowed = set(OUTSIDE_OFFICE_HOURS_ALLOWED_URL_NAMES)
    if has_office_hours_grant or has_location_grant:
        allowed |= set(PDF_PREVIEW_URL_NAMES)
        permissions = employee_info.get("permissions") or {}
        for url_name, perm_key in URL_PERMISSION_MAP.items():
            if permissions.get(perm_key):
                allowed.add(url_name)
    return allowed


def is_at_office_location(company: Company_user, client_ip: str) -> bool:
    return is_ip_allowed_for_company(company, client_ip)


def get_pdf_access_zone(company: Company_user, client_ip: str) -> str:
    settings_obj = get_or_create_security_settings(company)
    if not settings_obj.ip_whitelist_enabled:
        return PDF_ZONE_INSIDE
    return PDF_ZONE_INSIDE if is_ip_allowed_for_company(company, client_ip) else PDF_ZONE_OUTSIDE


def is_pdf_verified_in_session(request, zone: str) -> bool:
    gate = request.session.get("pdf_access") or {}
    if gate.get("zone") != zone:
        return False
    expires = gate.get("expires_at")
    if not expires:
        return False
    try:
        from datetime import datetime

        exp = datetime.fromisoformat(expires)
        if timezone.is_naive(exp):
            exp = timezone.make_aware(exp, timezone.get_current_timezone())
        return exp > timezone.now()
    except (TypeError, ValueError):
        return False


def set_pdf_verified_session(request, zone: str):
    from datetime import timedelta

    request.session["pdf_access"] = {
        "zone": zone,
        "expires_at": (timezone.now() + timedelta(minutes=PDF_SESSION_TTL_MINUTES)).isoformat(),
    }
    request.session.modified = True


def employee_needs_location_permission(request, url_name: str | None = None) -> bool:
    if not is_employee(request):
        return False
    if url_name and url_name not in PDF_PREVIEW_URL_NAMES:
        return False
    try:
        company = get_session_company(request)
    except (Company_user.DoesNotExist, KeyError):
        return True
    settings_obj = get_or_create_security_settings(company)
    if not settings_obj.ip_whitelist_enabled:
        return False
    zone = get_pdf_access_zone(company, get_client_ip(request))
    if zone != PDF_ZONE_OUTSIDE:
        return False
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    if emp_id and employee_has_active_preview_grant(
        company,
        emp_id,
        restriction_kind=AfterHoursPreviewRequest.KIND_OUTSIDE_LOCATION,
    ):
        return False
    return True


def check_pdf_access_gate(request):
    """Return a redirect response if PDF access is blocked, else None."""
    from django.shortcuts import redirect

    try:
        url_name = resolve(request.path_info).url_name
    except Exception:
        url_name = None
    if url_name not in PDF_PREVIEW_URL_NAMES:
        return None

    try:
        company = get_session_company(request)
    except (Company_user.DoesNotExist, KeyError):
        return redirect("company-login")

    client_ip = get_client_ip(request)
    zone = get_pdf_access_zone(company, client_ip)
    settings_obj = get_or_create_security_settings(company)

    if employee_needs_location_permission(request, url_name):
        queue_preview_permission(
            request,
            target_url_name=url_name or "",
            document_type=url_name or "pdf",
            document_label="PDF (outside office location)",
            payload=_extract_request_payload(request),
            restriction_kind=AfterHoursPreviewRequest.KIND_OUTSIDE_LOCATION,
        )
        messages.warning(request, location_permission_message(company))
        return redirect("preview-permission-request")

    if employee_needs_preview_permission(request, url_name):
        return block_after_hours_preview_response(request, document_label="PDF")

    # Password is enforced inside the PDF file (Acrobat/browser prompt).
    from erp.utils.pdf_protection import get_pdf_embed_password_for_request

    if get_pdf_embed_password_for_request(request):
        return None

    if not settings_obj.pdf_password_required(zone):
        return None

    if is_pdf_verified_in_session(request, zone):
        return None

    request.session["pdf_access_return"] = {
        "url_name": url_name,
        "path": request.get_full_path(),
        "method": request.method,
        "payload": _extract_request_payload(request),
        "zone": zone,
    }
    return redirect("pdf-access-verify")


def _extract_request_payload(request) -> dict:
    payload = {}
    source = request.POST if request.method == "POST" else request.GET
    for key in source:
        if key == "csrfmiddlewaretoken":
            continue
        values = source.getlist(key)
        payload[key] = values if len(values) > 1 else values[0]
    return payload


def require_pdf_access(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        blocked = check_pdf_access_gate(request)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)

    return wrapper


def employee_needs_preview_permission(request, url_name: str | None = None) -> bool:
    """True if employee must get Super Admin approval before PDF preview."""
    if not is_employee(request):
        return False
    if url_name and url_name not in PDF_PREVIEW_URL_NAMES:
        return False
    try:
        company = get_session_company(request)
    except (Company_user.DoesNotExist, KeyError):
        return True
    if not office_hours_enforced(company):
        return False
    if is_within_office_hours(company):
        return False
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    if emp_id and employee_has_active_preview_grant(
        company,
        emp_id,
        restriction_kind=AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
    ):
        return False
    return True


def block_after_hours_preview_response(request, *, document_label: str = "PDF"):
    """Store attempted preview in session and return redirect to permission request."""
    from django.shortcuts import redirect

    try:
        url_name = resolve(request.path_info).url_name
    except Exception:
        url_name = request.path

    payload = {}
    source = request.POST if request.method == "POST" else request.GET
    for key in source:
        if key == "csrfmiddlewaretoken":
            continue
        values = source.getlist(key)
        payload[key] = values if len(values) > 1 else values[0]

    queue_preview_permission(
        request,
        target_url_name=url_name,
        document_type=url_name or "pdf",
        document_label=document_label,
        payload=payload,
        restriction_kind=AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
    )
    company = get_session_company(request)
    employee = None
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    if emp_id:
        employee = Employee.objects.filter(id=emp_id, company=company).first()
    log_security_event(
        company=company,
        employee=employee,
        event_type=SecurityAuditEvent.AFTER_HOURS_PREVIEW_BLOCKED,
        request=request,
        details={"document": document_label},
    )
    try:
        company = get_session_company(request)
        msg = office_hours_permission_message(company)
    except (Company_user.DoesNotExist, KeyError):
        msg = "Outside office hours: preview requires Super Admin approval."
    messages.warning(request, f"{document_label}: {msg}")
    return redirect("preview-permission-request")


def employee_has_url_permission(employee_session: dict, url_name: str) -> bool:
    if url_name in EMPLOYEE_EXEMPT_URL_NAMES:
        return True
    perm_key = URL_PERMISSION_MAP.get(url_name)
    if not perm_key:
        return True
    permissions = employee_session.get("permissions") or {}
    return bool(permissions.get(perm_key))


def build_employee_session_payload(employee: Employee) -> dict:
    return {
        "employee_id": employee.id,
        "username": employee.username,
        "display_name": employee.display_name,
        "permissions": employee.permissions_dict(),
    }


def block_employee_download(request):
    """Return True if request should be blocked (employee tried to download)."""
    if not is_employee(request):
        return False
    company_id = request.session.get("company_info", {}).get("company_id")
    if not company_id:
        return True
    try:
        company = Company_user.objects.get(id=company_id)
    except Company_user.DoesNotExist:
        return True
    employee_id = request.session.get("employee_info", {}).get("employee_id")
    employee = None
    if employee_id:
        employee = Employee.objects.filter(id=employee_id, company=company).first()
    log_security_event(
        company=company,
        employee=employee,
        event_type=SecurityAuditEvent.DOWNLOAD_BLOCKED,
        request=request,
        details={"reason": "Employee download not permitted"},
    )
    return True
