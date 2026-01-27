from django.shortcuts import render ,redirect ,get_object_or_404
from django.contrib import messages
from company.models import Company_user , Company_profile
from transport.models import Rate , T_Contract ,Dispatch ,Destination ,Rate_taluka , Rate_District ,Rate_IncomeTax , Rate_Cumulative , Invoice , GC_Note
from datetime import datetime
from django.db import transaction
from erp.utils.decorators import session_required
from django.db.models import Func, Sum, Count, Max




@session_required
def add_contract(request):
    if request.method == "POST":
        try:
            # Save main contract (without rate_type now)
            if request.POST.get("unloading_rate_1") == 'yes':
                i_unloading_charge_1 = request.POST.get("unloading_charge_1")
            else:
                i_unloading_charge_1 = 0

            if request.POST.get("unloading_rate_2") == 'yes':
                i_unloading_charge_2 = request.POST.get("unloading_charge_2")
            else:
                i_unloading_charge_2 = 0

            if request.POST.get("loading_rate") == 'yes':
                i_loading_charge = request.POST.get("loading_charge")
            else:
                i_loading_charge = 0

            i_comapany_id = Company_user.objects.get(id=request.session['company_info']['company_id'])
            contract = T_Contract.objects.create( 
                company_id = i_comapany_id,
                company_name=request.POST.get("company_name"),
                vendor_code=request.POST.get("vendor_code"),
                gst_number=request.POST.get("gst_number"),
                pan_number=request.POST.get("pan_number"),
                tan_number=request.POST.get("tan_number"),
                cin_number=request.POST.get("cin_number"),
                from_center=request.POST.get("from_center"),

                contract_no=request.POST.get("contract_no"),
                bill_series_from=request.POST.get("bill_start_date"),
                bill_series_to=request.POST.get("bill_end_date"),
                c_start_date=request.POST.get("c_start_date"),
                c_end_date=request.POST.get("c_end_date"),
                dc_field=request.POST.get("dc_field"),
                gc_note_required = True if request.POST.get("gc_note_required") == 'yes' else False,
                gc_series_from = request.POST.get("gc_start"),

                cp_name=request.POST.get("cp_name"),
                c_email=request.POST.get("c_email"),
                c_designation=request.POST.get("c_designation"),
                c_number=request.POST.get("c_number"),

                rate_type = request.POST.get("rate_type"),
                
                billing_address=request.POST.get("billing_address"),
                billing_state=request.POST.get("billing_state"),
                billing_city=request.POST.get("billing_city"),
                billing_pin=request.POST.get("billing_pin"),

                unloading_charge_1 = i_unloading_charge_1,
                unloading_charge_2 = i_unloading_charge_2,
                loading_charge = i_loading_charge,

                

                invoice_fields=request.POST.getlist("field")
            )

            rate_type = request.POST.get("rate_type")

            if rate_type in ["Kilometer-Wise"]:
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km"
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate.objects.create(
                        company_id=i_comapany_id,
                        contract=contract,
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value,
                        mt_per_km=mt_per_km_value
                    )
                messages.success(request, "Rate added successfully")


            elif rate_type == "Taluka-Wise":
                district_names = request.POST.getlist("district_name[]")

                for district_index, district_name in enumerate(district_names, start=1):
                    taluka_names = request.POST.getlist(f"taluka_name_{district_index}[]")
                    taluka_rates = request.POST.getlist(f"taluka_rate_{district_index}[]")

                    for t_name, t_rate in zip(taluka_names, taluka_rates):
                        Rate_taluka.objects.create(
                            company_id=i_comapany_id,
                            contract=contract,
                            rate_type="Taluka-Wise",
                            distric_name=district_name,
                            taluka_name=t_name,
                            mt=t_rate
                        )
                    messages.success(request, "Rate added successfully")
                    

            elif rate_type == "Distric-Wise":
                district_names = request.POST.getlist("district_name[]")
                values = request.POST.getlist("district_rate[]")

                for i, district in enumerate(district_names):
                    choice = request.POST.get(f"district_choice_{i+1}")  # radio for MT or MT/KM

                    if choice == "mt":
                        mt_value = values[i]
                        mt_per_km_value = 0
                    else:
                        mt_value = 0
                        mt_per_km_value = values[i]

                    Rate_District.objects.create(
                        company_id= i_comapany_id,
                        contract=contract,
                        rate_type="District-Wise",
                        distric_name=district,
                        mt=mt_value,
                        mt_per_km=mt_per_km_value,
                    )
                messages.success(request, "Rate added successfully")
            
            elif rate_type == "Incometax-Wise":
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km"
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate_IncomeTax.objects.create(
                        company_id=i_comapany_id,
                        contract=contract,
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value,
                        mt_per_km=mt_per_km_value
                    )
                messages.success(request, "Rate added successfully")

            elif rate_type == "Cumulative-Wise":
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km"
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate_Cumulative.objects.create(
                        company_id=i_comapany_id,
                        contract=contract,
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value,
                        mt_per_km=mt_per_km_value
                    )
                messages.success(request, "Rate added successfully")


            messages.success(request, "Contract created successfully")
            return redirect("new-contract-view")

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("new-contract-form")

    return render(request, "new-contract-2.html") 
    
