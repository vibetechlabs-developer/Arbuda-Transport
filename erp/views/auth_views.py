from django.shortcuts import render ,redirect 
from django.contrib import messages
from company.models import Company_user , Company_profile
from erp.utils.decorators import session_required, redirect_if_logged_in

@redirect_if_logged_in
def Company_login(request):
    alldata = {}
    allcompany = Company_user.objects.all()
    alldata['allcompany'] = allcompany
    if request.method == 'POST':
        remail = request.POST["company_name"]
        raw_password = request.POST["password"]

        try:
            company = Company_user.objects.get(company_name = remail)
        except Company_user.DoesNotExist:
            messages.error(request, "Invalid email or password!")
            return redirect('company-login')
        

        if company.check_password(raw_password):
            request.session['company_info'] = {
                'company_id': company.id,
                'company_name': company.company_name,
                'company_email': company.email,
            }
            if company.company_profile_status:
                    company_profile = Company_profile.objects.get(company_id=company)
                    request.session['company_profile'] = {
                        'company_logo': company_profile.logo.url if company_profile.logo else None,
                    }
            else:
                request.session['company_profile'] = None
            messages.success(request, 'Login Successfully')
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid email or password!")

    return render(request , 'auth-login.html' , alldata)

@session_required
def Company_logout(request):
    if 'company_info' in request.session:
        del request.session['company_info']
        # del request.session['company_profile']
        messages.success(request, "Logged out successfully!")
        return redirect('company-login')
    return render(request , 'auth-login.html')
