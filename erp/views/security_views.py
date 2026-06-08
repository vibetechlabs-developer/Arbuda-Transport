import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from company.models import (
    AllowedIP,
    Company_user,
    Employee,
    SecurityAuditEvent,
)
from erp.utils.decorators import owner_required, session_required
from erp.utils.security import (
    PDF_ZONE_INSIDE,
    PDF_ZONE_OUTSIDE,
    count_pending_preview_requests,
    ensure_default_pdf_passwords,
    get_client_ip,
    get_employee_preview_grants,
    get_location_access_summary,
    get_office_hours_summary,
    get_or_create_security_settings,
    get_pending_preview_requests,
    get_pdf_access_zone,
    get_session_company,
    pdf_password_status,
    reveal_stored_pdf_password,
    is_within_office_hours,
    log_security_event,
    set_pdf_verified_session,
)


def _get_owner_company(request) -> Company_user:
    from erp.utils.security import get_session_company

    return get_session_company(request)


@session_required
@owner_required
def security_settings(request):
    company = _get_owner_company(request)
    settings_obj = get_or_create_security_settings(company)
    allowed_ips = AllowedIP.objects.filter(company=company)

    if request.method == "POST":
        action = request.POST.get("action", "settings")
        if action == "settings":
            settings_obj.ip_whitelist_enabled = request.POST.get("ip_whitelist_enabled") == "on"
            settings_obj.office_hours_enabled = request.POST.get("office_hours_enabled") == "on"
            settings_obj.timezone = (request.POST.get("timezone") or "Asia/Kolkata").strip()
            settings_obj.working_days = (request.POST.get("working_days") or "0,1,2,3,4,5,6").strip()
            try:
                settings_obj.after_hours_grant_minutes = max(
                    15,
                    min(480, int(request.POST.get("after_hours_grant_minutes") or 120)),
                )
            except (TypeError, ValueError):
                settings_obj.after_hours_grant_minutes = 120
            try:
                from datetime import datetime

                settings_obj.office_start = datetime.strptime(
                    request.POST.get("office_start") or "10:00", "%H:%M"
                ).time()
                settings_obj.office_end = datetime.strptime(
                    request.POST.get("office_end") or "19:00", "%H:%M"
                ).time()
            except ValueError:
                messages.error(request, "Invalid office hours format. Use HH:MM.")
                return redirect("security-settings")
            settings_obj.save()
            messages.success(request, "Security settings saved.")
        elif action == "pdf_file_policy":
            settings_obj.pdf_files_always_use_outside_password = (
                request.POST.get("pdf_files_always_use_outside_password") == "on"
            )
            settings_obj.save()
            messages.success(request, "PDF file password policy saved.")
        elif action == "add_ip":
            ip_address = (request.POST.get("ip_address") or "").strip()
            label = (request.POST.get("label") or "").strip()
            if ip_address:
                AllowedIP.objects.create(
                    company=company,
                    ip_address=ip_address,
                    label=label,
                )
                messages.success(request, f"IP {ip_address} added to whitelist.")
            else:
                messages.error(request, "IP address is required.")
        elif action == "add_current_ip":
            ip_address = get_client_ip(request)
            if not ip_address:
                messages.error(request, "Could not detect your current IP address.")
                return redirect("security-settings")
            existing = AllowedIP.objects.filter(company=company, ip_address=ip_address).first()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.save()
                    messages.success(request, f"Re-activated office IP {ip_address}.")
                else:
                    messages.info(request, f"Your current IP {ip_address} is already on the whitelist.")
            else:
                AllowedIP.objects.create(
                    company=company,
                    ip_address=ip_address,
                    label="This computer (auto-added)",
                )
                messages.success(
                    request,
                    f"Added your current IP {ip_address} to the office whitelist. "
                    "Enable “Enforce office location” below and save settings.",
                )
        elif action == "delete_ip":
            ip_id = request.POST.get("ip_id")
            AllowedIP.objects.filter(company=company, id=ip_id).delete()
            messages.success(request, "IP removed from whitelist.")
        elif action == "toggle_ip":
            ip_id = request.POST.get("ip_id")
            row = get_object_or_404(AllowedIP, id=ip_id, company=company)
            row.is_active = not row.is_active
            row.save()
            messages.success(request, "IP status updated.")
        elif action == "owner_credentials":
            new_owner_id = (request.POST.get("owner_login_id") or "").strip().lower()
            new_password = request.POST.get("owner_password") or ""
            confirm_password = request.POST.get("owner_password_confirm") or ""
            if not new_owner_id or len(new_owner_id) < 3:
                messages.error(request, "Super Admin ID must be at least 3 characters.")
                return redirect("security-settings")
            if Employee.objects.filter(company=company, username=new_owner_id).exists():
                messages.error(request, "This ID is already used by an employee. Choose a different Super Admin ID.")
                return redirect("security-settings")
            if new_password:
                if len(new_password) < 4:
                    messages.error(request, "Password must be at least 4 characters.")
                    return redirect("security-settings")
                if new_password != confirm_password:
                    messages.error(request, "Passwords do not match.")
                    return redirect("security-settings")
                company.set_owner_password(new_password)
            company.owner_login_id = new_owner_id
            company.save()
            messages.success(request, "Super Admin login ID/password updated (separate from company registration password).")
        elif action == "pdf_passwords":
            inside_pw = request.POST.get("pdf_password_inside") or ""
            outside_pw = request.POST.get("pdf_password_outside") or ""
            clear_inside = request.POST.get("clear_pdf_password_inside") == "on"
            clear_outside = request.POST.get("clear_pdf_password_outside") == "on"
            if clear_inside:
                settings_obj.pdf_password_inside = ""
            elif inside_pw:
                if len(inside_pw) < 4:
                    messages.error(request, "Inside-location PDF password must be at least 4 characters.")
                    return redirect("security-settings")
                settings_obj.set_pdf_password_inside(inside_pw)
            if clear_outside:
                settings_obj.pdf_password_outside = ""
            elif outside_pw:
                if len(outside_pw) < 4:
                    messages.error(request, "Outside-location PDF password must be at least 4 characters.")
                    return redirect("security-settings")
                settings_obj.set_pdf_password_outside(outside_pw)
            settings_obj.save()
            messages.success(request, "PDF access passwords updated.")
        elif action == "regenerate_pdf_passwords":
            inside, outside = ensure_default_pdf_passwords(settings_obj)
            request.session["pdf_passwords_auto_generated"] = {
                "inside": inside,
                "outside": outside,
            }
            messages.success(
                request,
                "New inside and outside PDF passwords were generated. Copy them below — they are shown once.",
            )
        return redirect("security-settings")

    auto_pw = request.session.pop("pdf_passwords_auto_generated", None)
    return render(
        request,
        "security/security-settings.html",
        {
            "settings": settings_obj,
            "allowed_ips": allowed_ips,
            "current_ip": get_client_ip(request),
            "company": company,
            "office_hours_summary": get_office_hours_summary(company),
            "location_summary": get_location_access_summary(company, get_client_ip(request)),
            "pdf_pw_status": pdf_password_status(settings_obj),
            "auto_generated_passwords": auto_pw,
        },
    )


