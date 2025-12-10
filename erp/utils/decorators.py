from django.shortcuts import redirect 
from django.contrib import messages
from django.urls import  resolve
from company.models import Company_user 
from functools import wraps

def session_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1️⃣ Check if logged in
        if 'company_info' not in request.session:
            messages.warning(request, "Please log in first!")
            return redirect('company-login')

        try:
            cid = request.session.get('company_info')
            company = Company_user.objects.get(id=cid['company_id'])

            # 2️⃣ Resolve current URL name
            current_url_name = resolve(request.path_info).url_name

            # 3️⃣ URLs that incomplete profiles are allowed to access
            allowed_names = [
                'company-profile',         # profile completion page
                'company-update-profile',  # profile update API/page
                'company-logout',          # logout page
            ]

            # 4️⃣ If profile is incomplete, restrict access except for allowed pages
            if not company.company_profile_status:
                if current_url_name not in allowed_names:
                    messages.warning(request, "Please complete your profile first.")
                    return redirect('company-profile')

        except Company_user.DoesNotExist:
            # Handle case where stored session data is invalid
            del request.session['company_info']  # remove bad session
            messages.error(request, "Session expired or invalid. Please log in again.")
            return redirect('company-login')

        # 5️⃣ Everything OK → proceed
        return view_func(request, *args, **kwargs)

    return wrapper

def redirect_if_logged_in(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if 'company_info' in request.session:
            # If already logged in, skip login/signup page
            messages.info(request, "You are already logged in.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper