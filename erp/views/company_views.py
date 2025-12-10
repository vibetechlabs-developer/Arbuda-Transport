from django.shortcuts import render ,redirect 
from django.contrib import messages
from company.models import Company_user , Company_profile
from erp.utils.decorators import session_required


def Company_registraion(request):
    if(request.method == "POST"):
        cname = request.POST['company_name']
        cgstin = request.POST['gstin']
        cemail = request.POST['email']
        cmobile = request.POST['mobile']
        raw_password = request.POST['password']

        if Company_user.objects.filter(email=cemail).exists():
            messages.error(request , "This email is already exist, try with diffrent email")
            return redirect('company-registraion')

        if Company_user.objects.filter(mobile=cmobile).exists():
            messages.error(request , "This mobile number is already exist, try with diffrent mobile number")
            return redirect('company-registraion')


        if Company_user.objects.filter(gst_number=cgstin).exists():
            messages.error(request , "This GSTIN number is already exist, try with diffrent GSTIN")
            return redirect('company-registraion')
        
        # try:
        new_comp = Company_user(
            company_name = cname,
            mobile = cmobile,
            email = cemail,
            gst_number = cgstin,
        )
        new_comp.set_password(raw_password)
        new_comp.save()
        messages.success(request , "Company registred sucssesful")

        return redirect('company-login')

    return render(request , 'auth-register-company.html')


@session_required   
def Company_profile_view(request):
    remail = request.session.get("company_info")
    alldata = {}
    try:
        company = Company_user.objects.get(email = remail['company_email'])
        alldata['company'] = company
        if company.company_profile_status:
            profile = Company_profile.objects.get(company_id=company)
            alldata['profile'] = profile
    except Company_user.DoesNotExist:
        messages.error(request, "Invalid email or password!")
        return redirect('company-login')
    
    if request.method == "POST":
    
        rpan_number = request.POST['pan_number']
        raddress = request.POST['address']
        rstate = request.POST['state']
        rcity = request.POST['city']
        rpin = request.POST['pin']
        rlogo = request.FILES.get('logo', None)     
        rp_status = request.POST.get('p_status')

        try:
            if rp_status == 'update':
                profile = Company_profile.objects.get(company_id=company)
                if profile.pan_number != rpan_number:
                    messages.error(request, "PAN number cannot be changed once set.")
                    return redirect('company-profile')
                profile.address = raddress
                profile.state = rstate
                profile.city = rcity
                profile.pincode = rpin
                if rlogo is not None and rlogo != profile.logo:
                    profile.logo = rlogo
                else:       
                    profile.logo = profile.logo
                profile.save()
                messages.success(request, "Profile updated successfully! Please log in again to see the changes.")

                return redirect('company-logout')
            else:
                if Company_profile.objects.filter(pan_number = rpan_number).exists():
                    messages.error(request , "This pan number is already exist, try with diffrent email")
                    return redirect('company-profile')
                
                new_profile = Company_profile(
                    company_id = company,
                    pan_number = rpan_number,
                    address = raddress,
                    state = rstate,
                    city = rcity,
                    pincode = rpin,
                    logo = rlogo,
                )
                new_profile.save()
                company.company_profile_status = True
                company.save()
                messages.success(request, "Profile created successfully!")

                return redirect('dashboard')

        except Company_profile.DoesNotExist:
            messages.error(request, "Company does not exist!")
            return redirect('company-profile')

    return render(request , 'company_profile_form.html' , alldata)