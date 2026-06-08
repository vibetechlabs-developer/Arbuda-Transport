from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.exceptions import MultipleObjectsReturned

from company.models import Company_profile, Company_user, Employee, SecurityAuditEvent
from erp.utils.decorators import redirect_if_logged_in, session_required
from erp.utils.financial_year import generate_financial_year_options, get_current_financial_year
from erp.utils.security import (
    build_employee_session_payload,
    employee_default_redirect_url,
    get_client_ip,
    is_ip_allowed_for_company,
    log_security_event,
)


def _login_context():
    min_allowed_fy = 2025
    max_allowed_fy = get_current_financial_year()
    return {
        "allcompany": Company_user.objects.all().order_by("company_name"),
        "financial_years": generate_financial_year_options(
            start_year=min_allowed_fy,
            end_year=max_allowed_fy,
        ),
        "current_fy": max_allowed_fy,
    }


def _set_company_session(request, company, financial_year):
    request.session["company_info"] = {
        "company_id": company.id,
        "company_name": company.company_name,
        "company_email": company.email,
    }
    request.session["financial_year"] = financial_year
    if company.company_profile_status:
        try:
            company_profile = Company_profile.objects.get(company_id=company)
            request.session["company_profile"] = {
                "company_logo": company_profile.logo.url if company_profile.logo else None,
            }
        except Company_profile.DoesNotExist:
            request.session["company_profile"] = None
    else:
        request.session["company_profile"] = None


@redirect_if_logged_in
def Company_login(request):
    alldata = _login_context()

    if request.method == "POST":
        company_name = (request.POST.get("company_name") or "").strip()
        raw_password = request.POST.get("password") or ""
        login_id = (request.POST.get("login_id") or "").strip().lower()
        login_as = (request.POST.get("login_as") or "owner").strip().lower()
        selected_year = request.POST.get("year", "")

        try:
            financial_year = int(selected_year) if selected_year else get_current_financial_year()
        except (ValueError, TypeError):
            financial_year = get_current_financial_year()

        min_allowed_fy = 2025
        max_allowed_fy = get_current_financial_year()
        if financial_year < min_allowed_fy or financial_year > max_allowed_fy:
            financial_year = max_allowed_fy

        try:
            company = Company_user.objects.get(company_name=company_name)
        except Company_user.DoesNotExist:
            messages.error(request, "Invalid company or credentials.")
            return redirect("company-login")
        except MultipleObjectsReturned:
            company = Company_user.objects.filter(company_name=company_name).first()
            if not company:
                messages.error(request, "Invalid company or credentials.")
                return redirect("company-login")

        client_ip = get_client_ip(request)

        if login_as == "employee":
            if not login_id:
                messages.error(request, "Employee ID is required.")
                return redirect("company-login")
            if login_id == company.effective_owner_login_id():
                messages.error(request, "Use Super Admin login for that ID.")
                return redirect("company-login")

            employee = Employee.objects.filter(
                company=company,
                username=login_id,
                is_active=True,
            ).first()
            if not employee or not employee.check_password(raw_password):
                log_security_event(
                    company=company,
                    event_type=SecurityAuditEvent.LOGIN_FAILED,
                    request=request,
                    details={"login_as": "employee", "username": login_id},
                )
                messages.error(request, "Invalid employee ID or password.")
                return redirect("company-login")

            _set_company_session(request, company, financial_year)
            request.session["user_role"] = "employee"
            request.session["employee_info"] = build_employee_session_payload(employee)
            request.session.pop("pdf_access", None)

            log_security_event(
                company=company,
                employee=employee,
                event_type=SecurityAuditEvent.LOGIN_SUCCESS,
                request=request,
                details={"login_as": "employee", "ip_allowed": is_ip_allowed_for_company(company, client_ip)},
            )
            messages.success(request, f"Welcome, {employee.display_name}.")
            return redirect(employee_default_redirect_url(employee.permissions_dict()))

        # Super Admin (owner)
        if not login_id:
            login_id = company.effective_owner_login_id()
        if login_id != company.effective_owner_login_id() or not company.check_owner_password(raw_password):
            log_security_event(
                company=company,
                event_type=SecurityAuditEvent.LOGIN_FAILED,
                request=request,
                details={"login_as": "owner", "login_id": login_id},
            )
            messages.error(request, "Invalid Super Admin ID or password.")
            return redirect("company-login")

        _set_company_session(request, company, financial_year)
        request.session["user_role"] = "owner"
        request.session.pop("employee_info", None)
        request.session.pop("pdf_access", None)

        log_security_event(
            company=company,
            event_type=SecurityAuditEvent.LOGIN_SUCCESS,
            request=request,
            details={"login_as": "owner"},
        )
        messages.success(request, "Super Admin login successful.")
        return redirect("dashboard")

    return render(request, "auth-login.html", alldata)


@session_required
def Company_logout(request):
    company_id = request.session.get("company_info", {}).get("company_id")
    emp_id = request.session.get("employee_info", {}).get("employee_id")
    if company_id:
        try:
            company = Company_user.objects.get(id=company_id)
            employee = None
            if emp_id:
                employee = Employee.objects.filter(id=emp_id, company=company).first()
            log_security_event(
                company=company,
                employee=employee,
                event_type=SecurityAuditEvent.LOGOUT,
                request=request,
            )
        except Company_user.DoesNotExist:
            pass

    for key in (
        "company_info",
        "financial_year",
        "company_profile",
        "user_role",
        "employee_info",
        "pdf_access",
        "pdf_access_return",
        "pending_preview",
        "outside_office_hours",
        "outside_office_location",
    ):
        request.session.pop(key, None)

    messages.success(request, "Logged out successfully.")
    return redirect("company-login")
