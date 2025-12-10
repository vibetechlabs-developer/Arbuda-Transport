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
from itertools import groupby
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont



@session_required
def generate_invoice_pdf(request):
    if request.method != "POST":
        return redirect("create-dispatch-invoice")

    # --- Fetch POST data ---
    contract_id = request.POST.get("contract_no")
    dispatch_ids = [int(i) for i in request.POST.getlist("dispatch_ids")]
    i_bill_no = request.POST.get("bill_no")
    bill_date_str = request.POST.get("bill_date")
    bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date() if bill_date_str else None

    if not dispatch_ids:
        messages.error(request, "Please select at least one dispatch to generate invoice.")
        return redirect("create-dispatch-invoice")

    # --- Fetch contract and company ---
    try:
        contract = T_Contract.objects.get(id=contract_id)
        i_company_id = Company_user.objects.get(id=request.session['company_info']['company_id'])
        company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
        company = Company_user.objects.get(id=request.session['company_info']['company_id'])
    except T_Contract.DoesNotExist:
        return HttpResponse("Contract not found", status=404)
    except Company_user.DoesNotExist:
        return HttpResponse("User's company not found", status=404)
    except Company_profile.DoesNotExist:
        return HttpResponse("Company profile not found", status=404)

    # --- Validate bill no ---
    if i_bill_no < contract.bill_series_from or i_bill_no > contract.bill_series_to:
        messages.error(request, f'Please enter valid bill no. {contract.bill_series_from} to {contract.bill_series_to}')
        return redirect('create-dispatch-invoice')

    if Invoice.objects.filter(Bill_no=i_bill_no, company_id=i_company_id, contract_id=contract.id).exists():
        messages.error(request, "Invoice with this bill number already exists!")
        return redirect("create-dispatch-invoice")

    # --- Create Invoice ---
    invoice = Invoice.objects.create(
        Bill_no=i_bill_no,
        Bill_date=bill_date,
        company_id=i_company_id,
        contract_id=contract,
    )

    dispatches = Dispatch.objects.filter(id__in=dispatch_ids).order_by('dep_date')
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
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=5*mm, bottomMargin=5*mm)
    styles = getSampleStyleSheet()
    elements = []

    # --- Styles ---
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=9, alignment=1 ,leading=12)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=7, alignment=1 ,leading=9)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=14, alignment=1 ,leading=18)
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0 ,leading=12)
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2 ,leading=12)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=7, alignment=2, leading=9)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=7, alignment=0 ,leading=9)
    to_right_style_desc_heading = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=8, alignment=2 ,leading=10)
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=7, alignment=2 ,leading=9)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        # [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[288*mm])
    header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

    fields = contract.invoice_fields
    chunk_size = int(request.POST.get('chunk', 10))  # dispatch per page

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None):
   
        # Header row
        data = [[("Challan No" if getattr(contract, f) in [None, "None", "null", ""] else getattr(contract, f))
                if f=="dc_field" else f.replace("_", " ").title() for f in fields]]

        numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                        "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
        center_fields = ["sr_no", "gc_note"]

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

        # Special column widths
        special_widths = {
            "Sr No": width_for_chars(5) * mm,
            f"{contract.dc_field}": width_for_chars(16) * mm,
            "truck_no": width_for_chars(10) * mm,
            "Party Name": width_for_chars(25) * mm,
            "Product Name": width_for_chars(14) * mm,
            "Gc Note": width_for_chars(8) * mm,
            "Weight": width_for_chars(10) * mm,
            "Km": width_for_chars(5) * mm,
            "Rate": width_for_chars(12) * mm,
            "Luggage": width_for_chars(14) * mm,
            "Unloading Charge 1": width_for_chars(14) * mm,
            "Loading Charge": width_for_chars(14) * mm,
        }

        table_width = 288 * mm
        headers = data[0]

        # Calculate column widths
        col_widths = []
        for col_name in headers:
            col_widths.append(special_widths.get(col_name, None))

        # Adjust remaining width
        fixed_total = sum(w for w in col_widths if w is not None)
        remaining = table_width - fixed_total
        num_other_cols = sum(1 for w in col_widths if w is None)
        if num_other_cols > 0:
            other_width = remaining / num_other_cols
            col_widths = [w if w is not None else other_width for w in col_widths]

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = fields[j]
                if i == 0:  # header
                    style = to_right_style_desc_heading if field_name in numeric_fields else center_style_desc if field_name in center_fields else to_style_desc
                    row[j] = Paragraph(f"<b>{cell}</b>", style)
                elif add_total and i == len(data) - 1:  # total/grand total row
                    row[j] = Paragraph(str(cell), total_style)
                else:
                    style = to_right_style_desc if field_name in numeric_fields else center_style_desc if field_name in center_fields else to_style_desc
                    row[j] = Paragraph(str(cell), style)

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles
        styles = [
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("LEFTPADDING", (0,0), (-1,-1), 2),
            ("RIGHTPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,0), 4),
            ("BOTTOMPADDING", (0,0), (-1,0), 4),
            ("TOPPADDING", (0,1), (-1,-2), 2),
            ("BOTTOMPADDING", (0,1), (-1,-2), 2),
            ("LINEABOVE", (0,0), (-1,0), 0.2, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 0.2, colors.black),
        ]
        if add_total:
            styles += [
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                ("SPAN", (0,-1), (2,-1)),
                ("TOPPADDING", (0,-1), (-1,-1), 4),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 4),
                ("LINEABOVE", (0,-1), (-1,-1), 0.2, colors.black),
                ("LINEBELOW", (0,-1), (-1,-1), 0.2, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table

    # --- Split dispatches per page ---

    if contract.rate_type == "Distric-Wise":
        # Sort dispatches by district
        page_no=1
        dispatches_sorted = sorted(dispatches, key=attrgetter('district'))

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
                elements.append(Spacer(1, 10))

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
                
                to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm,50*mm])
                to_table.setStyle(TableStyle([
                    ('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),
                    ("LEFTPADDING",(0,0),(-1,-1),0),
                    ("RIGHTPADDING",(0,0),(-1,-1),0)
                ]))
                elements.append(to_table)
                elements.append(Spacer(1,3))
                elements.append(Paragraph("<cneter><b>PERTICULARS</b></center>", center_style))
                elements.append(Spacer(1,3))

                # Dispatch Table for this page
                elements.append(build_table_page(dispatch_chunk, add_total_row=True))
                elements.append(Spacer(1,20))

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
            elements.append(Spacer(1,10))

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
            to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm,50*mm])

            to_table.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                                        ("VALIGN",(0,0),(-1,-1),"TOP"),
                                        ("ALIGN",(0,0),(0,0),"LEFT"),
                                        ("ALIGN",(1,0),(1,0),"RIGHT"),
                                        ("LEFTPADDING",(0,0),(-1,-1),0),
                                        ("RIGHTPADDING",(0,0),(-1,-1),0)]))
            
            elements.append(to_table)
            elements.append(Spacer(1,3))
            elements.append(Paragraph("<cneter><b>PERTICULARS</b></center>", center_style))
            elements.append(Spacer(1,3))
            # Dispatch Table
            elements.append(build_table_page(dispatch_chunk,add_total_row=False, is_last_page=is_last_page, all_dispatches=dispatches))
            elements.append(Spacer(1,20))

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
   
        bill_date_str = request.POST.get("bill_date")
        bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date() if bill_date_str else None
        
    # --- PDF Generation ---
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
    styles = getSampleStyleSheet()
    elements = []

    # --- Styles ---
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=9, alignment=1 ,leading=12)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=8, alignment=1 ,leading=10)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=14, alignment=1 ,leading=18)
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0 ,leading=12)
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2 ,leading=12)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=8, alignment=2, leading=10)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=8, alignment=0 ,leading=10)
    to_right_style_desc_heading = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=8, alignment=2 ,leading=10)
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=8, alignment=2 ,leading=15)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        # [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[288*mm])
    header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

    fields = contract.invoice_fields
    chunk_size = int(request.POST.get('chunk', 10))  # dispatch per page

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None):
   
        # Header row
        data = [[("Challan No" if getattr(contract, f) in [None, "None", "null", ""] else getattr(contract, f))
                if f=="dc_field" else f.replace("_", " ").title() for f in fields]]

        numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                        "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
        center_fields = ["sr_no", "gc_note"]

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

        # Special column widths
        special_widths = {
            "Sr No": width_for_chars(5) * mm,
            f"{contract.dc_field}": width_for_chars(16) * mm,
            "truck_no": width_for_chars(10) * mm,
            "Party Name": width_for_chars(25) * mm,
            "Product Name": width_for_chars(14) * mm,
            "Gc Note": width_for_chars(8) * mm,
            "Weight": width_for_chars(10) * mm,
            "Km": width_for_chars(5) * mm,
            "Rate": width_for_chars(12) * mm,
            "Luggage": width_for_chars(14) * mm,
            "Unloading Charge 1": width_for_chars(14) * mm,
            "Loading Charge": width_for_chars(14) * mm,
        }

        table_width = 288 * mm
        headers = data[0]

        # Calculate column widths
        col_widths = []
        for col_name in headers:
            col_widths.append(special_widths.get(col_name, None))

        # Adjust remaining width
        fixed_total = sum(w for w in col_widths if w is not None)
        remaining = table_width - fixed_total
        num_other_cols = sum(1 for w in col_widths if w is None)
        if num_other_cols > 0:
            other_width = remaining / num_other_cols
            col_widths = [w if w is not None else other_width for w in col_widths]

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = fields[j]
                if i == 0:  # header
                    style = to_right_style_desc_heading if field_name in numeric_fields else center_style_desc if field_name in center_fields else to_style_desc
                    row[j] = Paragraph(f"<b>{cell}</b>", style)
                elif add_total and i == len(data) - 1:  # total/grand total row
                    row[j] = Paragraph(str(cell), total_style)
                else:
                    style = to_right_style_desc if field_name in numeric_fields else center_style_desc if field_name in center_fields else to_style_desc
                    row[j] = Paragraph(str(cell), style)

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles
        styles = [
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("LEFTPADDING", (0,0), (-1,-1), 2),
            ("RIGHTPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,0), 4),
            ("BOTTOMPADDING", (0,0), (-1,0), 4),
            ("TOPPADDING", (0,1), (-1,-2), 2),
            ("BOTTOMPADDING", (0,1), (-1,-2), 2),
            ("LINEABOVE", (0,0), (-1,0), 0.2, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 0.2, colors.black),
        ]
        if add_total:
            styles += [
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                ("SPAN", (0,-1), (2,-1)),
                ("TOPPADDING", (0,-1), (-1,-1), 4),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 4),
                ("LINEABOVE", (0,-1), (-1,-1), 0.2, colors.black),
                ("LINEBELOW", (0,-1), (-1,-1), 0.2, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table




    # --- Split dispatches per page ---
    if contract.rate_type == "Distric-Wise":
        page_no=1  
        # Sort dispatches by district
        dispatches_sorted = sorted(dispatches, key=attrgetter('district'))
    
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
                elements.append(Spacer(1, 10))

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
                
                to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm,50*mm])
                to_table.setStyle(TableStyle([
                    ('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),  
                    ("LEFTPADDING",(0,0),(-1,-1),0),
                    ("RIGHTPADDING",(0,0),(-1,-1),0)
                ]))
                elements.append(to_table)
                elements.append(Spacer(1,3))
                elements.append(Paragraph("<cneter><b>PERTICULARS</b></center>", center_style))
                elements.append(Spacer(1,3))

                # Dispatch Table for this page
                elements.append(build_table_page(dispatch_chunk, add_total_row=True))
                elements.append(Spacer(1,20))

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
    else:
        page_no = 1
        total_pages = math.ceil(len(dispatches) / chunk_size)

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1, 10))

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

            to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm, 50*mm])
            to_table.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                                        ("VALIGN",(0,0),(-1,-1),"TOP"),
                                        ("ALIGN",(0,0),(0,0),"LEFT"),
                                        ("ALIGN",(1,0),(1,0),"RIGHT"),
                                        ("LEFTPADDING",(0,0),(-1,-1),0),
                                        ("RIGHTPADDING",(0,0),(-1,-1),0)]))
            elements.append(to_table)  
            elements.append(Spacer(1,3))
            elements.append(Paragraph("<cneter><b>PERTICULARS</b></center>", center_style))
            elements.append(Spacer(1,3))

            # **Build table only ONCE per page**
            elements.append(build_table_page(dispatch_chunk, add_total_row=False, is_last_page=is_last_page, all_dispatches=dispatches))
            elements.append(Spacer(1,20))

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
                    ("ALIGN",(1,0),(1,0),"RIGHT"),
                    ("ALIGN",(0,1),(0,1),"LEFT"),
                    ("ALIGN",(1,1),(1,1),"RIGHT"),
                    ("TOPPADDING",(0,0),(-1,-1),5)
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