def update_contract(request, ):
    contract_id = request.GET.get('contract_id')
    alldata = {}
    contract = get_object_or_404(T_Contract, id=contract_id , company_id=request.session['company_info']['company_id'])
    alldata['contract'] = contract
    if contract.rate_type in ["Kilometer-Wise", "Slab-Wise"]:
        rates = Rate.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id']).order_by('from_km')
        alldata['rates'] = rates
    elif contract.rate_type == "Taluka-Wise":
        taluka_rates = Rate_taluka.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id'])
        taluka_district = Rate_taluka.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id']).values_list('distric_name', flat=True).distinct()
        alldata['taluka_district'] = taluka_district
        alldata['taluka_rates'] = taluka_rates
    elif contract.rate_type == "Distric-Wise":
        rate_dist = Rate_District.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id']).order_by('id')
        alldata['rate_dist'] = rate_dist

    elif contract.rate_type == "Incometax-Wise":
        rate_income = Rate_IncomeTax.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id']).order_by('id')
        alldata['rate_income'] = rate_income

    elif contract.rate_type == "Cumulative-Wise":
        rate_cumulative = Rate_Cumulative.objects.filter(contract=contract.id , company_id=request.session['company_info']['company_id']).order_by('id')
        alldata['rate_cumulative'] = rate_cumulative
    
    if request.method == "POST":
        try:
            # Update contract fields
            contract.company_name = request.POST.get("company_name")
            contract.vendor_code = request.POST.get("vendor_code")
            contract.gst_number = request.POST.get("gst_number")
            contract.pan_number = request.POST.get("pan_number")
            contract.from_center = request.POST.get("from_center")

            contract.contract_no = request.POST.get("contract_no")
            contract.bill_series_from = request.POST.get("bill_start_date")
            contract.bill_series_to = request.POST.get("bill_end_date")
            contract.c_start_date = request.POST.get("c_start_date") or None
            contract.c_end_date = request.POST.get("c_end_date") or None
            contract.dc_field = request.POST.get("dc_field") or None
            contract.gc_note_required = True if request.POST.get("gc_note_required") == 'yes' else False
            contract.gc_series_from = request.POST.get("gc_start")

            contract.cp_name = request.POST.get("cp_name")
            contract.c_email = request.POST.get("c_email")
            contract.c_designation = request.POST.get("c_designation")
            contract.c_number = request.POST.get("c_number")


            contract.billing_address = request.POST.get("billing_address")
            contract.billing_state = request.POST.get("billing_state")
            contract.billing_city = request.POST.get("billing_city")
            contract.billing_pin = request.POST.get("billing_pin")

            if request.POST.get("unloading_rate_1") == 'yes':
                contract.unloading_charge_1 = request.POST.get("unloading_charge_1")
            else:
                contract.unloading_charge_1 = 0

            if request.POST.get("unloading_rate_2") == 'yes':
                contract.unloading_charge_2 = request.POST.get("unloading_charge_2")
            else:
                contract.unloading_charge_2 = 0

            if request.POST.get("loading_rate") == 'yes':
                contract.loading_charge = request.POST.get("loading_charge")
            else:
                contract.loading_charge = 0

            contract.rate_type = request.POST.get("rate_type")
            contract.invoice_fields = request.POST.getlist("field")

            # Save the contract first
            contract.save()

            # Clear old rates (so we can replace with new ones)
            Rate.objects.filter(contract=contract , company_id = request.session['company_info']['company_id']).delete()
            Rate_taluka.objects.filter(contract=contract ,company_id=request.session['company_info']['company_id']).delete()
            Rate_District.objects.filter(contract=contract ,company_id=request.session['company_info']['company_id']).delete()
            Rate_IncomeTax.objects.filter(contract=contract ,company_id=request.session['company_info']['company_id']).delete()
            Rate_Cumulative.objects.filter(contract=contract ,company_id=request.session['company_info']['company_id']).delete()

            rate_type = request.POST.get("rate_type")

            if rate_type in ["Kilometer-Wise", "Slab-Wise"]:
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km" 
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate.objects.create(
                        company_id=contract.company_id,
                        contract=contract, 
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value, 
                        mt_per_km=mt_per_km_value
                    ) 
       
            elif rate_type == "Taluka-Wise":
                district_names = request.POST.getlist("district_name[]")

                for district_index, district_name in enumerate(district_names, start=1):
                    taluka_names = request.POST.getlist(f"taluka_name_{district_index}[]")
                    taluka_rates = request.POST.getlist(f"taluka_rate_{district_index}[]")

                    for t_name, t_rate in zip(taluka_names, taluka_rates):
                        Rate_taluka.objects.create(
                            company_id=contract.company_id,
                            contract=contract,
                            rate_type="Taluka-Wise",
                            distric_name=district_name,
                            taluka_name=t_name,
                            mt=t_rate
                        )

            elif rate_type == "Distric-Wise":
                district_names = request.POST.getlist("district_name[]")
                values = request.POST.getlist("district_rate[]")

                for i, district in enumerate(district_names):
                    choice = request.POST.get(f"district_choice_{i+1}")  # radio for MT or MT/KM

                    if choice == "mt":
                        mt_value = values[i]
                        mt_per_km_value = 0
                    else:
                        mt_value = 0
                        mt_per_km_value = values[i]

                    Rate_District.objects.create(
                        company_id= contract.company_id,
                        contract=contract,
                        rate_type="District-Wise",
                        distric_name=district,
                        mt=mt_value,
                        mt_per_km=mt_per_km_value,
                    )
            elif rate_type == "Incometax-Wise":
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km"
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate_IncomeTax.objects.create(
                        company_id=contract.company_id,
                        contract=contract,
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value,
                        mt_per_km=mt_per_km_value
                    )
            elif rate_type == "Cumulative-Wise":
                from_km_list = request.POST.getlist("from_km[]")
                to_km_list = request.POST.getlist("to_km[]")
                value_list = request.POST.getlist("value[]")

                for i in range(len(from_km_list)):
                    choice = request.POST.get(f"choice_{i+1}")   # radio button value for that row
                    if choice == "mt":
                        mt_value = value_list[i]
                        mt_per_km_value = 0
                    else:  # choice == "mt_per_km"
                        mt_value = 0
                        mt_per_km_value = value_list[i]

                    Rate_Cumulative.objects.create(
                        company_id=contract.company_id,
                        contract=contract,
                        rate_type=rate_type,
                        from_km=from_km_list[i],
                        to_km=to_km_list[i],
                        mt=mt_value,
                        mt_per_km=mt_per_km_value
                    )

            Destination.objects.filter(company_id=contract.company_id,
                contract_id=contract_id,).update(
                from_center=contract.from_center,
            )
            messages.success(request, "Contract updated successfully")
            return redirect("new-contract-view")  # go back to contract list

        except Exception as e:
            messages.error(request, f"Error updating contract: {str(e)}")
            return redirect(f"/update-contract-form?contract_id={contract_id}")

    return render(request, "update-contract-2.html", alldata)


