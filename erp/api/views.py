from django.http import JsonResponse
from django.core.cache import cache
from erp.utils.csv_export import csv_response
from erp.utils.decorators import session_required
from erp.utils.financial_year import filter_by_financial_year, get_current_financial_year
from transport.models import (
    T_Contract,
    Destination,
    Dispatch,
    Invoice,
    GC_Note,
    Rate,
    Rate_IncomeTax,
    Rate_Cumulative,
    Rate_taluka,
    Rate_District,
)
import re
from decimal import Decimal
from datetime import datetime

## CONTRACT DETAILS FETCHING ##

@session_required
def get_contract_details(request):
    dcontract_id = request.GET.get('contract_id')
    try:
        contract = T_Contract.objects.get(id=dcontract_id , company_id = request.session['company_info']['company_id'])

        try:
            destination = Destination.objects.filter(contract_id=dcontract_id , company_id = request.session['company_info']['company_id']).values('id','destination','km')

            return JsonResponse({
                'from' : contract.from_center,
                'unloading_charge_1' : contract.unloading_charge_1 if contract.unloading_charge_1 else 0,
                'unloading_charge_2' : contract.unloading_charge_2 if contract.unloading_charge_2 else 0,
                'loading_charge' : contract.loading_charge if contract.loading_charge else 0,
                'destinations': list(destination),
                "rate_type" : contract.rate_type,
                'invoice_fields': contract.invoice_fields if contract.invoice_fields else [],
            })
        except Destination.DoesNotExist:
            return JsonResponse({
                'from' : contract.from_center,
                'from' : contract.from_center,
                'unloading_charge_1' : contract.unloading_charge_1 if contract.unloading_charge_1 else 0,
                'unloading_charge_2' : contract.unloading_charge_2 if contract.unloading_charge_2 else 0,
                'loading_charge' : contract.loading_charge if contract.loading_charge else 0,
                "rate_type" : contract.rate_type,
                'invoice_fields': contract.invoice_fields if contract.invoice_fields else [],
            })
        
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    


@session_required
def get_destination_details(request):
    """
    Fetch destination details for the dispatch form.

    Behaviour:
    - If `did` is a valid Destination primary key, return that record.
    - Otherwise, treat `did` as a destination name and try to resolve it
      within the current contract + company so that:
        * Typing/creating a destination that already exists will still
          auto-fill taluka, district and km.
    """
    did = (request.GET.get("did") or "").strip()
    contract_id = request.GET.get("contract_id")
    company_id = request.session["company_info"]["company_id"]

    if not did:
        return JsonResponse({"error": "did is required"}, status=400)

    destination = None

    # 1) Try to resolve by primary key ID (existing select option)
    if did.isdigit():
        destination = Destination.objects.filter(id=did, company_id=company_id).first()

    # 2) If not found, resolve by destination name for given contract+company
    if destination is None and contract_id:
        destination = (
            Destination.objects.filter(
                company_id=company_id,
                contract_id=contract_id,
                destination__iexact=did,
            ).first()
        )

    # 3) Fallback: by name within company (any contract)
    if destination is None:
        destination = (
            Destination.objects.filter(
                company_id=company_id,
                destination__iexact=did,
            ).first()
        )

    if destination is None:
        # Let the frontend know nothing was found so user can enter manually
        return JsonResponse({"found": False})

    return JsonResponse(
        {
            "found": True,
            "district": destination.district,
            "taluka": destination.taluka or "",
            "km": destination.km,
            "rate_type": destination.contract_id.rate_type,
        }
    )


@session_required
def get_taluka_district(request):
    """
    Given a taluka and contract, try to infer the district automatically.

    We first look at Destination records, then fall back to past Dispatch
    records for the same contract + company.
    """
    taluka = (request.GET.get("taluka") or "").strip()
    contract_id = request.GET.get("contract-id")
    company_id = request.session["company_info"]["company_id"]

    if not taluka or not contract_id:
        return JsonResponse(
            {"found": False, "error": "taluka and contract-id are required"},
            status=400,
        )

    # 1) Prefer Destination mappings
    district = (
        Destination.objects.filter(
            company_id=company_id,
            contract_id=contract_id,
            taluka__iexact=taluka,
        )
        .values_list("district", flat=True)
        .distinct()
        .first()
    )

    # 2) Fallback to previous Dispatch entries
    if not district:
        district = (
            Dispatch.objects.filter(
                company_id=company_id,
                contract_id=contract_id,
                taluka__iexact=taluka,
            )
            .values_list("district", flat=True)
            .distinct()
            .first()
        )

    if not district:
        return JsonResponse({"found": False})

    return JsonResponse({"found": True, "district": district})


@session_required
def check_challan_duplicate(request):
    challan_no = request.GET.get('challan_no', '').strip()
    dispatch_id = request.GET.get('dispatch_id')  # For update form, exclude current dispatch
    company_id = request.session['company_info']['company_id']
    
    if not challan_no:
        return JsonResponse({'exists': False, 'valid': False})
    
    # Check for duplicate challan_no (case-insensitive and trimmed)
    query = Dispatch.objects.filter(challan_no__iexact=challan_no, company_id=company_id)
    
    # If updating, exclude the current dispatch
    if dispatch_id:
        query = query.exclude(id=dispatch_id)
    
    exists = query.exists()
    
    return JsonResponse({
        'exists': exists,
        'valid': not exists
    })


