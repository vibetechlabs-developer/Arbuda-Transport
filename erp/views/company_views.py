from django.shortcuts import render ,redirect 
from django.contrib import messages
from company.models import Company_user , Company_profile
from erp.utils import validate_gstin
from erp.utils.decorators import session_required


def Company_registraion(request):
    if request.method == "POST":
        cname = (request.POST.get('company_name') or '').strip()
        cgstin = (request.POST.get('gstin') or '').strip().upper()
        cemail = (request.POST.get('email') or '').strip().lower()
        cmobile = (request.POST.get('mobile') or '').strip()
        raw_password = request.POST.get('password') or ''
        rpassword = request.POST.get('rpassword') or ''
        tc = request.POST.get('tc')

        errors = {}
        values = {
            'company_name': cname,
            'gstin': cgstin,
            'email': cemail,
            'mobile': cmobile,
            'tc': bool(tc),
        }

        # Basic required validation (JS validation exists, but we must validate on server too)
        if not cname:
            errors['company_name'] = "Company name is required."
        if not cgstin:
            errors['gstin'] = "GST number is required."
        elif not validate_gstin(cgstin):
            errors['gstin'] = "Enter a valid GSTIN as per GST rules."
        if not cemail:
            errors['email'] = "Email is required."
        if not cmobile:
            errors['mobile'] = "Mobile number is required."
        if not raw_password:
            errors['password'] = "Password is required."
        if not rpassword:
            errors['rpassword'] = "Confirm password is required."
        if raw_password and rpassword and raw_password != rpassword:
            errors['rpassword'] = "Passwords do not match."
        if not tc:
            errors['tc'] = "Please accept the privacy policy & terms."

        # Uniqueness validation
        if cemail and Company_user.objects.filter(email=cemail).exists():
            errors['email'] = "This email already exists. Try a different email."
        if cmobile and Company_user.objects.filter(mobile=cmobile).exists():
            errors['mobile'] = "This mobile number already exists. Try a different mobile number."
        if cgstin and Company_user.objects.filter(gst_number=cgstin).exists():
            errors['gstin'] = "This GSTIN already exists. Try a different GSTIN."

        if errors:
            # Render inline errors (avoid global toast notifications for form errors)
            return render(request, 'auth-register-company.html', {'errors': errors, 'values': values})

        new_comp = Company_user(
            company_name=cname,
            mobile=cmobile,
            email=cemail,
            gst_number=cgstin,
        )
        new_comp.set_password(raw_password)
        new_comp.save()
        messages.success(request, "Company registered successfully.")
        return redirect('company-login')

    return render(request, 'auth-register-company.html', {'errors': {}, 'values': {}})


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
        # Validate on server (JS validation exists but must not be trusted).
        errors = {}
        values = {
            "pan_number": (request.POST.get('pan_number') or '').strip().upper(),
            "address": (request.POST.get('address') or '').strip(),
            "state": (request.POST.get('state') or '').strip(),
            "city": (request.POST.get('city') or '').strip(),
            "pin": (request.POST.get('pin') or '').strip(),
        }

        rpan_number = values["pan_number"]
        raddress = values["address"]
        rstate = values["state"]
        rcity = values["city"]
        rpin = values["pin"]
        rlogo = request.FILES.get('logo', None)     
        rp_status = request.POST.get('p_status')

        try:
            if rp_status == 'update':
                profile = Company_profile.objects.get(company_id=company)
                if profile.pan_number != rpan_number:
                    errors['pan_number'] = "PAN number cannot be changed once set."
                # Basic required validation
                if not raddress:
                    errors['address'] = "Address is required."
                if not rstate:
                    errors['state'] = "State is required."
                if not rcity:
                    errors['city'] = "City is required."
                if not rpin:
                    errors['pin'] = "Pin code is required."
                if errors:
                    # Inline errors only (avoid toast notifications for validation errors)
                    alldata['errors'] = errors
                    alldata['values'] = values
                    return render(request, 'company_profile_form.html', alldata)
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
                    errors['pan_number'] = "This PAN number already exists. Try a different one."

                # Basic required validation
                if not rpan_number:
                    errors['pan_number'] = errors.get('pan_number') or "PAN number is required."
                if not raddress:
                    errors['address'] = "Address is required."
                if not rstate:
                    errors['state'] = "State is required."
                if not rcity:
                    errors['city'] = "City is required."
                if not rpin:
                    errors['pin'] = "Pin code is required."

                if errors:
                    alldata['errors'] = errors
                    alldata['values'] = values
                    return render(request, 'company_profile_form.html', alldata)
                
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