@session_required 
def new_contract_view_2(request):
    company = request.session.get('company_info')
    delete_id = request.GET.get('delete') 
    if delete_id:
        try:
            dcontract = T_Contract.objects.get(id=delete_id, company_id_id=company['company_id'])
            dcontract.delete()
            messages.success(request, "Contract deleted successfully!")
        except T_Contract.DoesNotExist:
            messages.error(request, "Contract does not exist!")
        return redirect('new-contract-view')
    alldata = {}

    try:
        contract = T_Contract.objects.filter(company_id=company['company_id']).order_by('-id')
        alldata['all_contract'] = contract
    except T_Contract.DoesNotExist:
        messages.error(request, "Contract does not exist!")
        return redirect('dashboard')  

    return render(request, 'new-contract-view-2.html', alldata)



@session_required
def dispatch_form(request):
    alldata = {"errors": {}}
    try:
        allcontract = T_Contract.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['allcontract'] = allcontract
    except T_Contract.DoesNotExist:
        messages.error(request, "Contract not found!")
        return redirect('rent-slip')
    
    if request.method == "POST":
        form_data = request.POST
        errors = {}
        # Ensure km is numeric before attempting to save
        km_raw = request.POST.get("km")
        try:
            km_value = int(km_raw) if km_raw not in [None, ""] else 0
        except (TypeError, ValueError):
            errors["km"] = "KM must be a number."

        if errors:
            alldata["errors"] = errors
            alldata["form_data"] = form_data
            return render(request, 'dispatch-form.html', alldata)

        # Check for duplicate challan_no
        challan_no = request.POST.get("challan_no", "").strip()
        company_id = request.session['company_info']['company_id']
        
        # Validate challan_no is not empty
        if not challan_no:
            alldata['form_data'] = request.POST
            alldata['challan_error'] = "Challan No. is required."
            return render(request, 'dispatch-form.html', alldata)
        
        # Check for duplicate challan_no (case-insensitive and trimmed)
        if Dispatch.objects.filter(challan_no__iexact=challan_no, company_id=company_id).exists():
            # Pass POST data back to repopulate form
            alldata['form_data'] = request.POST
            alldata['challan_error'] = f"Challan No. '{challan_no}' already exists. Please use a different challan number."
            return render(request, 'dispatch-form.html', alldata)

        i_destination = request.POST.get("destination")

        if i_destination.isdigit():    
            try : 
                d_destination = Destination.objects.get(id=i_destination , company_id=request.session['company_info']['company_id'])
                save_destination = d_destination.destination
            except Destination.DoesNotExist:
                pass
        else:
            save_destination = i_destination

        from datetime import date
        dep_date_value = request.POST.get("dep_date")
        if not dep_date_value:
            dep_date_value = date.today()
        
        dispatch = Dispatch.objects.create(
            company_id = Company_user.objects.get(id=request.session['company_info']['company_id']),
            contract_id= T_Contract.objects.get(id=request.POST.get("contract_id")),
            dep_date=dep_date_value,
            challan_no=challan_no,    
            truck_no=request.POST.get("truck_no"),
            product_name=request.POST.get("product_name"),
            party_name=request.POST.get("party_name"),
            from_center=request.POST.get("from_center"),
            destination=save_destination,
            taluka=request.POST.get("taluka"),
            district=request.POST.get("district"),
            weight=request.POST.get("weight") or 0,
            rate=request.POST.get("rate") or 0,
            totalfreight=request.POST.get("totalfreight") or 0,
            unloading_charge_1=request.POST.get("unloading_charge_1") or 0,
            unloading_charge_2=request.POST.get("unloading_charge_2") or 0,
            loading_charge=request.POST.get("loading_charge") or 0,
            grand_total=request.POST.get("grand_total") or 0,
            truck_booking_rate=request.POST.get("truck_booking_rate") or 0,
            total_paid_truck_onwer=request.POST.get("total_paid_truck_onwer") or 0,
            advance_paid=request.POST.get("advance_paid") or 0,
            panding_amount=request.POST.get("panding_amount") or 0,
            net_profit=request.POST.get("net_profit") or 0,
            km=km_value,
        )

        # Save Destination if not exists
        Destination.objects.get_or_create(
            company_id = Company_user.objects.get(id=request.session['company_info']['company_id']),
            contract_id= T_Contract.objects.get(id=request.POST.get("contract_id")),          
            from_center=request.POST.get("from_center"),
            destination=save_destination ,
            district=request.POST.get("district"),
            taluka=request.POST.get("taluka"),
            km=km_value,
        )
        messages.success(request, "Dispatch Added successfully")
        return redirect("dispatch-view")

    return render(request, 'dispatch-form.html' ,alldata)


