from erp.utils.decorators import session_required
from transport.models import T_Contract, Company_user, Dispatch, Invoice, GC_Note
from company.models import Company_user , Company_profile
from django.shortcuts import render ,redirect ,get_object_or_404
from django.http import HttpResponse, FileResponse
from django.contrib import messages
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from datetime import datetime
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle ,PageBreak , HRFlowable
from reportlab.lib.units import mm
from operator import attrgetter
import math
import re
from itertools import groupby
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from erp.utils.financial_year import get_current_financial_year, get_financial_year_start_end
from django.db.models import Q


def sort_dispatches_by_challan_asc(dispatches):
    """
    Sort dispatches by challan_no in ascending order (numeric sorting).
    Handles challan numbers like "0005", "0009", etc.
    """
    def get_numeric_value(challan_no):
        """Extract numeric value from challan_no for sorting."""
        if not challan_no:
            return 0
        # Try to extract numeric part from the string
        num_match = re.search(r'\d+', str(challan_no))
        return int(num_match.group(0)) if num_match else 0
    
    # Convert queryset to list if needed
    dispatch_list = list(dispatches) if hasattr(dispatches, '__iter__') and not isinstance(dispatches, list) else dispatches
    # Sort in ascending order by challan_no numeric value
    return sorted(dispatch_list, key=lambda d: get_numeric_value(d.challan_no))