@session_required
@owner_required
@require_GET
def reveal_pdf_password(request):
    zone = (request.GET.get("zone") or "").strip().lower()
    if zone not in (PDF_ZONE_INSIDE, PDF_ZONE_OUTSIDE):
        return JsonResponse({"ok": False, "error": "Invalid password type."}, status=400)

    company = _get_owner_company(request)
    settings_obj = get_or_create_security_settings(company)

    if not settings_obj.pdf_password_required(zone):
        return JsonResponse({"ok": False, "error": "No password is set for this type."}, status=404)

    plain = reveal_stored_pdf_password(settings_obj, zone)
    if not plain:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "This password cannot be recovered (it was set before secure storage was enabled). "
                    "Use “Regenerate both PDF passwords” to create new ones you can view here."
                ),
            },
            status=409,
        )

    log_security_event(
        company=company,
        event_type=SecurityAuditEvent.PDF_PASSWORD_REVEALED,
        request=request,
        details={"zone": zone},
    )
    label = "Inside office" if zone == PDF_ZONE_INSIDE else "Outside office"
    return JsonResponse({"ok": True, "zone": zone, "label": label, "password": plain})


@session_required
@owner_required
def security_audit_log(request):
    company = _get_owner_company(request)
    events = SecurityAuditEvent.objects.filter(company=company).select_related("employee")[:500]
    event_types = SecurityAuditEvent.EVENT_TYPE_CHOICES
    filter_type = request.GET.get("event_type", "")
    if filter_type:
        events = events.filter(event_type=filter_type)
    return render(
        request,
        "security/security-audit-log.html",
        {
            "events": events[:200],
            "event_types": event_types,
            "filter_type": filter_type,
        },
    )