@session_required
def dispatch_update(request):
    dispatch_id = request.GET.get('dispatch_id')
    if not dispatch_id:
        messages.error(request, "Dispatch ID is required")
        return redirect("dispatch-view")
    
    alldata = {}
    # Fetch all contracts for dropdown or display
    allcontract = T_Contract.objects.filter(company_id=request.session['company_info']['company_id'])
    alldata['allcontract'] = allcontract
    # Fetch the dispatch to edit
    dispatch = get_object_or_404(Dispatch, id=dispatch_id, company_id=request.session['company_info']['company_id'])
    alldata['dispatch'] = dispatch

    alldestination = Destination.objects.filter(company_id=request.session['company_info']['company_id'] , contract_id=dispatch.contract_id)
    alldata['alldestination'] = alldestination
    
    # Find matching destination ID for current dispatch destination
    current_destination_id = None
    if dispatch.destination:
        try:
            matching_dest = Destination.objects.filter(
                company_id=request.session['company_info']['company_id'],
                contract_id=dispatch.contract_id,
                destination=dispatch.destination
            ).first()
            if matching_dest:
                current_destination_id = matching_dest.id
        except:
            pass
    alldata['current_destination_id'] = current_destination_id

    if request.method == "POST":
        try:
            # Check for duplicate challan_no (excluding current dispatch)
            challan_no = request.POST.get("challan_no", "").strip()
            company_id = request.session['company_info']['company_id']
            
            # Validate challan_no is not empty
            if not challan_no:
                alldata['challan_error'] = "Challan No. is required."
                alldata['dispatch'] = dispatch
                return render(request, 'dispatch-update.html', alldata)
            
            # Check for duplicate challan_no (case-insensitive and trimmed, excluding current dispatch)
            if Dispatch.objects.filter(challan_no__iexact=challan_no, company_id=company_id).exclude(id=dispatch.id).exists():
                # Update dispatch object with POST data to preserve form values
                alldata['challan_error'] = f"Challan No. '{challan_no}' already exists. Please use a different challan number."
                dispatch.challan_no = challan_no
                dispatch.dep_date = request.POST.get("dep_date")
                dispatch.truck_no = request.POST.get("truck_no")
                dispatch.product_name = request.POST.get("product_name")
                dispatch.party_name = request.POST.get("party_name")
                dispatch.from_center = request.POST.get("from_center")
                dispatch.taluka = request.POST.get("taluka")
                dispatch.district = request.POST.get("district")
                dispatch.km = request.POST.get("km") or 0
                dispatch.weight = request.POST.get("weight") or 0
                dispatch.rate = request.POST.get("rate") or 0
                dispatch.totalfreight = request.POST.get("totalfreight") or 0
                # Handle conditional charges based on radio button selections
                if request.POST.get("unloading_rate_1") == 'yes':
                    dispatch.unloading_charge_1 = request.POST.get("unloading_charge_1") or 0
                else:
                    dispatch.unloading_charge_1 = 0
                if request.POST.get("unloading_rate_2") == 'yes':
                    dispatch.unloading_charge_2 = request.POST.get("unloading_charge_2") or 0
                else:
                    dispatch.unloading_charge_2 = 0
                if request.POST.get("loading_rate") == 'yes':
                    dispatch.loading_charge = request.POST.get("loading_charge") or 0
                else:
                    dispatch.loading_charge = 0
                dispatch.grand_total = request.POST.get("grand_total") or 0
                dispatch.truck_booking_rate = request.POST.get("truck_booking_rate") or 0
                dispatch.total_paid_truck_onwer = request.POST.get("total_paid_truck_onwer") or 0
                dispatch.advance_paid = request.POST.get("advance_paid") or 0
                dispatch.panding_amount = request.POST.get("panding_amount") or 0
                dispatch.net_profit = request.POST.get("net_profit") or 0
                # Handle destination
                i_destination = request.POST.get("destination")
                if i_destination and i_destination.isdigit():
                    try:
                        d_destination = Destination.objects.get(id=i_destination, company_id=request.session['company_info']['company_id'])
                        dispatch.destination = d_destination.destination
                    except Destination.DoesNotExist:
                        dispatch.destination = i_destination
                else:
                    dispatch.destination = i_destination or ""
                alldata['dispatch'] = dispatch
                # Update current_destination_id if needed
                if i_destination and i_destination.isdigit():
                    alldata['current_destination_id'] = int(i_destination)
                return render(request, 'dispatch-update.html', alldata)
            
            # Handle destination - same logic as dispatch_form
            i_destination = request.POST.get("destination")
            if i_destination and i_destination.isdigit():    
                try: 
                    d_destination = Destination.objects.get(id=i_destination, company_id=request.session['company_info']['company_id'])
                    save_destination = d_destination.destination
                except Destination.DoesNotExist:
                    save_destination = i_destination
            else:
                save_destination = i_destination or ""

            # Update contract if changed
            if request.POST.get("contract_id"):
                dispatch.contract_id = T_Contract.objects.get(id=request.POST.get("contract_id"))
            
            # Update all fields from POST
            dispatch.dep_date = request.POST.get("dep_date")
            dispatch.challan_no = challan_no
            dispatch.truck_no = request.POST.get("truck_no")
            dispatch.product_name = request.POST.get("product_name")
            dispatch.party_name = request.POST.get("party_name")
            dispatch.from_center = request.POST.get("from_center")
            dispatch.destination = save_destination
            dispatch.taluka = request.POST.get("taluka")
            dispatch.district = request.POST.get("district")
            dispatch.km = request.POST.get("km") or 0
            dispatch.weight = request.POST.get("weight") or 0
            dispatch.rate = request.POST.get("rate") or 0
            dispatch.totalfreight = request.POST.get("totalfreight") or 0
            dispatch.unloading_charge_1 = request.POST.get("unloading_charge_1") or 0
            dispatch.unloading_charge_2 = request.POST.get("unloading_charge_2") or 0
            dispatch.loading_charge = request.POST.get("loading_charge") or 0
            dispatch.grand_total = request.POST.get("grand_total") or 0
            dispatch.truck_booking_rate = request.POST.get("truck_booking_rate") or 0
            dispatch.total_paid_truck_onwer = request.POST.get("total_paid_truck_onwer") or 0
            dispatch.advance_paid = request.POST.get("advance_paid") or 0
            dispatch.panding_amount = request.POST.get("panding_amount") or 0
            dispatch.net_profit = request.POST.get("net_profit") or 0

            dispatch.save()

            # Update or create Destination
            Destination.objects.update_or_create(
                company_id = Company_user.objects.get(id=request.session['company_info']['company_id']),
                contract_id= dispatch.contract_id,
                from_center=request.POST.get("from_center"),
                destination=save_destination,
                district=request.POST.get("district"),
                taluka=request.POST.get("taluka"),
                defaults={"km": request.POST.get("km") or 0},
            )

            messages.success(request, "Dispatch updated successfully")
            return redirect("dispatch-view")

        except Exception as e:
            messages.error(request, f"Error updating dispatch: {str(e)}")
            return redirect(f"/dispatch-update?dispatch_id={dispatch_id}")

    return render(request, 'dispatch-update.html', alldata)

