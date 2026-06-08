from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve

from company.models import Company_user
from erp.utils.security import employee_default_redirect_url, is_owner


def session_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if "company_info" not in request.session:
            messages.warning(request, "Please log in first!")
            return redirect("company-login")

        try:
            cid = request.session.get("company_info")
            company = Company_user.objects.get(id=cid["company_id"])
            current_url_name = resolve(request.path_info).url_name

            if request.session.get("user_role") == "employee":
                return view_func(request, *args, **kwargs)

            allowed_names = [
                "company-profile",
                "company-update-profile",
                "company-logout",
                "security-settings",
                "employee-manage",
                "employee-create",
                "employee-edit",
            ]

            if not company.company_profile_status and current_url_name not in allowed_names:
                messages.warning(request, "Please complete your profile first.")
                return redirect("company-profile")

        except Company_user.DoesNotExist:
            request.session.pop("company_info", None)
            messages.error(request, "Session expired or invalid. Please log in again.")
            return redirect("company-login")

        return view_func(request, *args, **kwargs)

    return wrapper


def owner_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_owner(request):
            messages.error(request, "Only Super Admin can access this page.")
            perms = request.session.get("employee_info", {}).get("permissions") or {}
            if perms:
                return redirect(employee_default_redirect_url(perms))
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper


def redirect_if_logged_in(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if "company_info" in request.session:
            messages.info(request, "You are already logged in.")
            if request.session.get("user_role") == "employee":
                perms = request.session.get("employee_info", {}).get("permissions") or {}
                return redirect(employee_default_redirect_url(perms))
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper
