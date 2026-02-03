from django.shortcuts import render ,redirect ,get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.urls import reverse, resolve
from erp.utils.decorators import session_required
from erp.utils.financial_year import filter_by_financial_year, get_current_financial_year, get_financial_year_start_end
from transport.models import Rate , T_Contract ,Dispatch ,Destination ,Rate_taluka , Rate_District ,Rate_IncomeTax , Rate_Cumulative , Invoice , GC_Note
  
@session_required
def dashboard(request):
    alldata = {}
    company_id = request.session['company_info']['company_id']
    
    # Get financial year from session, default to current if not set
    financial_year = request.session.get('financial_year', get_current_financial_year())
    
    # Base querysets filtered by company
    dispatch_base = Dispatch.objects.filter(company_id_id=company_id)
    invoice_base = Invoice.objects.filter(company_id_id=company_id)
    gc_note_base = GC_Note.objects.filter(company_id_id=company_id)
    contract_base = T_Contract.objects.filter(company_id_id=company_id)
    
    # Filter by financial year
    # For contracts, use created_at; for dispatch use dep_date; for invoice use Bill_date; for GC use gc_date
    dispatch_filtered = filter_by_financial_year(dispatch_base, financial_year, 'dep_date')
    
    # For invoices, filter by Bill_date
    start_date, end_date = get_financial_year_start_end(financial_year)
    invoice_filtered = invoice_base.filter(Bill_date__gte=start_date, Bill_date__lte=end_date)
    
    # For GC notes, filter by gc_date
    gc_filtered = gc_note_base.filter(gc_date__gte=start_date, gc_date__lte=end_date)
    
    # For contracts, show contracts that are active during the financial year
    # A contract is active if it overlaps with the financial year period
    # Contract overlaps if: (c_start_date <= end_date) AND (c_end_date >= start_date OR c_end_date is NULL)
    from django.db.models import Q
    contract_filtered = contract_base.filter(
        # Contracts with start/end dates that overlap financial year
        Q(c_start_date__lte=end_date) & (
            Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True)
        )
    )

    total_contracts = contract_filtered.count()
    total_dispatches = dispatch_filtered.count()
    total_invoices = invoice_filtered.count()
    total_gc_notes = gc_filtered.count()

    totals  = dispatch_filtered.aggregate(
                    total_amount=Sum('grand_total'),
                    total_pending_amount=Sum('panding_amount'),
                    total_paid_truck=Sum('advance_paid'),
                    total_profit=Sum('net_profit'),
            )
    
    total_charges = dispatch_filtered.aggregate(
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
        'financial_year': financial_year,
    }

    return render(request , 'index.html' , alldata)