@session_required
@require_GET
def security_office_hours_status(request):
    company_id = request.session.get("company_info", {}).get("company_id")
    if not company_id:
        return JsonResponse({"allowed": False, "reason": "not_logged_in"})
    try:
        company = Company_user.objects.get(id=company_id)
    except Company_user.DoesNotExist:
        return JsonResponse({"allowed": False, "reason": "invalid_company"})
    summary = get_office_hours_summary(company)
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    client_ip = get_client_ip(request)
    loc = get_location_access_summary(company, client_ip)
    grants = get_employee_preview_grants(company, emp_id)
    hours_ok = summary["within"] or grants["office_hours"]
    location_ok = loc["at_office"] or grants["outside_location"] or not loc["enabled"]
    return JsonResponse(
        {
            "allowed": hours_ok and location_ok,
            "role": request.session.get("user_role", "owner"),
            "office_hours_enabled": summary["enabled"],
            "office_start": summary["start"],
            "office_end": summary["end"],
            "preview_requires_permission": summary["preview_requires_permission"] and not grants["office_hours"],
            "preview_grant_active": grants["office_hours"],
            "location_enforced": loc["enabled"],
            "at_office_location": loc["at_office"],
            "location_requires_permission": loc["requires_permission"] and not grants["outside_location"],
            "location_grant_active": grants["outside_location"],
            "timezone": summary["timezone"],
        }
    )


@session_required
@owner_required
@require_GET
def security_admin_notifications(request):
    """JSON for Super Admin navbar badge and notification dropdown."""
    company = get_session_company(request)
    pending_qs = get_pending_preview_requests(company, limit=8)
    items = [
        {
            "id": r.id,
            "employee": r.employee.display_name,
            "username": r.employee.username,
            "kind": r.get_restriction_kind_display(),
            "restriction_kind": r.restriction_kind,
            "document": r.document_label or r.document_type,
            "reason": (r.reason or "")[:120],
            "requested_at": r.requested_at.strftime("%d %b %Y %H:%M"),
        }
        for r in pending_qs
    ]
    return JsonResponse(
        {
            "pending_count": count_pending_preview_requests(company),
            "items": items,
            "manage_url": "/security/preview-permission/manage",
        }
    )


@session_required
@require_POST
def security_audit_beacon(request):
    """Client-side security events (print, hotkeys)."""
    company_id = request.session.get("company_info", {}).get("company_id")
    if not company_id:
        return JsonResponse({"ok": False})
    try:
        company = Company_user.objects.get(id=company_id)
    except Company_user.DoesNotExist:
        return JsonResponse({"ok": False})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}

    event_type = payload.get("event_type", SecurityAuditEvent.HOTKEY_BLOCKED)
    valid_types = {c[0] for c in SecurityAuditEvent.EVENT_TYPE_CHOICES}
    if event_type not in valid_types:
        event_type = SecurityAuditEvent.HOTKEY_BLOCKED

    employee = None
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    if emp_id:
        employee = Employee.objects.filter(id=emp_id, company=company).first()

    log_security_event(
        company=company,
        employee=employee,
        event_type=event_type,
        request=request,
        details=payload.get("details") or {},
    )
    return JsonResponse({"ok": True})


@session_required
def pdf_access_verify(request):
    company = get_session_company(request)
    settings_obj = get_or_create_security_settings(company)
    client_ip = get_client_ip(request)
    zone = get_pdf_access_zone(company, client_ip)
    zone_label = "office (inside)" if zone == PDF_ZONE_INSIDE else "outside office network"
    return_data = request.session.get("pdf_access_return") or {}

    if request.method == "POST":
        password = request.POST.get("pdf_password") or ""
        ok = (
            settings_obj.check_pdf_password_inside(password)
            if zone == PDF_ZONE_INSIDE
            else settings_obj.check_pdf_password_outside(password)
        )
        if not ok:
            employee = None
            emp_id = request.session.get("employee_info", {}).get("employee_id")
            if emp_id:
                employee = Employee.objects.filter(id=emp_id, company=company).first()
            log_security_event(
                company=company,
                employee=employee,
                event_type=SecurityAuditEvent.PDF_PASSWORD_FAILED,
                request=request,
                details={"zone": zone},
            )
            messages.error(request, "Incorrect PDF access password.")
            return redirect("pdf-access-verify")

        set_pdf_verified_session(request, zone)
        request.session.pop("pdf_access_return", None)
        messages.success(request, f"PDF access unlocked for {zone_label}.")

        from django.urls import reverse

        url_name = return_data.get("url_name")
        if url_name:
            path = reverse(url_name)
            if return_data.get("method") == "POST":
                return render(
                    request,
                    "security/pdf-access-replay.html",
                    {"target_path": path, "payload": return_data.get("payload") or {}},
                )
            return redirect(path)
        return redirect("dashboard")

    return render(
        request,
        "security/pdf-access-verify.html",
        {
            "zone": zone,
            "zone_label": zone_label,
            "inside_required": settings_obj.pdf_password_required(PDF_ZONE_INSIDE),
            "outside_required": settings_obj.pdf_password_required(PDF_ZONE_OUTSIDE),
            "return_data": return_data,
        },
    )