@session_required
def check_contract_duplicate(request):
    contract_no = request.GET.get('contract_no', '').strip()
    contract_id = request.GET.get('contract_id')  # For update form, exclude current contract
    company_id = request.session['company_info']['company_id']
    
    if not contract_no:
        return JsonResponse({'exists': False, 'valid': False})
    
    # Check for duplicate contract_no (case-insensitive and trimmed)
    query = T_Contract.objects.filter(contract_no__iexact=contract_no, company_id=company_id)
    
    # If updating, exclude the current contract
    if contract_id:
        query = query.exclude(id=contract_id)
    
    exists = query.exists()
    
    return JsonResponse({
        'exists': exists,
        'valid': not exists
    })


@session_required
def get_districts(request):
    """Fetch all unique districts for a given contract"""
    dcontract_id = request.GET.get('contract-id')
    try:
        contract = T_Contract.objects.get(id=dcontract_id)
        # Get unique districts from dispatches for this contract
        districts = Dispatch.objects.filter(
            contract_id=dcontract_id,
            company_id=request.session['company_info']['company_id']
        ).values_list('district', flat=True).distinct().order_by('district')
        
        # Filter out empty/null districts
        districts = [d for d in districts if d]
        
        return JsonResponse({
            'districts': list(districts),
        })
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'contract not found'}, status=404)

@session_required
def get_dispacth(request):
    dcontract_id = request.GET.get('contract-id')
    district_filter = request.GET.get('district', '').strip()
    financial_year = request.session.get('financial_year', get_current_financial_year())
    try:
        contract = T_Contract.objects.get(id=dcontract_id)
        try:
            # Only fetch dispatches which are **not** already linked to any invoice
            # so that already-billed entries do not appear again on invoice creation.
            dispatch = Dispatch.objects.filter(
                contract_id=dcontract_id,
                company_id=request.session['company_info']['company_id'],
                inv_status=False,
            )
            
            # Filter by financial year
            dispatch = filter_by_financial_year(dispatch, financial_year, 'dep_date')
            
            # Filter by district if provided
            if district_filter:
                dispatch = dispatch.filter(district=district_filter)
            
            dispatch = dispatch.values().order_by('dep_date')

            inv = Invoice.objects.filter(company_id = request.session['company_info']['company_id'], contract_id = dcontract_id).order_by('-id').first()

            # Extract last numeric part
            if inv:
                bill_no = inv.Bill_no
                match = re.search(r'(\d+)$', bill_no)  # e.g. 'INV-001'
                if match:
                    num_str = match.group(1)             # e.g. '001'
                    new_num = str(int(num_str) + 1).zfill(len(num_str))  # keep zero padding
                    new_bill_no = re.sub(r'\d+$', new_num, bill_no)  # replace last number with new one

            return JsonResponse({
                'fields' : contract.invoice_fields,
                'destinations': list(dispatch),
                'bill_no' : new_bill_no if inv else contract.bill_series_from,
            })
        except Dispatch.DoesNotExist:
            return JsonResponse({
               'error': 'not dispatch found' 
            })

    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'not con found'}, status=404)



@session_required
def get_ninv_dispacth(request):                  # ninv means not in invoice dispatch
    dbill_id = request.GET.get('bill-id')
    financial_year = request.session.get('financial_year', get_current_financial_year())
    if not dbill_id:
        return JsonResponse({'error': 'bill-id is required'}, status=400)
    
    try:
        invoice = Invoice.objects.get(id=dbill_id , company_id = request.session['company_info']['company_id'])
        contract = T_Contract.objects.get(id=invoice.contract_id.id)
        # Include inv_status explicitly to ensure it's in the response
        dispatch = Dispatch.objects.filter(contract_id=invoice.contract_id.id , company_id = request.session['company_info']['company_id'], inv_status = False)
        
        # Filter by financial year
        dispatch = filter_by_financial_year(dispatch, financial_year, 'dep_date')
        
        dispatch = dispatch.values('id', 'challan_no', 'dep_date', 'truck_no', 'product_name', 
                                                      'party_name', 'from_center', 'destination', 'taluka', 'district',
                                                      'km', 'weight', 'rate', 'totalfreight', 'unloading_charge_1',
                                                      'unloading_charge_2', 'loading_charge', 'grand_total', 
                                                      'gc_note_no', 'inv_status').order_by('dep_date')

        return JsonResponse({
            'fields' : contract.invoice_fields,
            'destinations': list(dispatch),
        })

    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'invoice not found'}, status=404)
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'contract not found'}, status=404)



@session_required
def get_gc(request):  
    bill_id = request.GET.get('bill-id')
    if (request.GET.get("format") or "").lower() == "csv":
        # Export GC notes for the selected invoice as CSV
        gc_qs = (
            GC_Note.objects.filter(
                bill_id_id=bill_id,
                company_id=request.session['company_info']['company_id'],
            )
            .order_by("gc_no")
        )
        header = [
            "GC No",
            "Bill No",
            "GC Date",
            "Consignor",
            "Consignee",
            "DC Field",
            "Dispatch From",
            "Destination",
            "District",
            "Product Name",
            "Truck No",
            "Weight",
        ]
        rows = (
            (
                g.gc_no,
                g.bill_no,
                g.gc_date,
                g.consignor,
                g.consignee,
                g.dc_field,
                g.dispatch_from,
                g.destination,
                g.district,
                g.product_name,
                g.truck_no,
                g.weight,
            )
            for g in gc_qs
        )
        return csv_response(filename="gc_notes_backup", header=header, rows=rows)
    try:
        gc = GC_Note.objects.filter(bill_id_id=bill_id , company_id = request.session['company_info']['company_id']).values().order_by('gc_no')   
        fields = [
            'gc_no',
            'bill_no',
            'gc_date' ,
            'consignor' ,
            'consignee', 
            'dc_field',
            'dispatch_from',
            'destination',
            'district' ,
            'product_name',
            'truck_no',
            'weight', 
            ]

        return JsonResponse({  
            'fields' : fields,
            'destinations': list(gc),
        })

    except Invoice.DoesNotExist:
        return JsonResponse({
           'error': 'dispatch not found' 
        })
    
@session_required
def get_invoice(request):  
    bill_id = request.GET.get('bill-id')
    try:
        invoice = Invoice.objects.get(id=bill_id , company_id = request.session['company_info']['company_id'])

    except Invoice.DoesNotExist:
        return JsonResponse({
           'error': 'dispatch not found' 
        })
    if invoice:
        contract_id = invoice.contract_id.id
        try:
            contract = T_Contract.objects.get(id=contract_id)
            # Include inv_status explicitly to ensure it's in the response
            dispatch = invoice.dispatch_list.values('id', 'challan_no', 'dep_date', 'truck_no', 'product_name', 
                                                      'party_name', 'from_center', 'destination', 'taluka', 'district',
                                                      'km', 'weight', 'rate', 'totalfreight', 'unloading_charge_1',
                                                      'unloading_charge_2', 'loading_charge', 'grand_total', 
                                                      'gc_note_no', 'inv_status', 'main_party', 'sub_party').order_by('dep_date')
            if (request.GET.get("format") or "").lower() == "csv":
                header = [
                    "Challan No",
                    "Dep Date",
                    "Truck No",
                    "Product Name",
                    "Party Name",
                    "From",
                    "Destination",
                    "Taluka",
                    "District",
                    "KM",
                    "Weight",
                    "Rate",
                    "Total Freight",
                    "Unloading 1",
                    "Unloading 2",
                    "Loading",
                    "Grand Total",
                    "GC Note No",
                    "Main Party",
                    "Sub Party",
                ]
                rows = (
                    (
                        d.get("challan_no", ""),
                        d.get("dep_date", ""),
                        d.get("truck_no", ""),
                        d.get("product_name", ""),
                        d.get("party_name", ""),
                        d.get("from_center", ""),
                        d.get("destination", ""),
                        d.get("taluka", ""),
                        d.get("district", ""),
                        d.get("km", ""),
                        d.get("weight", ""),
                        d.get("rate", ""),
                        d.get("totalfreight", ""),
                        d.get("unloading_charge_1", ""),
                        d.get("unloading_charge_2", ""),
                        d.get("loading_charge", ""),
                        d.get("grand_total", ""),
                        d.get("gc_note_no", ""),
                        d.get("main_party", ""),
                        d.get("sub_party", ""),
                    )
                    for d in dispatch
                )
                safe_bill = str(invoice.Bill_no or "invoice").replace("/", "-")
                return csv_response(filename=f"invoice_{safe_bill}_backup", header=header, rows=rows)
            return JsonResponse({
           'bill_date': invoice.Bill_date,  
            'contract_no' : contract.contract_no, 
            'contract_id' : contract.id,
            'rr_number' : invoice.rr_number or '',     
            'destinations' : list(dispatch),
            'fields' : contract.invoice_fields,
        })

        except T_Contract.DoesNotExist:
            return JsonResponse({'error': 'contract not found'}, status=404)
        




## RATE DETAILS FETCHING ##

## KM WISE RATE ##

@session_required
def get_rate_details(request):
    km = request.GET.get("km")
    dcontract_no = request.GET.get("contract_no")

    if not km or not dcontract_no:
        return JsonResponse({"error": "km and contract_id required"}, status=400)

    try:
        km = float(km)
        
        rate = Rate.objects.filter(
            company_id = request.session['company_info']['company_id'],
            contract=dcontract_no,
            from_km__lte=km,
            to_km__gte=km
        ).first()
        if not rate:
            return JsonResponse({"error": "No rate found for this km"}, status=404)

        # return whichever is > 0
        rate_value = rate.mt if rate.mt > 0 else rate.mt_per_km
        rate_calculation = ""
        if rate.mt > 0 :
            rate_calculation = "MT"
        else:
            rate_calculation = "MT/KM"
        how_calculation = f"From Km: {rate.from_km} | To Km: {rate.to_km} | MT: {rate.mt} | MT/KM: {rate.mt_per_km}"
        data = {
            "rate": float(rate_value),
            "rate_calculation": rate_calculation,   
            "how_calculation": how_calculation
        }
        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    