@session_required
def generate_invoice_pdf(request):
    if request.method != "POST":
        return redirect("create-dispatch-invoice")

    # Prepare context for error rendering
    alldata = {}
    try:
        company_id = request.session['company_info']['company_id']
        financial_year = request.session.get('financial_year', get_current_financial_year())
        start_date, end_date = get_financial_year_start_end(financial_year)
        
        # Filter contracts that are active during the financial year
        allcontract = T_Contract.objects.filter(
            company_id=company_id
        ).filter(
            Q(
                Q(c_start_date__lte=end_date) & (
                    Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True)
                )
            ) |
            Q(c_start_date__isnull=True)
        ).order_by('-id')
        alldata['allcontract'] = allcontract
    except Exception as e:
        messages.error(request, f'Error loading contracts: {str(e)}')
        return redirect("create-dispatch-invoice")

    # --- Fetch POST data ---
    contract_id = request.POST.get("contract_no")
    dispatch_ids_raw = request.POST.getlist("dispatch_ids")
    i_bill_no = request.POST.get("bill_no", "").strip()
    bill_date_str = request.POST.get("bill_date")
    
    # Store form data for repopulation
    alldata['form_data'] = request.POST

    # Validation: Check if dispatch_ids are selected
    if not dispatch_ids_raw:
        alldata['dispatch_error'] = "Please select at least one dispatch to generate invoice."
        return render(request, 'dispatch-invoice.html', alldata)

    # Convert dispatch_ids to integers
    try:
        dispatch_ids = [int(i) for i in dispatch_ids_raw]
    except (ValueError, TypeError):
        alldata['dispatch_error'] = "Invalid dispatch selection."
        return render(request, 'dispatch-invoice.html', alldata)

    # Validation: Check if contract is selected
    if not contract_id:
        alldata['contract_error'] = "Please select a contract."
        return render(request, 'dispatch-invoice.html', alldata)

    # Validation: Check if bill_no is provided
    if not i_bill_no:
        alldata['bill_no_error'] = "Bill No. is required."
        return render(request, 'dispatch-invoice.html', alldata)

    # Validation: Check if bill_date is provided
    if not bill_date_str:
        alldata['bill_date_error'] = "Bill Date is required."
        return render(request, 'dispatch-invoice.html', alldata)

    # Parse bill_date
    try:
        bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date()
    except ValueError:
        alldata['bill_date_error'] = "Invalid bill date format."
        return render(request, 'dispatch-invoice.html', alldata)

    # --- Fetch contract and company ---
    try:
        contract = T_Contract.objects.get(id=contract_id)
        i_company_id = Company_user.objects.get(id=request.session['company_info']['company_id'])
        company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
        company = Company_user.objects.get(id=request.session['company_info']['company_id'])
    except T_Contract.DoesNotExist:
        alldata['contract_error'] = "Contract not found."
        return render(request, 'dispatch-invoice.html', alldata)
    except Company_user.DoesNotExist:
        alldata['general_error'] = "User's company not found."
        return render(request, 'dispatch-invoice.html', alldata)
    except Company_profile.DoesNotExist:
        alldata['general_error'] = "Company profile not found."
        return render(request, 'dispatch-invoice.html', alldata)

    # --- Validate bill no range ---
    # Note: contract.bill_series_from / bill_series_to are CharFields in the DB.
    # Only perform numeric range validation when all values are numeric to avoid int<->str TypeErrors.
    series_from_raw = contract.bill_series_from
    series_to_raw = contract.bill_series_to
    if series_from_raw not in [None, ""] and series_to_raw not in [None, ""]:
        bill_no_s = str(i_bill_no).strip()
        series_from_s = str(series_from_raw).strip()
        series_to_s = str(series_to_raw).strip()

        if bill_no_s.isdigit() and series_from_s.isdigit() and series_to_s.isdigit():
            bill_no_int = int(bill_no_s)
            series_from_int = int(series_from_s)
            series_to_int = int(series_to_s)
            if bill_no_int < series_from_int or bill_no_int > series_to_int:
                alldata['bill_no_error'] = (
                    f"Please enter valid bill no. {contract.bill_series_from} to {contract.bill_series_to}"
                )
                return render(request, "dispatch-invoice.html", alldata)

    # --- Validate duplicate bill no ---
    if Invoice.objects.filter(Bill_no=i_bill_no, company_id=i_company_id, contract_id=contract.id).exists():
        alldata['bill_no_error'] = f"Invoice with bill number '{i_bill_no}' already exists!"
        return render(request, 'dispatch-invoice.html', alldata)

    # --- Create Invoice ---
    invoice = Invoice.objects.create(
        Bill_no=i_bill_no,
        Bill_date=bill_date,
        company_id=i_company_id,
        contract_id=contract,
    )

    dispatches = Dispatch.objects.filter(id__in=dispatch_ids).order_by('dep_date')
    # Sort by challan_no in ascending order (will be re-sorted for district-wise contracts)
    dispatches = sort_dispatches_by_challan_asc(dispatches)
    invoice.dispatch_list.add(*dispatches)

    # --- Create GC Notes ---

    for d in dispatches:
        d.inv_status = True
        d.save()

    if contract.gc_note_required:

        for d in dispatches:
            if GC_Note.objects.filter(contract_id=contract.id).exists():
                last_gc = GC_Note.objects.filter(contract_id=contract.id).latest('id')
                gc_no = last_gc.gc_no + 1
            else:
                gc_no = contract.gc_series_from
            gc_note = GC_Note.objects.create(
                gc_no=gc_no,
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
                bill_no=i_bill_no,
                dispatch_id=d,
                bill_id=invoice,
                contract_id=contract,
                company_id=i_company_id
            )
            d.gc_note_no = gc_note.gc_no
            d.save()

    # --- PDF Generation ---
    buffer = BytesIO()
    # Use reasonable margins for better readability
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=8 * mm,
        leftMargin=8 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # --- Styles ---
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=10, alignment=1, leading=14)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=8, alignment=1, leading=11)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=16, alignment=1, leading=20)
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=10, alignment=0, leading=14)
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=10, alignment=2, leading=14)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=8, alignment=2, leading=11)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=7, alignment=0, leading=10)
    # Uniform header style for all column names - same size for consistency
    to_right_style_desc_heading = ParagraphStyle(name="ToRightDesc", fontName="Helvetica-Bold", fontSize=7.5, alignment=1, leading=10)
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=7, alignment=2, leading=10)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='15'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[272*mm])
    header_table.setStyle(TableStyle([
        ('LINEBELOW', (0,2), (-1,2), 0.8, colors.black), 
        ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    fields = contract.invoice_fields
    chunk_size = int(request.POST.get('chunk', 10))  # dispatch per page

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None):
   
        # Header row
        label_map = {
            "sr_no": "Sr No",
            "depature_date": "Dep Date",
            "dep_date": "Dep Date",
            "dc_field": ("Challan No" if getattr(contract, "dc_field", None) in [None, "None", "null", ""] else str(getattr(contract, "dc_field"))),
            "truck_no": "Truck No",
            "party_name": "Party Name",
            "product_name": "Product",
            "district": "District",
            "taluka": "Taluka",
            "unloading_charge_1": "Unloading 1",
            "unloading_charge_2": "Unloading 2",
            "loading_charge": "Loading",
            "totalfreight": "Freight",
            "gc_note": "GC Note",
        }
        data = [[label_map.get(f, f.replace("_", " ").title()) for f in fields]]

        numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                        "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
        center_fields = ["sr_no", "gc_note"]

        compact = len(dispatch_subset) >= 18
        compact_fs = 6.5 if compact else None
        
        compact_leading = 9 if compact else None

        center_style_desc_local = ParagraphStyle(
            name="CenterDescLocal",
            parent=center_style_desc,
            fontSize=compact_fs or center_style_desc.fontSize,
            leading=compact_leading or center_style_desc.leading,
        )
        to_style_desc_local = ParagraphStyle(
            name="ToDescLocal",
            parent=to_style_desc,
            fontSize=compact_fs or to_style_desc.fontSize,
            leading=compact_leading or to_style_desc.leading,
        )
        # Uniform header style for all column names
        header_style_uniform = ParagraphStyle(
            name="HeaderUniform",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize,
            leading=to_right_style_desc_heading.leading,
            alignment=1,  # Center all headers
        )
        to_right_style_desc_local = ParagraphStyle(
            name="ToRightDescLocal",
            parent=to_right_style_desc,
            fontSize=compact_fs or to_right_style_desc.fontSize,
            leading=compact_leading or to_right_style_desc.leading,
        )
        # Uniform header style - same size for all column names
        to_right_style_desc_heading_local = ParagraphStyle(
            name="ToRightDescHeadingLocal",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize,  # Always use same size
            leading=to_right_style_desc_heading.leading,  # Always use same leading
            alignment=1,  # Center align all headers
        )
        total_style_local = ParagraphStyle(
            name="TotalStyleLocal",
            parent=total_style,
            fontSize=compact_fs or total_style.fontSize,
            leading=compact_leading or total_style.leading,
        )

        # Initialize page totals
        total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = 0

        # Build rows
        for idx, d in enumerate(dispatch_subset, start=1):
            total_amount = (float(d.totalfreight or 0) +
                            float(d.unloading_charge_1 or 0) +
                            float(d.unloading_charge_2 or 0) +
                            float(d.loading_charge or 0))

            total_freight_sum += float(d.totalfreight or 0)
            total_unloading_sum_1 += float(d.unloading_charge_1 or 0)
            total_unloading_sum_2 += float(d.unloading_charge_2 or 0)
            total_loading_sum += float(d.loading_charge or 0)
            total_amount_sum += total_amount
            total_weight += float(d.weight or 0)

            row = []
            for field in fields:
                if field == "sr_no":
                    row.append(idx)
                elif field in ("depature_date", "dep_date"):
                    row.append(d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "")
                elif field == "dc_field" or field == "None":
                    row.append(d.challan_no)
                elif field in ("luggage", "totalfreight"):
                    row.append(d.totalfreight)
                elif field in ("product_name", "product"):
                    row.append(d.product_name)
                elif field == "amount":
                    row.append(f"{total_amount:.2f}")
                elif field == "gc_note":
                    row.append(d.gc_note_no)
                elif field == "main_party":
                    row.append(d.main_party or "")
                elif field == "sub_party":
                    row.append(d.sub_party or "")
                else:
                    row.append(getattr(d, field, ""))
            data.append(row)                

        # Determine total row logic
        add_total = False
        total_row = []

        if contract.rate_type == "Distric-Wise" and add_total_row:
            # District-wise: page total only
            add_total = True
            dispatches_to_sum = dispatch_subset
        elif contract.rate_type != "Distric-Wise" and is_last_page:
            # Non District-wise: grand total on last page
            add_total = True
            dispatches_to_sum = all_dispatches

        if add_total:
            # Calculate totals
            total_weight = total_freight_sum = total_unloading_sum_1 = total_unloading_sum_2 = total_loading_sum = total_amount_sum = 0
            for d in dispatches_to_sum:
                total_amount = (float(d.totalfreight or 0) +
                                float(d.unloading_charge_1 or 0) +
                                float(d.unloading_charge_2 or 0) +
                                float(d.loading_charge or 0))
                total_freight_sum += float(d.totalfreight or 0)
                total_unloading_sum_1 += float(d.unloading_charge_1 or 0)
                total_unloading_sum_2 += float(d.unloading_charge_2 or 0)
                total_loading_sum += float(d.loading_charge or 0)
                total_amount_sum += total_amount
                total_weight += float(d.weight or 0)

            for i, field in enumerate(fields):
                if field == "weight":
                    total_row.append(f"{total_weight:.3f}")
                elif field in ("luggage", "totalfreight"):
                    total_row.append(f"{total_freight_sum:.2f}")
                elif field == "unloading_charge_1":
                    total_row.append(f"{total_unloading_sum_1:.3f}")
                elif field == "unloading_charge_2":
                    total_row.append(f"{total_unloading_sum_2:.3f}")
                elif field == "loading_charge":
                    total_row.append(f"{total_loading_sum:.3f}")
                elif field == "amount":
                    total_row.append(f"{total_amount_sum:.2f}")
                else:
                    total_row.append("")
            total_row[0] = "TOTAL"
            data.append(total_row)

        # Special column widths - optimized to prevent wrapping, all headers same size
        # NOTE: header keys must match `data[0]` exactly.
        special_widths = {
            "Sr No": 10 * mm,
            ("Challan No" if getattr(contract, "dc_field", None) in [None, "None", "null", ""] else str(getattr(contract, "dc_field"))): 18 * mm,
            "Truck No": 28 * mm,
            "Party Name": 22 * mm,
            "Product": 20 * mm,
            "Gc Note": 12 * mm,
            "Weight": 14 * mm,
            "Km": 10 * mm,
            "Rate": 14 * mm,
            "Luggage": 16 * mm,
            "Unloading 1": 18 * mm,
            "Unloading 2": 18 * mm,
            "Loading": 16 * mm,
            "Freight": 14 * mm,
            "Dep Date": 18 * mm,
            "Destination": 22 * mm,
            "District": 16 * mm,
            "Taluka": 16 * mm,
        }

        table_width = 272 * mm
        headers = data[0]

        # Calculate column widths
        col_widths = []
        for col_name in headers:
            col_widths.append(special_widths.get(col_name, None))

        # Adjust remaining width - ensure valid values
        fixed_total = sum(w for w in col_widths if w is not None)
        remaining = max(0, table_width - fixed_total)  # Ensure non-negative
        num_other_cols = sum(1 for w in col_widths if w is None)
        if num_other_cols > 0 and remaining > 0:
            other_width = max(10 * mm, remaining / num_other_cols)  # Minimum 10mm
            col_widths = [w if w is not None else other_width for w in col_widths]
        else:
            # If no remaining width, set default for None values
            default_width = 15 * mm
            col_widths = [w if w is not None else default_width for w in col_widths]
        
        # Ensure all widths are valid and positive (minimum 5mm)
        col_widths = [max(5 * mm, float(w)) if w is not None else 15 * mm for w in col_widths]
        
        # Recalculate total and scale if needed to fit table width
        total_width = sum(col_widths)
        if total_width > table_width and total_width > 0:
            scale_factor = table_width / total_width
            col_widths = [w * scale_factor for w in col_widths]

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = fields[j]
                if i == 0:  # header - use uniform style for all column names
                    row[j] = Paragraph(f"<b>{cell}</b>", header_style_uniform)
                elif add_total and i == len(data) - 1:  # total/grand total row
                    row[j] = Paragraph(str(cell), total_style_local)
                else:
                    style = to_right_style_desc_local if field_name in numeric_fields else center_style_desc_local if field_name in center_fields else to_style_desc_local
                    row[j] = Paragraph(str(cell), style)

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles
        styles = [
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("LEFTPADDING", (0,0), (-1,-1), 2 if compact else 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 2 if compact else 4),
            # Header row height
            ("TOPPADDING", (0,0), (-1,0), 5 if compact else 7),
            ("BOTTOMPADDING", (0,0), (-1,0), 5 if compact else 7),
            # Body row height
            ("TOPPADDING", (0,1), (-1,-2), 3 if compact else 5),
            ("BOTTOMPADDING", (0,1), (-1,-2), 3 if compact else 5),
            ("LINEABOVE", (0,0), (-1,0), 0.5, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 0.5, colors.black),
            # Make it readable: light grid + zebra rows
            ("GRID", (0,0), (-1,-1), 0.2, colors.lightgrey),
            # Prevent text wrapping in cells
            ("WORDWRAP", (0,0), (-1,-1), "NORMAL"),
        ]
        # zebra rows for body (exclude header)
        for r in range(1, len(data) - (1 if add_total else 0)):
            if (r % 2) == 0:
                styles.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#FAFAFA")))
        if add_total:
            styles += [
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                ("SPAN", (0,-1), (2,-1)),
                ("TOPPADDING", (0,-1), (-1,-1), 6),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 6),
                ("LINEABOVE", (0,-1), (-1,-1), 0.5, colors.black),
                ("LINEBELOW", (0,-1), (-1,-1), 0.5, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table

    # --- Split dispatches per page ---

    if contract.rate_type == "Distric-Wise":
        # Sort dispatches by district, then by challan_no (ascending) within each district
        page_no=1
        def sort_key(d):
            def get_numeric_value(challan_no):
                if not challan_no:
                    return 0
                num_match = re.search(r'\d+', str(challan_no))
                return int(num_match.group(0)) if num_match else 0
            # Positive for ascending challan order within each district
            return (d.district or '', get_numeric_value(d.challan_no))
        
        dispatches_sorted = sorted(dispatches, key=sort_key)

        # Group by district
        for district, district_dispatches_iter in groupby(dispatches_sorted, key=attrgetter('district')):
            district_dispatches = list(district_dispatches_iter)
            
            # Paginate within the district
            for i in range(0, len(district_dispatches), chunk_size):
                dispatch_chunk = district_dispatches[i:i+chunk_size]
                if page_no > 1: 
                    elements.append(PageBreak())
                
                # Header
                elements.append(header_table)
                elements.append(Spacer(1, 8))

                # TO Table with Page number
                to_content = [
                    Paragraph("<b>TO</b>", to_style),
                    Paragraph(f"{contract.c_designation}, ", to_style),
                    Paragraph(f"{contract.company_name},", to_style),
                    Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                    Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                    Paragraph(f"GST NO. : {contract.gst_number}", to_style)
                ]
                bill_no_content = [
                    Paragraph(f"Bill No : {i_bill_no}", to_style),
                    Paragraph(f"Bill Date : {bill_date.strftime("%d-%m-%Y")}", to_style),
                    Paragraph(f"From : {contract.from_center}", to_style),
                    Paragraph(f"District : {district}", to_style),
                    Paragraph(f"Page : {page_no} ", to_style)
                ]
                
                to_table = Table([[to_content, bill_no_content]], colWidths=[222*mm,50*mm])
                to_table.setStyle(TableStyle([
                    ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2),
                    ("TOPPADDING",(0,0),(-1,-1),4),
                    ("BOTTOMPADDING",(0,0),(-1,-1),4)
                ]))
                elements.append(to_table)
                elements.append(Spacer(1,5))
                elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
                elements.append(Spacer(1,5))

                # Dispatch Table for this page
                elements.append(build_table_page(dispatch_chunk, add_total_row=True))
                elements.append(Spacer(1,8))

                # Signature per page
                signature_data = [
                    [Paragraph(f"<b>Verified By</b><br/>_________________<br/>{request.POST.get('v_by_name')}", to_style), Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{request.POST.get('r_by_name')}", to_style),
                     Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", to_right_style)],
                ]
                signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
                signature_table.setStyle(TableStyle([
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),
                    ("ALIGN",(0,1),(0,1),"LEFT"),
                    ("ALIGN",(1,1),(1,1),"RIGHT"),
                    ("TOPPADDING",(0,0),(-1,-1),5)
                ]))
                elements.append(signature_table)
                page_no += 1
    else:
        page_no=1
        total_pages = math.ceil(len(dispatches) / chunk_size)
        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0: elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1,8))

            # TO Table
            to_content = [
                Paragraph("<b>TO</b>", to_style),
                Paragraph(f"{contract.c_designation}, ", to_style),
                Paragraph(f"{contract.company_name},", to_style),
                Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                Paragraph(f"GST NO. : {contract.gst_number}", to_style)
            ]
            bill_no_content = [
                Paragraph(f"Bill No : {i_bill_no}", to_style),
                Paragraph(f"Bill Date : {bill_date.strftime("%d-%m-%Y")}", to_style),
                Paragraph(f"From : {contract.from_center}", to_style),
                Paragraph(f"Page : {page_no} of {total_pages}", to_style)
            ]
            to_table = Table([[to_content, bill_no_content]], colWidths=[222*mm,50*mm])

            to_table.setStyle(TableStyle([
                ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("ALIGN",(0,0),(0,0),"LEFT"),
                ("ALIGN",(1,0),(1,0),"RIGHT"),
                ("LEFTPADDING",(0,0),(-1,-1),2),
                ("RIGHTPADDING",(0,0),(-1,-1),2),
                ("TOPPADDING",(0,0),(-1,-1),4),
                ("BOTTOMPADDING",(0,0),(-1,-1),4)
            ]))
            
            elements.append(to_table)
            elements.append(Spacer(1,5))
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            elements.append(Spacer(1,5))
            # Dispatch Table
            elements.append(build_table_page(dispatch_chunk,add_total_row=False, is_last_page=is_last_page, all_dispatches=dispatches))
            elements.append(Spacer(1,10))

            # Signature per page
            signature_data = [
                    [Paragraph(f"<b>Verified By</b><br/>_________________<br/>{request.POST.get('v_by_name')}", to_style), Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{request.POST.get('r_by_name')}", to_style),
                     Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", to_right_style)],
                ]
            signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
            signature_table.setStyle(TableStyle([
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"CENTER"),
                    ("ALIGN",(2,0),(2,0),"RIGHT"),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("TOPPADDING",(0,0),(-1,-1),8),
                    ("BOTTOMPADDING",(0,0),(-1,-1),4),
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2)
                ]))
            elements.append(signature_table)
            page_no += 1

    # --- Build PDF ---
    doc.build(elements)
    buffer.seek(0)
    filename = f"{contract.company_name}_{i_bill_no.replace('/','-')}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename)