@session_required
def dispatch_view(request):
    alldata = {}
    company = request.session.get('company_info')

    s_challan_no = request.GET.get('s_challan_no', "")
    start_date = request.GET.get('start_date', "")
    end_date = request.GET.get('end_date', "")
    delete_id = request.GET.get('delete')

    # Base Query
    dispatch_qs = Dispatch.objects.filter(company_id=company['company_id']).order_by('-id')

    # ✅ Search by Challan No
    if s_challan_no:
        dispatch_qs = dispatch_qs.annotate(
            col_str=Func('challan_no', function='CAST', template='CAST(%(expressions)s AS CHAR)')
        ).filter(col_str__icontains=s_challan_no)

    # ✅ Search by Date Range
    if start_date and end_date:
        dispatch_qs = dispatch_qs.filter(dep_date__range=[start_date, end_date]).order_by('dep_date')

    elif start_date:
        dispatch_qs = dispatch_qs.filter(dep_date=start_date).order_by('dep_date')
    elif end_date:
        dispatch_qs = dispatch_qs.filter(dep_date__lte=end_date).order_by('dep_date')

    alldata["all_dispatch"] = dispatch_qs

    # Totals for visible rows (respecting filters)
    totals = dispatch_qs.aggregate(
        total_weight=Sum('weight'),
        total_rate=Sum('rate'),
        total_freight=Sum('totalfreight'),
        total_unloading_1=Sum('unloading_charge_1'),
        total_unloading_2=Sum('unloading_charge_2'),
        total_loading=Sum('loading_charge'),
        total_grand_total=Sum('grand_total'),
        total_paid=Sum('total_paid_truck_onwer'),
        total_advance=Sum('advance_paid'),
        total_pending=Sum('panding_amount'),
        total_net_profit=Sum('net_profit'),
    )
    # replace None with 0 for display
    alldata["totals"] = {k: v or 0 for k, v in totals.items()}

    # Keep filter values in template
    alldata["s_challan_no"] = s_challan_no
    alldata["start_date"] = start_date
    alldata["end_date"] = end_date

    # Delete Logic
    if delete_id:   
        try:
            ddispatch = Dispatch.objects.get(id=delete_id, company_id_id=company['company_id'])
            ddispatch.delete()
            messages.success(request, "Dispatch deleted successfully!")
        except Dispatch.DoesNotExist:
            messages.error(request, "Dispatch does not exist!")
        return redirect('dispatch-view')

    return render(request, 'dispatch-view.html', alldata)