## INCOME TAX RATE ##

@session_required
def get_incometax_rate_details(request):
    ton = request.GET.get("ton")
    km = request.GET.get("km")
    dcontract_no = request.GET.get("contract_no")

    try:
        km = Decimal(km)
        slabs = Rate_IncomeTax.objects.filter(
            company_id = request.session['company_info']['company_id'],
            contract=dcontract_no,
        ).values("from_km", "to_km", "mt", "mt_per_km").order_by('from_km')

        if not slabs:
            return JsonResponse({"error": "No rate found for this km"}, status=404)
        amount = 0
        for slab in slabs:
            from_km = Decimal(slab["from_km"])
            to_km = Decimal(slab["to_km"])
            if km >= to_km:
                if slab["mt"] > 0:
                    amount += Decimal(slab["mt"])
                else:
                    amount += (to_km  - from_km + 1 ) * Decimal(slab["mt_per_km"])
            elif km >= from_km:
                if slab["mt"] > 0: 
                    amount +=  Decimal(slab["mt"]) 
                else:
                    amount += (km - from_km + 1) *  Decimal(slab["mt_per_km"])
                break

        data = { 
                'amount' : float(amount),
                'slab' : list(slabs)
               }
        
        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    

## CUMULATIVE RATE ##

@session_required
def get_cumrate_details(request):
    km = request.GET.get("km")
    dcontract_no = request.GET.get("contract_no")
    try:
        km = Decimal(km)
        slabs = Rate_Cumulative.objects.filter(
            company_id = request.session['company_info']['company_id'],
            contract=dcontract_no,
        ).values("from_km", "to_km", "mt", "mt_per_km").order_by('from_km')

        amount = 0
        for slab in slabs:
            if slab["mt"] > 0:   
                slab["st_point"] = slab["mt"]
                slab["en_point"] = slab["mt"]
            else:
                slab["st_point"] = round(slab["mt_per_km"] * slab["from_km"],2)
                slab["en_point"] = round(slab["mt_per_km"] * slab["to_km"],2)

        crr_slab_index = 1

        for crr_slab in slabs:
            if crr_slab["from_km"] <= km and crr_slab["to_km"] >= km:
                if crr_slab["mt"] > 0 :
                    crr_rate = round(crr_slab["mt"],2)
                else :
                    crr_rate = round(crr_slab["mt_per_km"] * km ,2)

                for i in range(crr_slab_index , len(slabs)):
                    nex_slab = slabs[i]
                    if crr_rate > nex_slab["st_point"]:
                        crr_rate = round(nex_slab["st_point"],2)
                amount = crr_rate
            crr_slab_index += 1
        
        data = { 
                'amount' : float(amount),
                'slab' : list(slabs)
               }
        
        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

## TALUKA RATE ##

@session_required    
def get_taluka_rate_details(request):
    district = request.GET.get("district")
    dcontract_no = request.GET.get("contract_no")
    taluka = request.GET.get("taluka_name")

    if not taluka or not dcontract_no or not district:
        return JsonResponse({"error": "Contracr id , Taluka and District are required"}, status=400)

    try:
        rate = Rate_taluka.objects.filter(
            company_id = request.session['company_info']['company_id'],
            contract=dcontract_no,
            distric_name=district,
            taluka_name=taluka
        ).first()
        if not rate:
            return JsonResponse({"error": "No rate found for this km"}, status=404)
       
        rate_calculation = "MT"
        how_calculation = f"Taluka: {rate.taluka_name} | District: {rate.distric_name} | MT: {rate.mt}"
        data = {
            "rate": float(rate.mt),
            "rate_calculation": rate_calculation,   
            "how_calculation": how_calculation
        }
        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)



## DISTRICT RATE ##


@session_required   
def get_district_rate_details(request):
    district = request.GET.get("district")
    dcontract_no = request.GET.get("contract_no")

    # if dcontract_no or not district:
    #     return JsonResponse({"error": "Contracr id and District are required"}, status=400)

    try:
        
        rate = Rate_District.objects.filter(
            company_id = request.session['company_info']['company_id'],
            contract=dcontract_no,
            distric_name=district,
        ).first()
        if not rate:
            return JsonResponse({"error": "No rate found for this km"}, status=404)
        rate_value = rate.mt if rate.mt > 0 else rate.mt_per_km
        if rate.mt > 0 :
            rate_calculation = "MT"
        else:
            rate_calculation = "MT/KM"     
        how_calculation = f" District: {rate.distric_name} | MT: {rate.mt} | MT/KM: {rate.mt_per_km}"
        data = {
            "rate": float(rate_value),
            "rate_calculation": rate_calculation,   
            "how_calculation": how_calculation
        }
        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    


