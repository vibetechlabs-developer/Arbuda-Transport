from django.http import JsonResponse
from erp.utils.decorators import session_required
from transport.models import T_Contract, Destination , Dispatch, Invoice, GC_Note
import re
from transport.models import Rate, Rate_IncomeTax, Rate_Cumulative, Rate_taluka, Rate_District
from decimal import Decimal

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
            })
        except Destination.DoesNotExist:
            return JsonResponse({
                'from' : contract.from_center,
                'from' : contract.from_center,
                'unloading_charge_1' : contract.unloading_charge_1 if contract.unloading_charge_1 else 0,
                'unloading_charge_2' : contract.unloading_charge_2 if contract.unloading_charge_2 else 0,
                'loading_charge' : contract.loading_charge if contract.loading_charge else 0,
                "rate_type" : contract.rate_type,
            })
        
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    


@session_required
def get_destination_details(request):
    did = request.GET.get('did')
    try:
        destination = Destination.objects.get(id=did)
        return JsonResponse({
            'district' : destination.district,
            'taluka' : destination.taluka,
            'km' : destination.km,
            'rate_type' : destination.contract_id.rate_type,
        })
    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    


@session_required
def get_dispacth(request):
    dcontract_id = request.GET.get('contract-id')
    try:
        contract = T_Contract.objects.get(id=dcontract_id)
        try:
            dispatch = Dispatch.objects.filter(contract_id=dcontract_id , company_id = request.session['company_info']['company_id'], inv_status = False).values().order_by('dep_date')

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
    try:
        invoice = Invoice.objects.get(id=dbill_id , company_id = request.session['company_info']['company_id'])
        contract = T_Contract.objects.get(id=invoice.contract_id.id)
        try:
            dispatch = Dispatch.objects.filter(contract_id=invoice.contract_id.id , company_id = request.session['company_info']['company_id'], inv_status = False).values().order_by('dep_date')

            return JsonResponse({
                'fields' : contract.invoice_fields,
                'destinations': list(dispatch),
            })
        except Dispatch.DoesNotExist:
            return JsonResponse({
               'error': 'not dispatch found' 
            })

    except T_Contract.DoesNotExist:
        return JsonResponse({'error': 'not con found'}, status=404)



@session_required
def get_gc(request):  
    bill_id = request.GET.get('bill-id')
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
            dispatch = invoice.dispatch_list.values().order_by('dep_date')
            return JsonResponse({
           'bill_date': invoice.Bill_date,  
            'contract_no' : contract.contract_no, 
            'contract_id' : contract.id,     
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
    queryset = Rate.objects.filter(contract = client_id , company_id=request.session['company_info']['company_id'])
    data = []
    for r in queryset:
        data.append({
            "from_km": r.from_km,
            "to_km": r.to_km,
            "mt": r.mt,
            "mt_per_km": r.mt_per_km,
        })
    return JsonResponse({"success": True, "data": data})



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

    

