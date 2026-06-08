from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from company.models import AfterHoursPreviewRequest, Employee, SecurityAuditEvent
from erp.utils.decorators import owner_required, session_required
from erp.utils.security import (
    get_client_ip,
    get_location_access_summary,
    get_office_hours_summary,
    get_session_company,
    is_employee,
    log_security_event,
)


def _get_employee(request) -> Employee:
    company = get_session_company(request)
    emp_id = request.session["employee_info"]["employee_id"]
    return get_object_or_404(Employee, id=emp_id, company=company, is_active=True)


@session_required
def preview_permission_request(request):
    if not is_employee(request):
        messages.info(request, "Super Admin does not need preview permission requests.")
        return redirect("dashboard")

    company = get_session_company(request)
    employee = _get_employee(request)
    pending = request.session.get("pending_preview")

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            messages.error(request, "Please provide a reason for after-hours preview.")
            return redirect("preview-permission-request")

        doc_type = (request.POST.get("document_type") or (pending or {}).get("document_type") or "pdf")
        doc_label = (request.POST.get("document_label") or (pending or {}).get("document_label") or "Document")
        target_url = (request.POST.get("target_url_name") or (pending or {}).get("target_url_name") or "")
        payload = (pending or {}).get("payload") or {}

        restriction_kind = (
            request.POST.get("restriction_kind")
            or (pending or {}).get("restriction_kind")
            or AfterHoursPreviewRequest.KIND_OFFICE_HOURS
        )

        AfterHoursPreviewRequest.objects.create(
            company=company,
            employee=employee,
            document_type=doc_type,
            document_label=doc_label,
            target_url_name=target_url,
            payload=payload,
            reason=reason,
            status=AfterHoursPreviewRequest.PENDING,
            restriction_kind=restriction_kind,
        )
        request.session.pop("pending_preview", None)
        log_security_event(
            company=company,
            employee=employee,
            event_type=SecurityAuditEvent.PREVIEW_REQUESTED,
            request=request,
            details={"document": doc_label},
        )
        messages.success(
            request,
            "Your preview request was sent to the Super Admin. You will be able to preview after approval.",
        )
        return redirect("preview-permission-my")

    context = {
        "pending": pending,
        "office_hours": get_office_hours_summary(company),
        "location_access": get_location_access_summary(company, get_client_ip(request)),
    }
    return render(request, "security/preview-permission-request.html", context)


@session_required
def preview_permission_my(request):
    if not is_employee(request):
        return redirect("preview-permission-manage")

    company = get_session_company(request)
    employee = _get_employee(request)
    requests_qs = AfterHoursPreviewRequest.objects.filter(
        company=company, employee=employee
    ).order_by("-requested_at")[:30]

    now = timezone.now()
    active_grant = AfterHoursPreviewRequest.objects.filter(
        company=company,
        employee=employee,
        status=AfterHoursPreviewRequest.APPROVED,
        grant_expires_at__gt=now,
    ).order_by("-grant_expires_at").first()

    return render(
        request,
        "security/preview-permission-my.html",
        {
            "requests": requests_qs,
            "now": now,
            "active_grant": active_grant,
        },
    )


@session_required
def preview_permission_run(request, request_id):
    """Replay an approved preview (POST with stored payload)."""
    if not is_employee(request):
        return redirect("dashboard")

    company = get_session_company(request)
    employee = _get_employee(request)
    preview_req = get_object_or_404(
        AfterHoursPreviewRequest,
        id=request_id,
        company=company,
        employee=employee,
        status=AfterHoursPreviewRequest.APPROVED,
    )
    if not preview_req.grant_is_active():
        messages.error(request, "This preview approval has expired. Please request again.")
        return redirect("preview-permission-my")

    url_name = preview_req.target_url_name
    if not url_name:
        messages.error(request, "Invalid preview request.")
        return redirect("preview-permission-my")

    path = reverse(url_name)
    return render(
        request,
        "security/preview-permission-run.html",
        {
            "preview_request": preview_req,
            "target_path": path,
            "payload": preview_req.payload,
        },
    )


@session_required
@owner_required
def preview_permission_manage(request):
    company = get_session_company(request)

    if request.method == "POST":
        action = request.POST.get("action")
        req_id = request.POST.get("request_id")
        preview_req = get_object_or_404(
            AfterHoursPreviewRequest,
            id=req_id,
            company=company,
            status=AfterHoursPreviewRequest.PENDING,
        )
        note = (request.POST.get("reviewer_note") or "").strip()
        from erp.utils.security import get_or_create_security_settings

        settings_obj = get_or_create_security_settings(company)
        grant_minutes = settings_obj.after_hours_grant_minutes or 120

        if action == "approve":
            preview_req.status = AfterHoursPreviewRequest.APPROVED
            preview_req.reviewed_at = timezone.now()
            preview_req.reviewer_note = note
            preview_req.grant_expires_at = timezone.now() + timedelta(minutes=grant_minutes)
            preview_req.save()
            log_security_event(
                company=company,
                employee=preview_req.employee,
                event_type=SecurityAuditEvent.PREVIEW_APPROVED,
                request=request,
                details={
                    "request_id": preview_req.id,
                    "expires": preview_req.grant_expires_at.isoformat(),
                },
            )
            messages.success(
                request,
                f"Approved preview for {preview_req.employee.display_name} "
                f"until {preview_req.grant_expires_at.strftime('%I:%M %p')}. "
                f"They can use permitted modules and PDFs until then "
                f"(employee should refresh the page or open My preview requests).",
            )
        elif action == "deny":
            preview_req.status = AfterHoursPreviewRequest.DENIED
            preview_req.reviewed_at = timezone.now()
            preview_req.reviewer_note = note
            preview_req.save()
            log_security_event(
                company=company,
                employee=preview_req.employee,
                event_type=SecurityAuditEvent.PREVIEW_DENIED,
                request=request,
                details={"request_id": preview_req.id},
            )
            messages.success(request, "Preview request denied.")

        return redirect("preview-permission-manage")

    pending = AfterHoursPreviewRequest.objects.filter(
        company=company, status=AfterHoursPreviewRequest.PENDING
    ).select_related("employee")
    recent = AfterHoursPreviewRequest.objects.filter(company=company).exclude(
        status=AfterHoursPreviewRequest.PENDING
    ).select_related("employee")[:20]

    return render(
        request,
        "security/preview-permission-manage.html",
        {"pending": pending, "recent": recent, "now": timezone.now()},
    )
