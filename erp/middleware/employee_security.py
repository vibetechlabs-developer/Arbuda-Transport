from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve

from company.models import AfterHoursPreviewRequest, Company_user, Employee, SecurityAuditEvent
from erp.utils.security import (
    EMPLOYEE_EXEMPT_URL_NAMES,
    OWNER_ONLY_URL_NAMES,
    PDF_PREVIEW_URL_NAMES,
    employee_allowed_url_names_outside_restrictions,
    employee_default_redirect_url,
    employee_has_url_permission,
    get_client_ip,
    get_employee_preview_grants,
    get_or_create_security_settings,
    get_user_role,
    is_ip_allowed_for_company,
    is_within_office_hours,
    location_permission_message,
    log_security_event,
    office_hours_enforced,
    office_hours_permission_message,
    queue_preview_permission,
)


class EmployeeSecurityMiddleware:
    """
    Enforces IP whitelist, office hours, and module permissions for employees.
    Company owners (Super Admin) are exempt from IP and office-hour rules.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "company_info" not in request.session:
            return self.get_response(request)

        try:
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = None

        if url_name in EMPLOYEE_EXEMPT_URL_NAMES:
            return self.get_response(request)

        role = get_user_role(request)
        company_id = request.session["company_info"]["company_id"]

        try:
            company = Company_user.objects.get(id=company_id)
        except Company_user.DoesNotExist:
            request.session.flush()
            messages.error(request, "Session expired. Please log in again.")
            return redirect("company-login")

        if role == "owner":
            return self.get_response(request)

        client_ip = get_client_ip(request)
        employee_info = request.session.get("employee_info") or {}
        employee = None
        emp_id = employee_info.get("employee_id")

        if emp_id:
            employee = Employee.objects.filter(
                id=emp_id,
                company=company,
                is_active=True,
            ).first()
            if not employee:
                request.session.flush()
                messages.error(request, "Your employee account is no longer active.")
                return redirect("company-login")

        grants = get_employee_preview_grants(company, emp_id)
        request.session["preview_grants"] = grants

        if url_name in OWNER_ONLY_URL_NAMES:
            log_security_event(
                company=company,
                employee=employee,
                event_type=SecurityAuditEvent.PERMISSION_DENIED,
                request=request,
                details={"url": url_name, "reason": "owner_only"},
            )
            messages.error(request, "You do not have permission to access that page.")
            perms = employee_info.get("permissions") or {}
            return redirect(employee_default_redirect_url(perms))

        settings_obj = get_or_create_security_settings(company)
        at_office = is_ip_allowed_for_company(company, client_ip)
        outside_location = settings_obj.ip_whitelist_enabled and not at_office

        if outside_location:
            request.session["outside_office_location"] = True
            if not grants["outside_location"]:
                allowed_loc = employee_allowed_url_names_outside_restrictions(
                    employee_info,
                    has_office_hours_grant=grants["office_hours"],
                    has_location_grant=False,
                )
                if url_name not in allowed_loc:
                    event = (
                        SecurityAuditEvent.LOCATION_PREVIEW_BLOCKED
                        if url_name in PDF_PREVIEW_URL_NAMES
                        else SecurityAuditEvent.IP_BLOCKED
                    )
                    log_security_event(
                        company=company,
                        employee=employee,
                        event_type=event,
                        request=request,
                        details={"ip": client_ip, "url": url_name},
                    )
                    label = (
                        "PDF (outside office location)"
                        if url_name in PDF_PREVIEW_URL_NAMES
                        else f"Module access — {url_name or 'page'}"
                    )
                    queue_preview_permission(
                        request,
                        target_url_name=url_name or "",
                        document_type=url_name or "access",
                        document_label=label,
                        restriction_kind=AfterHoursPreviewRequest.KIND_OUTSIDE_LOCATION,
                    )
                    messages.warning(request, location_permission_message(company))
                    return redirect("preview-permission-request")
        else:
            request.session.pop("outside_office_location", None)

        outside_hours = office_hours_enforced(company) and not is_within_office_hours(company)

        if outside_hours:
            request.session["outside_office_hours"] = True

            if not grants["office_hours"]:
                allowed_hours = employee_allowed_url_names_outside_restrictions(
                    employee_info,
                    has_office_hours_grant=False,
                    has_location_grant=grants["outside_location"],
                )
                if url_name not in allowed_hours:
                    if url_name in PDF_PREVIEW_URL_NAMES:
                        log_security_event(
                            company=company,
                            employee=employee,
                            event_type=SecurityAuditEvent.AFTER_HOURS_PREVIEW_BLOCKED,
                            request=request,
                            details={"url": url_name, "stage": "middleware"},
                        )
                        queue_preview_permission(
                            request,
                            target_url_name=url_name or "",
                            document_type=url_name or "pdf",
                            document_label="PDF (outside office hours)",
                            restriction_kind=AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
                        )
                    else:
                        log_security_event(
                            company=company,
                            employee=employee,
                            event_type=SecurityAuditEvent.OFFICE_HOURS_BLOCKED,
                            request=request,
                            details={"url": url_name},
                        )
                        queue_preview_permission(
                            request,
                            target_url_name=url_name or "",
                            document_type=url_name or "access",
                            document_label=f"Module access — {url_name or 'page'} (outside office hours)",
                            restriction_kind=AfterHoursPreviewRequest.KIND_OFFICE_HOURS,
                        )
                    messages.warning(
                        request,
                        f"{office_hours_permission_message(company)} "
                        "Submit a request below; Super Admin will approve under Preview Approvals.",
                    )
                    return redirect("preview-permission-request")
        else:
            request.session.pop("outside_office_hours", None)

        if url_name and not employee_has_url_permission(employee_info, url_name):
            log_security_event(
                company=company,
                employee=employee,
                event_type=SecurityAuditEvent.PERMISSION_DENIED,
                request=request,
                details={"url": url_name},
            )
            messages.error(request, "You do not have permission to access this module.")
            perms = employee_info.get("permissions") or {}
            return redirect(employee_default_redirect_url(perms))

        return self.get_response(request)