################################
## END OF GENRATE INOVICE PDF ##
################################

@session_required
def download_generate_invoice_pdf(request):
    if request.method == "POST":     
        contract_id = request.POST.get("contract_id")
        dispatch_ids =  [int(i) for i in request.POST.getlist("dispatch_ids")]
        i_bill_no = request.POST.get("bill_no")

        # Fetch contract and dispatch data
        try:
            contract = T_Contract.objects.get(id=contract_id)
            company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
            company = Company_user.objects.get(id=request.session['company_info']['company_id'])
            invoice = Invoice.objects.get(id=i_bill_no, company_id = request.session['company_info']['company_id'] , contract_id = contract.id)
        except T_Contract.DoesNotExist:
            messages.error(request, "Contract not found!")
            return redirect("view-dispatch-invoice")
        except Company_user.DoesNotExist:
            messages.error(request, "user not found!")
            return redirect("view-dispatch-invoice")
        except Invoice.DoesNotExist:
            messages.error(request, "Invoice not found!")
            return redirect("view-dispatch-invoice")
   
        dispatches = Dispatch.objects.filter(id__in=dispatch_ids).order_by('dep_date')
        # Sort by challan_no in ascending order
        dispatches = sort_dispatches_by_challan_asc(dispatches)
   
        bill_date_str = request.POST.get("bill_date")
        bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date() if bill_date_str else None
        
    # --- PDF Generation ---
    buffer = BytesIO()
    # Use reasonable margins for better readability
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=8 * mm,
        leftMargin=8 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # --- Styles ---
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=9, alignment=1, leading=12)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=7, alignment=1, leading=10)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=15, alignment=1, leading=18)
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0, leading=12)
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2, leading=12)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=7, alignment=2, leading=10)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=7, alignment=0, leading=10)
    # Uniform header style for all column names - same size for consistency
    to_right_style_desc_heading = ParagraphStyle(name="ToRightDesc", fontName="Helvetica-Bold", fontSize=7.5, alignment=1, leading=10)
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=7, alignment=2, leading=10)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='15'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[272*mm])
    header_table.setStyle(TableStyle([
        ('LINEBELOW', (0,2), (-1,2), 0.8, colors.black), 
        ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    fields = contract.invoice_fields
    chunk_size = int(request.POST.get('chunk', 10))  # dispatch per page

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None):
   
        # Header row
        label_map = {
            "sr_no": "Sr No",
            "depature_date": "Dep Date",
            "dep_date": "Dep Date",
            "dc_field": ("Challan No" if getattr(contract, "dc_field", None) in [None, "None", "null", ""] else str(getattr(contract, "dc_field"))),
            "truck_no": "Truck No",
            "party_name": "Party Name",
            "product_name": "Product",
            "district": "District",
            "taluka": "Taluka",
            "unloading_charge_1": "Unloading 1",
            "unloading_charge_2": "Unloading 2",
            "loading_charge": "Loading",
            "totalfreight": "Freight",
            "gc_note": "GC Note",
        }
        data = [[label_map.get(f, f.replace("_", " ").title()) for f in fields]]

        numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                        "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
        center_fields = ["sr_no", "gc_note"]

        # Compact typography for larger tables to reduce page breaks
        compact = len(dispatch_subset) >= 18
        compact_fs = 6.5 if compact else None
        # Taller rows for readability (compact mode still tries to fit one page)
        compact_leading = 9 if compact else None

        center_style_desc_local = ParagraphStyle(
            name="CenterDescLocalDl",
            parent=center_style_desc,
            fontSize=compact_fs or center_style_desc.fontSize,
            leading=compact_leading or center_style_desc.leading,
        )
        to_style_desc_local = ParagraphStyle(
            name="ToDescLocalDl",
            parent=to_style_desc,
            fontSize=compact_fs or to_style_desc.fontSize,
            leading=compact_leading or to_style_desc.leading,
        )
        to_right_style_desc_local = ParagraphStyle(
            name="ToRightDescLocalDl",
            parent=to_right_style_desc,
            fontSize=compact_fs or to_right_style_desc.fontSize,
            leading=compact_leading or to_right_style_desc.leading,
        )
        # Uniform header style for all column names
        header_style_uniform = ParagraphStyle(
            name="HeaderUniformDl",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize,
            leading=to_right_style_desc_heading.leading,
            alignment=1,  # Center all headers
        )
        to_right_style_desc_heading_local = ParagraphStyle(
            name="ToRightDescHeadingLocalDl",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize,  # Always use same size
            leading=to_right_style_desc_heading.leading,  # Always use same leading
            alignment=1,  # Center align all headers
        )
        total_style_local = ParagraphStyle(
            name="TotalStyleLocalDl",
            parent=total_style,
            fontSize=compact_fs or total_style.fontSize,
            leading=compact_leading or total_style.leading,
        )

        # Initialize page totals
        total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = 0

        # Build rows
        for idx, d in enumerate(dispatch_subset, start=1):
            total_amount = (float(d.totalfreight or 0) +
                            float(d.unloading_charge_1 or 0) +
                            float(d.unloading_charge_2 or 0) +
                            float(d.loading_charge or 0))

            total_freight_sum += float(d.totalfreight or 0)
            total_unloading_sum_1 += float(d.unloading_charge_1 or 0)
            total_unloading_sum_2 += float(d.unloading_charge_2 or 0)
            total_loading_sum += float(d.loading_charge or 0)
            total_amount_sum += total_amount
            total_weight += float(d.weight or 0)

            row = []
            for field in fields:
                if field == "sr_no":
                    row.append(idx)
                elif field in ("depature_date", "dep_date"):
                    row.append(d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "")
                elif field == "dc_field" or field == "None":
                    row.append(d.challan_no)
                elif field in ("luggage", "totalfreight"):
                    row.append(d.totalfreight)
                elif field in ("product_name", "product"):
                    row.append(d.product_name)
                elif field == "amount":
                    row.append(f"{total_amount:.2f}")
                elif field == "gc_note":
                    row.append(d.gc_note_no)
                elif field == "main_party":
                    row.append(d.main_party or "")
                elif field == "sub_party":
                    row.append(d.sub_party or "")
                else:
                    row.append(getattr(d, field, ""))
            data.append(row)                

        # Determine total row logic
        add_total = False
        total_row = []

        if contract.rate_type == "Distric-Wise" and add_total_row:
            # District-wise: page total only
            add_total = True
            dispatches_to_sum = dispatch_subset
        elif contract.rate_type != "Distric-Wise" and is_last_page:
            # Non District-wise: grand total on last page
            add_total = True
            dispatches_to_sum = all_dispatches

        if add_total:
            # Calculate totals
            total_weight = total_freight_sum = total_unloading_sum_1 = total_unloading_sum_2 = total_loading_sum = total_amount_sum = 0
            for d in dispatches_to_sum:
                total_amount = (float(d.totalfreight or 0) +
                                float(d.unloading_charge_1 or 0) +
                                float(d.unloading_charge_2 or 0) +
                                float(d.loading_charge or 0))
                total_freight_sum += float(d.totalfreight or 0)
                total_unloading_sum_1 += float(d.unloading_charge_1 or 0)
                total_unloading_sum_2 += float(d.unloading_charge_2 or 0)
                total_loading_sum += float(d.loading_charge or 0)
                total_amount_sum += total_amount
                total_weight += float(d.weight or 0)

            for i, field in enumerate(fields):
                if field == "weight":
                    total_row.append(f"{total_weight:.3f}")
                elif field in ("luggage", "totalfreight"):
                    total_row.append(f"{total_freight_sum:.2f}")
                elif field == "unloading_charge_1":
                    total_row.append(f"{total_unloading_sum_1:.3f}")
                elif field == "unloading_charge_2":
                    total_row.append(f"{total_unloading_sum_2:.3f}")
                elif field == "loading_charge":
                    total_row.append(f"{total_loading_sum:.3f}")
                elif field == "amount":
                    total_row.append(f"{total_amount_sum:.2f}")
                else:
                    total_row.append("")
            total_row[0] = "TOTAL"
            data.append(total_row)

        # Special column widths - optimized to prevent wrapping, all headers same size
        special_widths = {
            "Sr No": 10 * mm,
            ("Challan No" if getattr(contract, "dc_field", None) in [None, "None", "null", ""] else str(getattr(contract, "dc_field"))): 18 * mm,
            "Truck No": 28 * mm,
            "Party Name": 22 * mm,
            "Product": 20 * mm,
            "Gc Note": 12 * mm,
            "Weight": 14 * mm,
            "Km": 10 * mm,
            "Rate": 14 * mm,
            "Luggage": 16 * mm,
            "Unloading 1": 18 * mm,
            "Unloading 2": 18 * mm,
            "Loading": 16 * mm,
            "Freight": 14 * mm,
            "Dep Date": 18 * mm,
            "Destination": 22 * mm,
            "District": 16 * mm,
            "Taluka": 16 * mm,
        }

        table_width = 272 * mm
        headers = data[0]

        # Calculate column widths
        col_widths = []
        for col_name in headers:
            col_widths.append(special_widths.get(col_name, None))

        # Adjust remaining width - ensure valid values
        fixed_total = sum(w for w in col_widths if w is not None)
        remaining = max(0, table_width - fixed_total)  # Ensure non-negative
        num_other_cols = sum(1 for w in col_widths if w is None)
        if num_other_cols > 0 and remaining > 0:
            other_width = max(10 * mm, remaining / num_other_cols)  # Minimum 10mm
            col_widths = [w if w is not None else other_width for w in col_widths]
        else:
            # If no remaining width, set default for None values
            default_width = 15 * mm
            col_widths = [w if w is not None else default_width for w in col_widths]
        
        # Ensure all widths are valid and positive (minimum 5mm)
        col_widths = [max(5 * mm, float(w)) if w is not None else 15 * mm for w in col_widths]
        
        # Recalculate total and scale if needed to fit table width
        total_width = sum(col_widths)
        if total_width > table_width and total_width > 0:
            scale_factor = table_width / total_width
            col_widths = [w * scale_factor for w in col_widths]

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = fields[j]
                if i == 0:  # header - use uniform style for all column names
                    row[j] = Paragraph(f"<b>{cell}</b>", header_style_uniform)
                elif add_total and i == len(data) - 1:  # total/grand total row
                    row[j] = Paragraph(str(cell), total_style_local)
                else:
                    style = to_right_style_desc_local if field_name in numeric_fields else center_style_desc_local if field_name in center_fields else to_style_desc_local
                    row[j] = Paragraph(str(cell), style)

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles
        styles = [
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("LEFTPADDING", (0,0), (-1,-1), 2 if compact else 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 2 if compact else 4),
            # Header row height
            ("TOPPADDING", (0,0), (-1,0), 5 if compact else 7),
            ("BOTTOMPADDING", (0,0), (-1,0), 5 if compact else 7),
            # Body row height
            ("TOPPADDING", (0,1), (-1,-2), 3 if compact else 5),
            ("BOTTOMPADDING", (0,1), (-1,-2), 3 if compact else 5),
            ("LINEABOVE", (0,0), (-1,0), 0.5, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 0.5, colors.black),
            ("GRID", (0,0), (-1,-1), 0.2, colors.lightgrey),
            # Prevent text wrapping in cells
            ("WORDWRAP", (0,0), (-1,-1), "NORMAL"),
        ]
        for r in range(1, len(data) - (1 if add_total else 0)):
            if (r % 2) == 0:
                styles.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#FAFAFA")))
        if add_total:
            styles += [
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                ("SPAN", (0,-1), (2,-1)),
                ("TOPPADDING", (0,-1), (-1,-1), 6),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 6),
                ("LINEABOVE", (0,-1), (-1,-1), 0.5, colors.black),
                ("LINEBELOW", (0,-1), (-1,-1), 0.5, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table




    # --- Split dispatches per page ---
    if contract.rate_type == "Distric-Wise":
        page_no=1  
        # Sort dispatches by district, then by challan_no (ascending) within each district
        def sort_key(d):
            def get_numeric_value(challan_no):
                if not challan_no:
                    return 0
                num_match = re.search(r'\d+', str(challan_no))
                return int(num_match.group(0)) if num_match else 0
            # Positive for ascending challan order within each district
            return (d.district or '', get_numeric_value(d.challan_no))
        
        dispatches_sorted = sorted(dispatches, key=sort_key)
    
        total_pages = len(list(groupby(dispatches_sorted, key=attrgetter('district'))))
        # Group by district
        for district, district_dispatches_iter in groupby(dispatches_sorted, key=attrgetter('district')):
            district_dispatches = list(district_dispatches_iter)
            # print(district_dispatches)
            # Paginate within the district
            for i in range(0, len(district_dispatches), chunk_size):
                dispatch_chunk = district_dispatches[i:i+chunk_size]
                if page_no > 1: 
                    elements.append(PageBreak())
                
                # Header
                elements.append(header_table)
                elements.append(Spacer(1, 8))

                # TO Table with Page number
                to_content = [
                    Paragraph("<b>TO</b>", to_style),
                    Paragraph(f"{contract.c_designation}, ", to_style),
                    Paragraph(f"{contract.company_name},", to_style),
                    Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                    Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                    Paragraph(f"GST NO. : {contract.gst_number}", to_style)
                ]
                bill_no_content = [
                    Paragraph(f"Bill No : {invoice.Bill_no}", to_style),
                    Paragraph(f"Bill Date : {bill_date.strftime("%d-%m-%Y")}", to_style),
                    Paragraph(f"From : {contract.from_center}", to_style),
                    Paragraph(f"District : {district}", to_style),
                    Paragraph(f"Page : {page_no} of {total_pages} ", to_style)
                ]
                page_no += 1
                
                to_table = Table([[to_content, bill_no_content]], colWidths=[222*mm,50*mm])
                to_table.setStyle(TableStyle([
                    ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),  
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2),
                    ("TOPPADDING",(0,0),(-1,-1),4),
                    ("BOTTOMPADDING",(0,0),(-1,-1),4)
                ]))
                elements.append(to_table)
                elements.append(Spacer(1,5))
                elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
                elements.append(Spacer(1,5))

                # Dispatch Table for this page
                elements.append(build_table_page(dispatch_chunk, add_total_row=True))
                elements.append(Spacer(1,10))

                # Signature per page
                signature_data = [
                    [Paragraph(f"<b>Verified By</b><br/>_________________<br/>{request.POST.get('v_by_name')}", to_style), Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{request.POST.get('r_by_name')}", to_style),
                     Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", to_right_style)],
                ]
                signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
                signature_table.setStyle(TableStyle([
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"CENTER"),
                    ("ALIGN",(2,0),(2,0),"RIGHT"),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("TOPPADDING",(0,0),(-1,-1),8),
                    ("BOTTOMPADDING",(0,0),(-1,-1),4),
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2)
                ]))
                elements.append(signature_table)
    else:
        page_no = 1
        total_pages = math.ceil(len(dispatches) / chunk_size)

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1, 8))

            # TO Table
            to_content = [
                Paragraph("<b>TO</b>", to_style),
                Paragraph(f"{contract.c_designation}, ", to_style),
                Paragraph(f"{contract.company_name},", to_style),
                Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                Paragraph(f"GST NO. : {contract.gst_number}", to_style)
            ]
            bill_no_content = [
                Paragraph(f"Bill No : {invoice.Bill_no}", to_style),
                Paragraph(f"Bill Date : {bill_date.strftime('%d-%m-%Y')}", to_style),
                Paragraph(f"From : {contract.from_center}", to_style),
                Paragraph(f"Page : {page_no} of {total_pages}", to_style)
            ]
            page_no += 1

            to_table = Table([[to_content, bill_no_content]], colWidths=[222*mm, 50*mm])
            to_table.setStyle(TableStyle([
                ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("ALIGN",(0,0),(0,0),"LEFT"),
                ("ALIGN",(1,0),(1,0),"RIGHT"),
                ("LEFTPADDING",(0,0),(-1,-1),2),
                ("RIGHTPADDING",(0,0),(-1,-1),2),
                ("TOPPADDING",(0,0),(-1,-1),4),
                ("BOTTOMPADDING",(0,0),(-1,-1),4)
            ]))
            elements.append(to_table)  
            elements.append(Spacer(1,5))
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            elements.append(Spacer(1,5))

            # **Build table only ONCE per page**
            elements.append(build_table_page(dispatch_chunk, add_total_row=False, is_last_page=is_last_page, all_dispatches=dispatches))
            elements.append(Spacer(1,10))

            # Signature
            signature_data = [
                [
                    Paragraph(f"<b>Verified By</b><br/>_________________<br/>{request.POST.get('v_by_name')}", to_style),
                    Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{request.POST.get('r_by_name')}", to_style),
                    Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", to_right_style),
                ]
            ]
            signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
            signature_table.setStyle(TableStyle([
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"CENTER"),
                    ("ALIGN",(2,0),(2,0),"RIGHT"),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("TOPPADDING",(0,0),(-1,-1),8),
                    ("BOTTOMPADDING",(0,0),(-1,-1),4),
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2)
                ]))
            elements.append(signature_table)

    # --- Build PDF ---
    doc.build(elements)
    buffer.seek(0)
    filename = f"{contract.company_name}_{invoice.Bill_no.replace('/','-')}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename)


