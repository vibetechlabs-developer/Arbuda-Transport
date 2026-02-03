from django.shortcuts import render ,redirect 
from django.contrib import messages
from django.core.exceptions import MultipleObjectsReturned
from company.models import Company_user , Company_profile
from erp.utils.decorators import session_required, redirect_if_logged_in
from erp.utils.financial_year import generate_financial_year_options, get_current_financial_year

@redirect_if_logged_in
def Company_login(request):
    alldata = {}
    allcompany = Company_user.objects.all()
    alldata['allcompany'] = allcompany
    
    # Generate financial year options for the dropdown
    financial_years = generate_financial_year_options()
    alldata['financial_years'] = financial_years
    alldata['current_fy'] = get_current_financial_year()
    
    if request.method == 'POST':
        remail = request.POST["company_name"]
        raw_password = request.POST["password"]
        selected_year = request.POST.get("year", "")

        # Validate and convert year
        try:
            financial_year = int(selected_year) if selected_year else get_current_financial_year()
        except (ValueError, TypeError):
            financial_year = get_current_financial_year()

        try:
            company = Company_user.objects.get(company_name = remail)
        except Company_user.DoesNotExist:
            messages.error(request, "Invalid email or password!")
            return redirect('company-login')
        except MultipleObjectsReturned:
            # If multiple companies have the same name, get the first one
            company = Company_user.objects.filter(company_name=remail).first()
            if not company:
                messages.error(request, "Invalid email or password!")
                return redirect('company-login')
        

        if company.check_password(raw_password):
            request.session['company_info'] = {
                'company_id': company.id,
                'company_name': company.company_name,
                'company_email': company.email,
            }
            # Store selected financial year in session
            request.session['financial_year'] = financial_year
            
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
        if 'financial_year' in request.session:
            del request.session['financial_year']
        # del request.session['company_profile']
        messages.success(request, "Logged out successfully!")
        return redirect('company-login')
    return render(request , 'auth-login.html')
