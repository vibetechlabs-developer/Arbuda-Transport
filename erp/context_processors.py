from erp.utils.security import (
    count_pending_preview_requests,
    get_office_hours_summary,
    get_pending_preview_requests,
    is_employee,
    is_owner,
)


def global_data(request):
    company_info = request.session.get("company_info")
    office_hours = None
    pending_approval_count = 0
    pending_preview_requests = []

    if company_info and company_info.get("company_id"):
        try:
            from company.models import Company_user

            company = Company_user.objects.get(id=company_info["company_id"])
            office_hours = get_office_hours_summary(company)
            if is_owner(request):
                pending_approval_count = count_pending_preview_requests(company)
                pending_preview_requests = list(get_pending_preview_requests(company, limit=5))
        except Company_user.DoesNotExist:
            pass

    return {
        "company_info": company_info,
        "company_profile": request.session.get("company_profile"),
        "user_role": request.session.get("user_role", "owner"),
        "employee_info": request.session.get("employee_info"),
        "is_super_admin": is_owner(request),
        "is_employee_user": is_employee(request),
        "office_hours": office_hours,
        "pending_approval_count": pending_approval_count,
        "pending_preview_requests": pending_preview_requests,
    }