## RATE VIEW ##

@session_required
def fetch_rates(request, client_id):
    try:
        company_id = request.session['company_info']['company_id']
        
        # Get the contract to determine rate_type
        try:
            contract = T_Contract.objects.get(id=client_id, company_id=company_id)
            rate_type = contract.rate_type
        except T_Contract.DoesNotExist:
            return JsonResponse({"success": False, "error": "Contract not found"}, status=404)
        
        data = []
        
        # Fetch rates based on contract rate_type
        if rate_type == "Kilometer-Wise" or rate_type == "Slab-Wise":
            queryset = Rate.objects.filter(contract=client_id, company_id=company_id)
            for r in queryset:
                data.append({
                    "rate_type": r.rate_type if r.rate_type else rate_type,
                    "from_km": str(r.from_km),
                    "to_km": str(r.to_km),
                    "mt": str(r.mt),
                    "mt_per_km": str(r.mt_per_km),
                    "display_type": "kilometer_slab"
                })
        
        elif rate_type == "Taluka-Wise":
            queryset = Rate_taluka.objects.filter(contract=client_id, company_id=company_id)
            for r in queryset:
                data.append({
                    "rate_type": r.rate_type if r.rate_type else rate_type,
                    "district_name": r.distric_name,
                    "taluka_name": r.taluka_name,
                    "mt": str(r.mt),
                    "display_type": "taluka"
                })
        
        elif rate_type == "Distric-Wise" or rate_type == "District-Wise":
            queryset = Rate_District.objects.filter(contract=client_id, company_id=company_id)
            for r in queryset:
                data.append({
                    "rate_type": r.rate_type if r.rate_type else rate_type,
                    "district_name": r.distric_name,
                    "mt": str(r.mt),
                    "mt_per_km": str(r.mt_per_km),
                    "display_type": "district"
                })
        
        elif rate_type == "Incometax-Wise":
            queryset = Rate_IncomeTax.objects.filter(contract=client_id, company_id=company_id)
            for r in queryset:
                data.append({
                    "rate_type": rate_type,  # Use contract rate_type for display
                    "from_km": str(r.from_km),
                    "to_km": str(r.to_km),
                    "mt": str(r.mt),
                    "mt_per_km": str(r.mt_per_km),
                    "display_type": "kilometer_slab"
                })
        
        elif rate_type == "Cumulative-Wise":
            queryset = Rate_Cumulative.objects.filter(contract=client_id, company_id=company_id)
            for r in queryset:
                data.append({
                    "rate_type": rate_type,  # Use contract rate_type for display
                    "from_km": str(r.from_km),
                    "to_km": str(r.to_km),
                    "mt": str(r.mt),
                    "mt_per_km": str(r.mt_per_km),
                    "display_type": "kilometer_slab"
                })
        
        if (request.GET.get("format") or "").lower() == "csv":
            # Export the same data as shown in the rate master table
            if rate_type == "Taluka-Wise":
                header = ["Rate Type", "District Name", "Taluka Name", "MT"]
                rows = (
                    (
                        r.get("rate_type", rate_type),
                        r.get("district_name", ""),
                        r.get("taluka_name", ""),
                        r.get("mt", ""),
                    )
                    for r in data
                )
            elif rate_type in ("Distric-Wise", "District-Wise"):
                header = ["Rate Type", "District Name", "MT", "MT/KM"]
                rows = (
                    (
                        r.get("rate_type", rate_type),
                        r.get("district_name", ""),
                        r.get("mt", ""),
                        r.get("mt_per_km", ""),
                    )
                    for r in data
                )
            else:
                header = ["Rate Type", "From Km", "To Km", "MT", "MT/KM"]
                rows = (
                    (
                        r.get("rate_type", rate_type),
                        r.get("from_km", ""),
                        r.get("to_km", ""),
                        r.get("mt", ""),
                        r.get("mt_per_km", ""),
                    )
                    for r in data
                )
            return csv_response(filename="rate_master_backup", header=header, rows=rows)

        return JsonResponse({"success": True, "data": data, "rate_type": rate_type})
    
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)



## DISPATCH FETCHING FOR REPORT ##

@session_required       
def get_dispacth_product(request):
    dcontract_id = request.GET.get('contract-id')
  
    try:
        product = Dispatch.objects.filter(
                    contract_id_id=dcontract_id,
                    company_id_id=request.session['company_info']['company_id']
                ).values_list('product_name', flat=True).distinct()
            
        return JsonResponse({
            "product_list": list(product),
        })
    except Dispatch.DoesNotExist:
        return JsonResponse({
           'error': 'not dispatch found' 
        })


