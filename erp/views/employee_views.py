from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from company.models import Employee
from erp.utils.decorators import owner_required, session_required
from erp.utils.security import get_session_company


def _get_owner_company(request):
    return get_session_company(request)


@session_required
@owner_required
def employee_manage(request):
    company = _get_owner_company(request)
    employees = Employee.objects.filter(company=company)
    return render(
        request,
        "security/employee-manage.html",
        {"employees": employees},
    )


@session_required
@owner_required
def employee_create(request):
    company = _get_owner_company(request)
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip().lower()
        display_name = (request.POST.get("display_name") or "").strip()
        password = request.POST.get("password") or ""
        if not username or not display_name or len(password) < 4:
            messages.error(request, "Username, display name, and password (min 4 chars) are required.")
            return redirect("employee-create")
        if username == company.effective_owner_login_id():
            messages.error(request, "This ID is reserved for Super Admin login.")
            return redirect("employee-create")
        if Employee.objects.filter(company=company, username=username).exists():
            messages.error(request, "That username already exists for your company.")
            return redirect("employee-create")
        emp = Employee(
            company=company,
            username=username,
            display_name=display_name,
            perm_dashboard=request.POST.get("perm_dashboard") == "on",
            perm_contract=request.POST.get("perm_contract") == "on",
            perm_dispatch=request.POST.get("perm_dispatch") == "on",
            perm_invoice_create=request.POST.get("perm_invoice_create") == "on",
            perm_invoice_view=request.POST.get("perm_invoice_view") == "on",
            perm_invoice_update=request.POST.get("perm_invoice_update") == "on",
            perm_gc_note=request.POST.get("perm_gc_note") == "on",
            perm_reports=request.POST.get("perm_reports") == "on",
            perm_masters=request.POST.get("perm_masters") == "on",
            perm_summary=request.POST.get("perm_summary") == "on",
        )
        emp.set_password(password)
        emp.save()
        messages.success(request, f"Employee '{username}' created.")
        return redirect("employee-manage")
    return render(request, "security/employee-form.html", {"employee": None, "is_edit": False})


@session_required
@owner_required
def employee_edit(request, employee_id):
    company = _get_owner_company(request)
    emp = get_object_or_404(Employee, id=employee_id, company=company)
    if request.method == "POST":
        emp.display_name = (request.POST.get("display_name") or "").strip()
        emp.perm_dashboard = request.POST.get("perm_dashboard") == "on"
        emp.perm_contract = request.POST.get("perm_contract") == "on"
        emp.perm_dispatch = request.POST.get("perm_dispatch") == "on"
        emp.perm_invoice_create = request.POST.get("perm_invoice_create") == "on"
        emp.perm_invoice_view = request.POST.get("perm_invoice_view") == "on"
        emp.perm_invoice_update = request.POST.get("perm_invoice_update") == "on"
        emp.perm_gc_note = request.POST.get("perm_gc_note") == "on"
        emp.perm_reports = request.POST.get("perm_reports") == "on"
        emp.perm_masters = request.POST.get("perm_masters") == "on"
        emp.perm_summary = request.POST.get("perm_summary") == "on"
        new_password = request.POST.get("password") or ""
        if new_password:
            if len(new_password) < 4:
                messages.error(request, "Password must be at least 4 characters.")
                return redirect("employee-edit", employee_id=emp.id)
            emp.set_password(new_password)
        emp.save()
        messages.success(request, "Employee updated.")
        return redirect("employee-manage")
    return render(
        request,
        "security/employee-form.html",
        {"employee": emp, "is_edit": True},
    )


@session_required
@owner_required
def employee_deactivate(request, employee_id):
    company = _get_owner_company(request)
    emp = get_object_or_404(Employee, id=employee_id, company=company)
    if request.method == "POST":
        emp.is_active = request.POST.get("is_active") == "1"
        emp.save()
        state = "activated" if emp.is_active else "deactivated"
        messages.success(request, f"Employee '{emp.username}' {state}.")
    return redirect("employee-manage")