@session_required
def create_dispatch_Invoice(request):
    alldata = {}
    try:
        allcontract = T_Contract.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['allcontract'] = allcontract
    except T_Contract.DoesNotExist:
        messages.error(request , 'Contract not fonded')
    return render(request, 'dispatch-invoice.html' , alldata)

@session_required
def view_dispatch_Invoice(request):
    alldata = {}
    try:
        allcontract = Invoice.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['allinvoice'] = allcontract
    except Invoice.DoesNotExist:
        messages.error(request , 'Invoice not fonded')
    return render(request, 'view-dispatch-invoice.html' , alldata)

@session_required
def update_dispatch_Invoice(request):
    alldata = {}
    try:
        allcontract = Invoice.objects.filter(company_id=request.session['company_info']['company_id'])
        alldata['allinvoice'] = allcontract
    except Invoice.DoesNotExist:
        messages.error(request, 'Invoice not found.')

    if request.method == "POST":
        dbill_id = request.POST.get("bill_no")  # existing invoice id
        dcontract_no = request.POST.get("contract_no")
        dispatch_ids = [int(i) for i in request.POST.getlist("dispatch_ids")]
        i_bill_no = request.POST.get("bill_no")
        bill_date_str = request.POST.get("bill_date")
        rr_number = request.POST.get("rr_number", "").strip()
        # Validation    
        if not dbill_id or not dcontract_no:
            messages.error(request, "Invalid request: missing invoice or contract.")
            return redirect("update-dispatch-invoice")
     
        if not dispatch_ids:
            messages.error(request, "Please select at least one dispatch to update invoice.")
            return redirect("update-dispatch-invoice")

        # Fetch objects
        try:
            contract = T_Contract.objects.get(contract_no=dcontract_no)
            company = Company_user.objects.get(id=request.session['company_info']['company_id'])
            invoice = get_object_or_404(Invoice, id=dbill_id, company_id=company, contract_id=contract)
        except (T_Contract.DoesNotExist, Company_user.DoesNotExist):
            messages.error(request, "Invalid contract or company.")
            return redirect("update-dispatch-invoice")

        # Convert date safely
        bill_date = None
        if bill_date_str:
            try:
                bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Invalid bill date format.")
                return redirect("update-dispatch-invoice")

        # Check for duplicate Bill_no (excluding current invoice)
        if Invoice.objects.filter(
            Bill_no=invoice.Bill_no,   
            company_id=company,
            contract_id=contract
        ).exclude(id=invoice.id).exists():
            messages.error(request, "Another invoice with this bill number already exists.")
            return redirect("update-dispatch-invoice")

        # Wrap everything in a transaction
        with transaction.atomic():
            # --- Update invoice fields ---
            invoice.Bill_no = invoice.Bill_no
            invoice.Bill_date = bill_date
            invoice.rr_number = rr_number if rr_number else None
            invoice.contract_id = contract
            invoice.company_id = company
            invoice.save()

            # --- Update dispatch list ---
            new_dispatches = Dispatch.objects.filter(id__in=dispatch_ids).order_by("dep_date")
            current_dispatches = list(invoice.dispatch_list.all())

            # Replace existing list
            invoice.dispatch_list.set(new_dispatches)

            # --- Set inv_status = True for new ones ---
            for d in new_dispatches:
                d.inv_status = True
                d.save()

            # --- Set inv_status = False for removed ones ---
            removed_dispatches = [d for d in current_dispatches if d not in new_dispatches]
            for d in removed_dispatches:
                d.inv_status = False
                d.gc_note_no = None
                d.save()

            # --- Remove old GC Notes ---
            if contract.gc_note_required:
                GC_Note.objects.filter(bill_id=invoice).delete()

                # --- Create new GC Notes ---
                for d in new_dispatches:
                    if GC_Note.objects.filter(contract_id=contract.id).exists():
                                    last_gc = GC_Note.objects.filter(contract_id=contract.id).latest('id')
                                    gc_no = last_gc.gc_no + 1
                    else:
                        gc_no = contract.gc_series_from
                    gc_note = GC_Note.objects.create(
                        gc_no=str(gc_no),
                        gc_date=bill_date,
                        consignor=contract.company_name,
                        consignee=d.party_name,
                        dispatch_from=contract.from_center,
                        dc_field=d.challan_no,
                        destination=d.destination,
                        product_name=d.product_name,
                        weight=d.weight,
                        truck_no=d.truck_no,
                        district=d.district,
                        bill_no=invoice.Bill_no,
                        bill_id=invoice,
                        dispatch_id=d,
                        contract_id=contract,
                        company_id=company
                    )
                    # Update dispatch GC reference
                    d.gc_note_no = gc_note.gc_no
                    d.save()

        # If everything succeeded, commit and show success
        messages.success(request, f"Invoice {i_bill_no} updated successfully.")
        return redirect("update-dispatch-invoice")

    return render(request, 'update-dispatch-invoice.html', alldata)