@session_required
def get_report_dispatches(request):
    """
    Return dispatch list for reports (client + internal) so that the
    front-end can display exactly what will be in the downloaded PDF report.
    
    This matches the exact filtering logic from download_report() and download_our_report().

    Query params:
    - contract-id : required
    - type        : "date_wise" | "product_wise" (same as report form)
    - d_from_date / d_to_date : for date_wise (both required)
    - product_name, p_from_date, p_to_date : for product_wise (all required)
    - internal    : optional "true" to indicate internal report
                    (currently only affects which fields frontend adds)
    """
    contract_id = request.GET.get("contract-id")
    report_type = request.GET.get("type")
    company_id = request.session["company_info"]["company_id"]
    # Optional flag: when true, only return dispatches that are NOT billed yet
    # (inv_status = False). Used by the Outstanding Report screen.
    outstanding_only = (request.GET.get("outstanding") or "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not contract_id or not report_type:
        return JsonResponse(
            {"error": "contract-id and type are required"},
            status=400,
        )

    try:
        contract = T_Contract.objects.get(id=contract_id, company_id=company_id)
    except T_Contract.DoesNotExist:
        return JsonResponse({"error": "Contract not found"}, status=404)

    # Apply filters based on report type, EXACTLY matching download_report logic
    if report_type == "product_wise":
        product_name = request.GET.get("product_name")
        p_from_date = request.GET.get("p_from_date")
        p_to_date = request.GET.get("p_to_date")
        
        if not product_name or not p_from_date or not p_to_date:
            return JsonResponse(
                {"error": "product_name, p_from_date, and p_to_date are required for product_wise"},
                status=400,
            )
        
        # Parse dates same way as download_report (line 74-75)
        try:
            f_from_date = datetime.strptime(p_from_date, "%Y-%m-%d").date() if p_from_date else None
            f_to_date = datetime.strptime(p_to_date, "%Y-%m-%d").date() if p_to_date else None
        except ValueError:
            return JsonResponse(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=400,
            )
        
        # Match filter from download_report but allow optional outstanding-only mode
        qs = Dispatch.objects.filter(
            contract_id=contract_id,
            product_name=product_name,
            dep_date__range=(f_from_date, f_to_date),
            company_id=company_id
        )
        if outstanding_only:
            qs = qs.filter(inv_status=False)
        qs = qs.order_by("dep_date")

    elif report_type == "date_wise":
        d_from_date = request.GET.get("d_from_date")
        d_to_date = request.GET.get("d_to_date")
        
        if not d_from_date or not d_to_date:
            return JsonResponse(
                {"error": "d_from_date and d_to_date are required for date_wise"},
                status=400,
            )
        
        # Parse dates same way as download_report (line 84-85)
        try:
            f_from_date = datetime.strptime(d_from_date, "%Y-%m-%d").date() if d_from_date else None
            f_to_date = datetime.strptime(d_to_date, "%Y-%m-%d").date() if d_to_date else None
        except ValueError:
            return JsonResponse(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=400,
            )
        
        # Match filter from download_report but allow optional outstanding-only mode
        qs = Dispatch.objects.filter(
            contract_id=contract_id,
            dep_date__range=(f_from_date, f_to_date),
            company_id=company_id
        )
        if outstanding_only:
            qs = qs.filter(inv_status=False)
        qs = qs.order_by("dep_date")
    else:
        return JsonResponse({"error": "Invalid report type"}, status=400)

    # Get all dispatch fields needed for the report (matching what download_report uses)
    dispatches_list = []
    for d in qs:
        # Calculate amount same way as download_report (line 198-201)
        total_amount = (float(d.totalfreight or 0) +
                       float(d.unloading_charge_1 or 0) +
                       float(d.unloading_charge_2 or 0) +
                       float(d.loading_charge or 0))
        
        dispatch_data = {
            "id": d.id,
            "challan_no": d.challan_no,
            "dep_date": d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "",
            "truck_no": d.truck_no,
            "product_name": d.product_name,
            "party_name": d.party_name,
            "from_center": d.from_center,
            "destination": d.destination,
            "taluka": d.taluka,
            "district": d.district,
            "km": float(d.km) if d.km else 0,
            "weight": float(d.weight) if d.weight else 0,
            "rate": float(d.rate) if d.rate else 0,
            "totalfreight": float(d.totalfreight) if d.totalfreight else 0,
            "unloading_charge_1": float(d.unloading_charge_1) if d.unloading_charge_1 else 0,
            "unloading_charge_2": float(d.unloading_charge_2) if d.unloading_charge_2 else 0,
            "loading_charge": float(d.loading_charge) if d.loading_charge else 0,
            "grand_total": total_amount,  # Use calculated amount
            "gc_note_no": d.gc_note_no,
            # Internal report fields
            "truck_booking_rate": float(d.truck_booking_rate) if d.truck_booking_rate else 0,
            "total_paid_truck_onwer": float(d.total_paid_truck_onwer) if d.total_paid_truck_onwer else 0,
            "advance_paid": float(d.advance_paid) if d.advance_paid else 0,
            "panding_amount": float(d.panding_amount) if d.panding_amount else 0,
            "net_profit": float(d.net_profit) if d.net_profit else 0,
        }
        dispatches_list.append(dispatch_data)

    # Base fields are invoice_fields; internal report will append more on frontend
    base_fields = contract.invoice_fields or []

    return JsonResponse(
        {
            "fields": base_fields,
            "destinations": dispatches_list,
        }
    )

    
@session_required
def get_last_dispatch_details(request):
    """
    Return the last dispatch entered for a given contract (optionally filtered by product_name)
    so the dispatch form can be auto-filled.
    """
    contract_id = request.GET.get("contract-id")
    product_name = request.GET.get("product_name")

    if not contract_id:
        return JsonResponse({"error": "contract-id is required"}, status=400)

    qs = Dispatch.objects.filter(
        contract_id_id=contract_id,
        company_id_id=request.session["company_info"]["company_id"],
    )

    if product_name:
        qs = qs.filter(product_name=product_name)

    last_dispatch = qs.order_by("-dep_date", "-id").first()

    if not last_dispatch:
        return JsonResponse({"found": False})

    data = _serialize_dispatch_details(
        last_dispatch,
        request.session["company_info"]["company_id"],
    )

    return JsonResponse(data)


def _serialize_dispatch_details(dispatch_obj, company_id):
    """
    Helper to serialize a Dispatch instance into the structure expected by
    the frontend (used for both last-dispatch and specific-dispatch fetch).
    """
    # Try to resolve a matching Destination record so the frontend can select it in the dropdown
    destination_obj = (
        Destination.objects.filter(
            contract_id_id=dispatch_obj.contract_id_id,
            company_id_id=company_id,
            destination=dispatch_obj.destination,
        ).first()
        if dispatch_obj.destination
        else None
    )

    return {
        "found": True,
        "id": dispatch_obj.id,
        # Dispatch date (HTML <input type="date"> expects YYYY-MM-DD)
        "dep_date": dispatch_obj.dep_date.strftime("%Y-%m-%d") if dispatch_obj.dep_date else "",
        "challan_no": dispatch_obj.challan_no,
        "product_name": dispatch_obj.product_name,
        "party_name": dispatch_obj.party_name,
        "from_center": dispatch_obj.from_center,
        "destination": dispatch_obj.destination,
        "destination_id": destination_obj.id if destination_obj else None,
        "taluka": dispatch_obj.taluka,
        "district": dispatch_obj.district,
        "km": dispatch_obj.km,
        "truck_no": dispatch_obj.truck_no,
        "weight": str(dispatch_obj.weight),
        "rate": str(dispatch_obj.rate),
        "totalfreight": str(dispatch_obj.totalfreight),
        "unloading_charge_1": str(dispatch_obj.unloading_charge_1 or 0),
        "unloading_charge_2": str(dispatch_obj.unloading_charge_2 or 0),
        "loading_charge": str(dispatch_obj.loading_charge or 0),
        "grand_total": str(dispatch_obj.grand_total),
        "truck_booking_rate": str(dispatch_obj.truck_booking_rate),
        "total_paid_truck_onwer": str(dispatch_obj.total_paid_truck_onwer),
        "advance_paid": str(dispatch_obj.advance_paid),
        "panding_amount": str(dispatch_obj.panding_amount),
        "net_profit": str(dispatch_obj.net_profit),
        "main_party": dispatch_obj.main_party or "",
        "sub_party": dispatch_obj.sub_party or "",
    }


@session_required
def get_dispatch_list_for_contract(request):
    """
    Return a list of previous dispatches for a contract so user can select
    one challan and auto-fill the add-dispatch form.
    """
    contract_id = request.GET.get("contract-id")
    if not contract_id:
        return JsonResponse({"error": "contract-id is required"}, status=400)

    company_id = request.session["company_info"]["company_id"]

    qs = (
        Dispatch.objects.filter(
            contract_id_id=contract_id,
            company_id_id=company_id,
        )
        .order_by("-dep_date", "-id")
    )

    dispatches = []
    for d in qs:
        dispatches.append(
            {
                "id": d.id,
                "challan_no": d.challan_no,
                "product_name": d.product_name,
                "dep_date": d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "",
                "destination": d.destination,
            }
        )

    return JsonResponse({"dispatches": dispatches})


@session_required
def get_dispatch_details(request):
    """
    Return full details for a specific dispatch (by dispatch_id) so the add
    dispatch form can be auto-filled from a selected previous challan.
    """
    dispatch_id = request.GET.get("dispatch_id")
    if not dispatch_id:
        return JsonResponse({"error": "dispatch_id is required"}, status=400)

    company_id = request.session["company_info"]["company_id"]

    try:
        dispatch_obj = Dispatch.objects.get(
            id=dispatch_id,
            company_id_id=company_id,
        )
    except Dispatch.DoesNotExist:
        return JsonResponse({"error": "dispatch not found"}, status=404)

    data = _serialize_dispatch_details(dispatch_obj, company_id)
    return JsonResponse(data)

@session_required
def get_truck_numbers(request):
    """
    Fetch unique truck numbers from Dispatch records for the current company,
    sorted in ascending order. Used for autocomplete in dispatch form.
    Results are cached for 1 hour to improve performance.
    """
    company_id = request.session['company_info']['company_id']
    search_query = request.GET.get('q', '').strip()
    
    # Create cache key based on company_id
    cache_key = f'truck_numbers_{company_id}'
    
    # Try to get from cache first
    cached_truck_numbers = cache.get(cache_key)
    
    if cached_truck_numbers is None:
        # Cache miss - fetch from database
        truck_numbers = Dispatch.objects.filter(
            company_id=company_id
        ).exclude(
            truck_no__isnull=True
        ).exclude(
            truck_no__exact=''
        ).values_list('truck_no', flat=True).distinct()
        
        # Sort in ascending order and convert to list
        truck_numbers = sorted(set(truck_numbers), key=str.lower)
        truck_numbers = list(truck_numbers)
        
        # Cache for 1 hour (3600 seconds)
        cache.set(cache_key, truck_numbers, 3600)
        cached_truck_numbers = truck_numbers
    
    # Filter by search query if provided (filter cached results)
    if search_query:
        search_lower = search_query.lower()
        filtered_truck_numbers = [
            truck_no for truck_no in cached_truck_numbers
            if search_lower in truck_no.lower()
        ]
        truck_numbers = filtered_truck_numbers
    else:
        truck_numbers = cached_truck_numbers
    
    return JsonResponse({
        'truck_numbers': truck_numbers,
    })


@session_required
def get_contract_bills(request):
    contract_id = request.GET.get('contract-id')
    company_id = request.session['company_info']['company_id']
    
    try:
        contract = T_Contract.objects.get(id=contract_id, company_id=company_id)
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'Contract not found'}, status=404)
    
    # Get all invoices for this contract
    invoices = Invoice.objects.filter(
        contract_id=contract_id,
        company_id=company_id
    ).order_by('Bill_no')
    
    bills_data = []
    for invoice in invoices:
        # Get all dispatches for this invoice
        dispatches = invoice.dispatch_list.all()
        
        if dispatches.exists():
            # Calculate totals
            total_weight = sum(d.weight for d in dispatches if d.weight)
            total_freight = sum(d.totalfreight for d in dispatches if d.totalfreight)
            total_loading = sum(d.loading_charge for d in dispatches if d.loading_charge)
            total_unloading1 = sum(d.unloading_charge_1 for d in dispatches if d.unloading_charge_1)
            total_unloading2 = sum(d.unloading_charge_2 for d in dispatches if d.unloading_charge_2)
            
            # Get product name from first dispatch (assuming all have same product)
            product_name = dispatches.first().product_name if dispatches.first() else ""
            
            bills_data.append({
                'id': invoice.id,
                'bill_no': invoice.Bill_no,
                'bill_date': invoice.Bill_date.strftime('%d-%m-%Y') if invoice.Bill_date else '',
                'total_weight': float(total_weight),
                'total_freight': float(total_freight),
                'total_loading': float(total_loading),
                'total_unloading1': float(total_unloading1),
                'total_unloading2': float(total_unloading2),
            })
    
    # Get product name from bills' dispatches (use first available)
    product_name = ""
    for invoice in invoices:
        dispatches = invoice.dispatch_list.all()
        if dispatches.exists():
            product_name = dispatches.first().product_name
            break
    
    if (request.GET.get("format") or "").lower() == "csv":
        header = [
            "Bill No",
            "Bill Date",
            "M.T",
            "Bill Amount",
            "Loading Charge",
            "Unloading 1",
            "Unloading 2",
            "Grand Total",
        ]
        rows = (
            (
                b.get("bill_no", ""),
                b.get("bill_date", ""),
                b.get("total_weight", 0),
                b.get("total_freight", 0),
                b.get("total_loading", 0),
                b.get("total_unloading1", 0),
                b.get("total_unloading2", 0),
                float(b.get("total_freight", 0) or 0)
                + float(b.get("total_loading", 0) or 0)
                + float(b.get("total_unloading1", 0) or 0)
                + float(b.get("total_unloading2", 0) or 0),
            )
            for b in bills_data
        )
        safe_contract = str(contract.contract_no or "contract").replace("/", "-")
        return csv_response(filename=f"summary_{safe_contract}_bills_backup", header=header, rows=rows)

    return JsonResponse({
        'contract': {
            'id': contract.id,
            'contract_no': contract.contract_no,
            'company_name': contract.company_name,
            'from_center': contract.from_center or "",
            'product_name': product_name,
            'billing_address': contract.billing_address or "",
            'billing_state': contract.billing_state or "",
            'billing_city': contract.billing_city or "",
            'billing_pin': contract.billing_pin or "",
            'gst_number': contract.gst_number or "",
            'pan_number': contract.pan_number or "",
            'loading_charge': float(contract.loading_charge) if contract.loading_charge else 0,
            'unloading_charge_1': float(contract.unloading_charge_1) if contract.unloading_charge_1 else 0,
            'unloading_charge_2': float(contract.unloading_charge_2) if contract.unloading_charge_2 else 0,
        },
        'bills': bills_data
    })

