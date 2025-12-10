from django.shortcuts import render ,redirect ,get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.urls import reverse, resolve
from erp.utils.decorators import session_required
from transport.models import Rate , T_Contract ,Dispatch ,Destination ,Rate_taluka , Rate_District ,Rate_IncomeTax , Rate_Cumulative , Invoice , GC_Note
  
@session_required
def dashboard(request):
    alldata = {}

    total_contracts = T_Contract.objects.filter(company_id_id=request.session['company_info']['company_id']).count()
    total_dispatches = Dispatch.objects.filter(company_id_id=request.session['company_info']['company_id']).count()
    total_invoices = Invoice.objects.filter(company_id_id=request.session['company_info']['company_id']).count()
    total_gc_notes = GC_Note.objects.filter(company_id_id=request.session['company_info']['company_id']).count()

    totals  = Dispatch.objects.filter(company_id_id=request.session['company_info']['company_id']).aggregate(
                    total_amount=Sum('grand_total'),
                    total_pending_amount=Sum('panding_amount'),
                    total_paid_truck=Sum('advance_paid'),
                    total_profit=Sum('net_profit'),
            )
    
    total_charges = Dispatch.objects.filter(company_id_id=request.session['company_info']['company_id']).aggregate(
                    total_loading_charges=Sum('loading_charge') ,
                    total_unloading_charges_1=Sum('unloading_charge_1') ,
                    total_unloading_charges_2=Sum('unloading_charge_2') ,
    )

    if total_charges['total_loading_charges'] != None and total_charges['total_unloading_charges_1'] != None and total_charges['total_unloading_charges_2'] != None:
        sum_charges = (total_charges['total_loading_charges']) + (total_charges['total_unloading_charges_1']) + (total_charges['total_unloading_charges_2'])
    else: 
        total_charges['total_loading_charges'] = 0
        total_charges['total_unloading_charges_1'] = 0
        total_charges['total_unloading_charges_2'] = 0
        sum_charges = 0

    alldata = {
        'total_contracts': total_contracts,
        'total_dispatches': total_dispatches,
        'total_invoices': total_invoices,
        'total_gc_notes': total_gc_notes,
        'totals': totals,
        'sum_charges': sum_charges or 0,
        'total_charges': total_charges,
    }

    return render(request , 'index.html' , alldata)