##########################################
## END OF DOWNLOAD GENRATED INOVICE PDF ##
##########################################


@session_required
def download_gc_pdf(request):
    if request.method == "POST":
        selected_gc_ids = request.POST.getlist('dispatch_ids')
        if not selected_gc_ids:
            messages.error(request, "No GC Notes selected for PDF generation.")
            return redirect("view-gc-note")

        gc_notes = GC_Note.objects.filter(id__in=selected_gc_ids, company_id=request.session['company_info']['company_id']).order_by('gc_no')
   

    buffer = BytesIO()

    # Create the PDF document
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiMin-W3'))
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=20)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterBold", alignment=1, fontSize=12, leading=14, spaceAfter=6, spaceBefore=3))
    styles.add(ParagraphStyle(name="Center", alignment=1, fontSize=9))
    styles.add(ParagraphStyle(name="font9", fontSize=9))
    elements = []  

    def make_gc_note(gc):
        to_table_data = [[Paragraph("<b>GOODS CONSINGNMENT NOTE</b>",styles["Normal"]), Paragraph(f"<b>NO : {gc.gc_no} </b>", styles["Normal"])]]

        to_table = Table(to_table_data, colWidths=[400, 88])  #adjust widths to fit page
        to_table.setStyle(TableStyle([ 
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (0,0), (0,0), "LEFT"),   
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
                  
        ]))  

        details_table_data = [
            [Paragraph(f"<b>Date</b>",styles["font9"]),":",Paragraph(f"{gc.gc_date}",styles["font9"]), Paragraph(f"<b>Truck No. </b>", styles["font9"]),":", Paragraph(f"{gc.truck_no}",styles["font9"])],
            [Paragraph(f"<b>Consignor</b>",styles["font9"]),":",Paragraph(f"{gc.consignor}",styles["font9"]), "", "" , ""],
            [Paragraph(f"<b>Depacth From</b>",styles["font9"]),":",Paragraph(f"{gc.dispatch_from}",styles["font9"]), Paragraph(f"<b>Weight</b>",styles["font9"]), ":" , Paragraph(f"{gc.weight}",styles["font9"])],
            [Paragraph(f"<b>Consignee</b>",styles["font9"]),":",Paragraph(f"{gc.consignee}",styles["font9"]),Paragraph(f"<b>Products</b>",styles["font9"]),":",Paragraph(f"{gc.product_name}",styles["font9"])],
            [Paragraph(f"<b>Challan no.</b>",styles["font9"]),":",Paragraph(f"{gc.dc_field}",styles["font9"]), Paragraph(f"<b>Bill No.</b>", styles["font9"]), ":" , Paragraph(f"{gc.bill_no}",styles["font9"])],
            [Paragraph(f"<b>Destination</b>",styles["font9"]),":",Paragraph(f"{gc.destination}",styles["font9"]), "" , "" , ""],
            [Paragraph(f"<b>District</b>", styles["font9"]), ":" , Paragraph(f"{gc.district}",styles["font9"]), "", "" , ""],   
            ]
        details_table = Table(details_table_data, rowHeights=14 , colWidths=[80,5,165,60,5,165])  #adjust widths to fit page
        details_table.setStyle(TableStyle([ 
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ('SPAN', (2,1), (-1,1)),
            ('FONTSIZE', (0,1),(-1,-1), 9)   ,
            ("ALIGN", (0,0), (0,0), "LEFT"),   
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
                  
        ]))

        company_profile = Company_profile.objects.get(company_id=request.session['company_info']['company_id'])
        company = Company_user.objects.get(id=request.session['company_info']['company_id'])

        data = [
            [Paragraph(f"<b>{request.session['company_info']['company_name']}</b>", styles["CenterBold"])],
            [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}<br/>"
                       f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", styles["Center"])],
            [HRFlowable(width="100%", thickness=1, color=colors.black)],
            [to_table],
            [HRFlowable(width="100%", thickness=1, color=colors.black)],
            [details_table],
            [Spacer(1, 10)],
            [Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b>", styles["Normal"])],
            [Spacer(1, 10)],
            [Paragraph("(Sign)", styles["Normal"])],
            [Spacer(1, 5)],
            [Paragraph(f"<font size=7>Consignor {gc.consignor} <br/>"
                       f"GST shall be Paid by {gc.consignor} under Reverse charge Mechanism (RCM)<br/>"
                       "No cenvat Credit of duty paid on inputs or capital good used for providing the taxable service has been taken</font>",
                       styles["Normal"])]
        ]
        
        table = Table(data, colWidths=[500])
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        return table

    # Loop through notes 3 per page
    for i, gc in enumerate(gc_notes):
        elements.append(make_gc_note(gc))
        elements.append(Spacer(1, 40))
        if (i + 1) % 2 == 0 and (i + 1) != len(gc_notes):
            elements.append(PageBreak())

    # Build PDF
    doc.build(elements)

    # Get the PDF content
    pdf = buffer.getvalue()
    buffer.close()

    # Return the response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="gc_notes.pdf"'
    response.write(pdf)
    return response


##########################################
## END OF GC_NOTE DOWLOAD ##
##########################################
    

def width_for_chars(num_chars, font_size=6, factor=0.6):
    """Estimate width in mm for given characters at a font size."""
    char_width_pt = font_size * factor  # width in points
    total_width_pt = num_chars * char_width_pt  
    return total_width_pt / 2.835

@session_required
def generate_summary_pdf(request):
    if request.method != "POST":
        return redirect("summary-view")
    
    contract_id = request.POST.get("contract_no")
    bill_ids = [int(i) for i in request.POST.getlist("bill_ids")]
    summary_date_str = request.POST.get("summary_date")
    
    if not contract_id or not bill_ids:
        messages.error(request, "Please select contract and at least one bill.")
        return redirect("summary-view")
    
    try:
        contract = T_Contract.objects.get(id=contract_id, company_id=request.session['company_info']['company_id'])
        company = Company_user.objects.get(id=request.session['company_info']['company_id'])
        try:
            company_profile = Company_profile.objects.get(company_id=company)
        except Company_profile.DoesNotExist:
            company_profile = None
    except (T_Contract.DoesNotExist, Company_user.DoesNotExist):
        messages.error(request, "Contract or company not found!")
        return redirect("summary-view")
    
    # Get selected invoices
    invoices = Invoice.objects.filter(
        id__in=bill_ids,
        contract_id=contract_id,
        company_id=request.session['company_info']['company_id']
    ).order_by('Bill_no')
    
    if not invoices.exists():
        messages.error(request, "No valid bills found.")
        return redirect("summary-view")
    
    # Parse summary date
    summary_date = None
    if summary_date_str:
        try:
            summary_date = datetime.strptime(summary_date_str, "%Y-%m-%d").date()
        except ValueError:
            summary_date = datetime.now().date()
    else:
        summary_date = datetime.now().date()
    
    # Collect bill data with totals
    bills_data = []
    total_mt = 0
    total_bill_amount = 0
    total_loading = 0
    total_unloading1 = 0
    total_unloading2 = 0
    total_grand_total = 0
    
    for invoice in invoices:
        dispatches = invoice.dispatch_list.all()
        
        if dispatches.exists():
            bill_mt = sum(float(d.weight) for d in dispatches if d.weight)
            bill_amount = sum(float(d.totalfreight) for d in dispatches if d.totalfreight)
            bill_loading = sum(float(d.loading_charge) for d in dispatches if d.loading_charge)
            bill_unloading1 = sum(float(d.unloading_charge_1) for d in dispatches if d.unloading_charge_1)
            bill_unloading2 = sum(float(d.unloading_charge_2) for d in dispatches if d.unloading_charge_2)
            
            bill_grand_total = bill_amount + bill_loading + bill_unloading1 + bill_unloading2
            
            bills_data.append({
                'bill_no': invoice.Bill_no,
                'mt': bill_mt,
                'bill_amount': bill_amount,
                'loading': bill_loading,
                'unloading1': bill_unloading1,
                'unloading2': bill_unloading2,
                'grand_total': bill_grand_total,
            })
            
            total_mt += bill_mt
            total_bill_amount += bill_amount
            total_loading += bill_loading
            total_unloading1 += bill_unloading1
            total_unloading2 += bill_unloading2
            total_grand_total += bill_grand_total
    
    # Get product name from first dispatch in selected invoices
    product_name = ""
    for invoice in invoices:
        dispatches = invoice.dispatch_list.all()
        if dispatches.exists():
            product_name = dispatches.first().product_name
            break
    
    # PDF Generation (match requested "Bill Summary" format)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    elements = []

    # ---- Styles ----
    title_center = ParagraphStyle(name="TitleCenter", fontName="Helvetica-Bold", fontSize=12, alignment=1, leading=14)
    small_center = ParagraphStyle(name="SmallCenter", fontName="Helvetica", fontSize=9, alignment=1, leading=11)
    normal = ParagraphStyle(name="Normal", fontName="Helvetica", fontSize=9, alignment=0, leading=11)
    normal_bold = ParagraphStyle(name="NormalBold", fontName="Helvetica-Bold", fontSize=9, alignment=0, leading=11)
    right = ParagraphStyle(name="Right", fontName="Helvetica", fontSize=9, alignment=2, leading=11)
    right_bold = ParagraphStyle(name="RightBold", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)
    center_bold = ParagraphStyle(name="CenterBold", fontName="Helvetica-Bold", fontSize=10, alignment=1, leading=12)
    cell_center = ParagraphStyle(name="CellCenter", fontName="Helvetica", fontSize=9, alignment=1, leading=11)
    cell_right = ParagraphStyle(name="CellRight", fontName="Helvetica", fontSize=9, alignment=2, leading=11)
    cell_header = ParagraphStyle(name="CellHeader", fontName="Helvetica-Bold", fontSize=9, alignment=1, leading=11)

    company_name = (company.company_name or "").upper()
    pan_no = (company_profile.pan_number if company_profile and company_profile.pan_number else "") if company_profile else ""
    gstin_no = (company.gst_number or "") if hasattr(company, "gst_number") else ""

    # ---- Header box ----
    header_lines = []
    if company_profile:
        addr_parts = [company_profile.address, company_profile.city, company_profile.state]
        addr = ", ".join([p for p in addr_parts if p])
        if company_profile.pincode:
            addr = f"{addr} - {company_profile.pincode}" if addr else str(company_profile.pincode)
        if addr:
            header_lines.append(Paragraph(addr, small_center))

    pan_gst_line = "  ".join([p for p in [f"PAN NO.{pan_no}" if pan_no else "", f"GSTIN:{gstin_no}" if gstin_no else ""] if p])

    header_cell = [
        Paragraph(company_name, title_center),
        Spacer(1, 2),
        *header_lines,
        Spacer(1, 2),
        Paragraph(pan_gst_line, small_center) if pan_gst_line else Paragraph("", small_center),
    ]
    header_table = Table([[header_cell]], colWidths=[A4[0] - doc.leftMargin - doc.rightMargin])
    header_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 8))

    # ---- To + Date row ----
    date_str = summary_date.strftime("%d.%m.%Y")
    to_lines = [
        Paragraph("To,", normal),
        Paragraph("The State Manager", normal_bold),
        Paragraph(f"{(contract.company_name or '').upper()}.", normal_bold),
    ]
    if contract.billing_address:
        to_lines.append(Paragraph(contract.billing_address, normal))
    city_state = ", ".join([p for p in [contract.billing_city, contract.billing_state] if p])
    if city_state:
        to_lines.append(Paragraph(city_state, normal))
    if contract.billing_pin:
        to_lines.append(Paragraph(f"PIN: {contract.billing_pin}", normal))
    if contract.gst_number:
        to_lines.append(Paragraph(f"GST NO.{contract.gst_number}", normal))

    to_date_table = Table(
        [[to_lines, [Paragraph(f"Date: {date_str}", right)]]],
        colWidths=[(A4[0] - doc.leftMargin - doc.rightMargin) * 0.7, (A4[0] - doc.leftMargin - doc.rightMargin) * 0.3],
    )
    to_date_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    elements.append(to_date_table)
    elements.append(Spacer(1, 6))

    elements.append(Paragraph("Bill Summary", center_bold))
    elements.append(Spacer(1, 6))

    # ---- FROM + Product row ----
    from_text = contract.from_center or ""
    product_text = product_name or ""
    from_prod_table = Table(
        [[Paragraph(f"<b>FROM:</b> {from_text}", normal), Paragraph(f"<b>Product :</b> {product_text}", right)]],
        colWidths=[(A4[0] - doc.leftMargin - doc.rightMargin) * 0.5, (A4[0] - doc.leftMargin - doc.rightMargin) * 0.5],
    )
    from_prod_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(from_prod_table)
    elements.append(Spacer(1, 6))

    # ---- Bills table (Sr, Bill No, M.T, Bill Amount, Loading, Unloading1, Unloading2, Grand Total) ----
    table_data = [
        [
            Paragraph("Sr.", cell_header),
            Paragraph("Bill No.", cell_header),
            Paragraph("M.T", cell_header),
            Paragraph("Bill Amount Rs.", cell_header),
            Paragraph("Loading Rs.", cell_header),
            Paragraph("Unloading 1 Rs.", cell_header),
            Paragraph("Unloading 2 Rs.", cell_header),
            Paragraph("Grand Total Rs.", cell_header),
        ]
    ]
    for idx, bill in enumerate(bills_data, 1):
        table_data.append(
            [
                Paragraph(str(idx), cell_center),
                Paragraph(str(bill["bill_no"]), cell_center),
                Paragraph(f"{bill['mt']:.3f}", cell_right),
                Paragraph(f"{bill['bill_amount']:.2f}", cell_right),
                Paragraph(f"{bill['loading']:.2f}", cell_right),
                Paragraph(f"{bill['unloading1']:.2f}", cell_right),
                Paragraph(f"{bill['unloading2']:.2f}", cell_right),
                Paragraph(f"{bill['grand_total']:.2f}", cell_right),
            ]
        )

    # Total row: "Total" spanning first two columns
    table_data.append(
        [
            Paragraph("Total", ParagraphStyle(name="TotalLeft", fontName="Helvetica-Bold", fontSize=9, alignment=1, leading=11)),
            "",
            Paragraph(f"{total_mt:.3f}", ParagraphStyle(name="TotalRight", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
            Paragraph(f"{total_bill_amount:.2f}", ParagraphStyle(name="TotalRight2", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
            Paragraph(f"{total_loading:.2f}", ParagraphStyle(name="TotalRight3", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
            Paragraph(f"{total_unloading1:.2f}", ParagraphStyle(name="TotalRight4", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
            Paragraph(f"{total_unloading2:.2f}", ParagraphStyle(name="TotalRight5", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
            Paragraph(f"{total_grand_total:.2f}", ParagraphStyle(name="TotalRight6", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
        ]
    )

    available_w = A4[0] - doc.leftMargin - doc.rightMargin
    # Fit 8 columns into available width while keeping Bill No readable
    col_widths = [
        9 * mm,   # Sr
        35 * mm,  # Bill No
        20 * mm,  # MT
        26 * mm,  # Bill Amount
        22 * mm,  # Loading
        24 * mm,  # Unloading 1
        24 * mm,  # Unloading 2
        0,        # Grand total (computed)
    ]
    fixed = sum(w for w in col_widths if w)
    col_widths[-1] = max(20 * mm, available_w - fixed)

    bill_table = Table(table_data, colWidths=col_widths)
    bill_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("SPAN", (0, -1), (1, -1)),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(bill_table)
    elements.append(Spacer(1, 10))

    # ---- Footer note + Signature ----
    elements.append(Paragraph("*GST Shall be paid by KRIBHCO under", normal))
    elements.append(Paragraph("RCM", normal))
    elements.append(Spacer(1, 14))

    sig_table = Table(
        [
            [
                Paragraph("", normal),
                Paragraph(f"FOR NARMADA TRANSPORT" if not company_name else f"FOR {company_name}", right_bold),
            ],
            ["", Paragraph("__________________", right)],
            ["", Paragraph("Authorised Signatory", right_bold)],
        ],
        colWidths=[available_w * 0.55, available_w * 0.45],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(sig_table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    filename = f"{contract.company_name}_{summary_date.strftime('%Y%m%d')}_Summary.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename) 