@session_required
def view_gc_note(request):
    alldata = {}
    try:
        allcontract = Invoice.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['allinvoice'] = allcontract
    except Invoice.DoesNotExist:
        messages.error(request , 'Invoice not fonded')
    return render(request, 'view-gc-note.html' , alldata)

@session_required
def Rate_master_view(request):
    alldata = {}
    try:
        allcontract = T_Contract.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['allcontract'] = allcontract
    except T_Contract.DoesNotExist:
        messages.error(request , 'Rate not fonded')

    return render(request , 'rate-master-view.html' , alldata)

@session_required
def rout_view(request):
    alldata = {}
    try:
        allroute = Destination.objects.all().filter(company_id=request.session['company_info']['company_id'])
        alldata['all_routes'] = allroute
    except Destination.DoesNotExist:
        messages.error(request , 'Route not fonded')
    return render(request , 'rout-view.html' , alldata)

@session_required
def product_master_view(request):
    """List unique products created through dispatches for the current company."""
    products = (
        Dispatch.objects.filter(company_id=request.session["company_info"]["company_id"])
        .exclude(product_name__isnull=True)
        .exclude(product_name__exact="")
        .values("product_name")
        .annotate(
            total_dispatches=Count("id"),
            contract_count=Count("contract_id", distinct=True),
            last_dispatch_date=Max("dep_date"),
        )
        .order_by("product_name")
    )

    return render(request, "product-master-view.html", {"products": products})
