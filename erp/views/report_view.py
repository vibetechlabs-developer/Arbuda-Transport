from erp.utils.decorators import session_required
from erp.utils.financial_year import get_current_financial_year, get_financial_year_start_end
from transport.models import T_Contract, Company_user, Dispatch, Invoice, GC_Note, Destination
from company.models import Company_user , Company_profile
from django.shortcuts import render ,redirect ,get_object_or_404
from django.http import HttpResponse, FileResponse
from django.contrib import messages
from django.db.models import Q
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from datetime import datetime , date
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle ,PageBreak , HRFlowable, KeepTogether
from reportlab.lib.units import mm
from operator import attrgetter
from itertools import groupby
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

@session_required
def client_report_view(request):
    alldata = {} 
    try: 
        company_id = request.session['company_info']['company_id']
        financial_year = request.session.get('financial_year', get_current_financial_year())
        start_date, end_date = get_financial_year_start_end(financial_year)
        
        # Filter contracts that are active during the financial year
        # A contract is active if it overlaps with the financial year period
        # Contract overlaps if: (c_start_date <= end_date) AND (c_end_date >= start_date OR c_end_date is NULL)
        contracts = T_Contract.objects.filter(
            company_id_id=company_id
        ).filter(
            Q(c_start_date__lte=end_date) & (
                Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True)
            )
        ).order_by('-id')
        alldata['allcontracts'] = contracts
    except T_Contract.DoesNotExist:
        messages.error(request, "No contracts found.")
        alldata['contracts'] = None

    return render(request, 'client-report-view.html' , alldata)


@session_required
def download_report(request):
    if request.method == "POST":     
        i_contract_id = request.POST.get("contract_no")
        i_product_name = request.POST.get("product_name")
        i_bill_no = request.POST.get("bill_no")
        i_report_type = request.POST.get("type_of_report")


        

        # Fetch contract and dispatch data
        try:
            contract = T_Contract.objects.get(id=i_contract_id)
            i_company_id = Company_user.objects.get(id=request.session['company_info']['company_id'])
            company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
            company = Company_user.objects.get(id=request.session['company_info']['company_id'])
        except T_Contract.DoesNotExist:
            messages.error(request, "Contract not found!")
            return redirect("client-report-view")
        except Company_user.DoesNotExist: 
            messages.error(request, "user not found!")
            return redirect("client-report-view")

        if i_report_type == "product_wise":
            i_p_from_date = request.POST.get("p_from_date")
            i_p_to_date = request.POST.get("p_to_date")  
            f_from_date = datetime.strptime(i_p_from_date, "%Y-%m-%d").date() if i_p_from_date else None
            f_to_date = datetime.strptime(i_p_to_date, "%Y-%m-%d").date() if i_p_to_date else None
            dispatches = Dispatch.objects.filter(contract_id = i_contract_id,
                                              product_name = i_product_name,
                                              dep_date__range=(i_p_from_date, i_p_to_date),
                                              company_id = request.session['company_info']['company_id']
                                              ).order_by('dep_date')
        elif i_report_type == "date_wise":
            i_d_from_date = request.POST.get("d_from_date")
            i_d_to_date = request.POST.get("d_to_date")
            f_from_date = datetime.strptime(i_d_from_date, "%Y-%m-%d").date() if i_d_from_date else None
            f_to_date = datetime.strptime(i_d_to_date, "%Y-%m-%d").date() if i_d_to_date else None
            dispatches = Dispatch.objects.filter(contract_id = i_contract_id,
                                              dep_date__range=(i_d_from_date, i_d_to_date),
                                              company_id = request.session['company_info']['company_id']
                                              ).order_by('dep_date')
        else:
            messages.error(request, "Invalid report type selected!")
            return redirect("client-report-view")
        
        # Check if dispatches exist
        if not dispatches.exists():
            messages.error(request, "No dispatches found for the selected criteria!")
            return redirect("client-report-view")
   
        # --- PDF Generation ---
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
        styles = getSampleStyleSheet()
        elements = []

        # --- Styles ---
        # Slightly larger fonts for better readability,
        # with smaller font just for column headers.
        center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=10, alignment=1 ,leading=12)
        center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=9, alignment=1 ,leading=11)
        title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=11, alignment=1 ,leading=13) 
        to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0 ,leading=11)
        to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2 ,leading=11)
        total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)
        to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=9, alignment=0 ,leading=11)
        to_right_style_desc_heading = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=9, alignment=2 ,leading=11)
        to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=9, alignment=2 ,leading=11)

        # Header (column name) styles - slightly smaller font
        header_center_style_desc = ParagraphStyle(
            name="HeaderCenterDesc",
            parent=center_style_desc,
            fontSize=center_style_desc.fontSize - 1,
            leading=center_style_desc.leading - 1,
        )
        header_to_style_desc = ParagraphStyle(
            name="HeaderToDesc",
            parent=to_style_desc,
            fontSize=to_style_desc.fontSize - 1,
            leading=to_style_desc.leading - 1,
        )
        header_to_right_style_desc_heading = ParagraphStyle(
            name="HeaderToRightDescHeading",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize - 1,
            leading=to_right_style_desc_heading.leading - 1,
        )

        # --- Header Table ---
        report_title = "<b>Date Wise Dispacth Report</b>" if i_report_type == "date_wise" else "<b>Product Wise Dispacth Report</b>"
        header_data = [
            [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
            # [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
            [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
            [Paragraph(report_title, title_style)]
        ]
        header_table = Table(header_data, colWidths=[288*mm])
        header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

        fields = contract.invoice_fields
        # print("Fields for report:", fields)
        # Show fewer rows per page so rows can be taller and clearer
        chunk_size = 10  # Fixed to 10 entries per page


        # --- Build table for a page ---
        def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None, start_index=0):
            # Header row with readable labels
            header_row = []
            dc_field_label = getattr(contract, "dc_field", None)
            dc_field_label = dc_field_label if dc_field_label not in [None, "None", "null", ""] else "Challan No"

            for f in fields:
                if f == "dc_field":
                    header_text = dc_field_label
                elif f == "sr_no":
                    header_text = "Sr No"
                elif f in ("depature_date", "dep_date"):
                    header_text = "Dep Date"
                elif f == "truck_no":
                    header_text = "Truck No"
                elif f == "party_name":
                    header_text = "Party Name"
                elif f in ("product_name", "product"):
                    header_text = "Product"
                elif f == "gc_note":
                    header_text = "GC Note"
                elif f == "unloading_charge_1":
                    header_text = "Unload Chg 1"
                elif f == "unloading_charge_2":
                    header_text = "Unload Chg 2"
                elif f == "loading_charge":
                    header_text = "Loading Chg"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)

            data = [header_row]

            numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                            "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
            center_fields = ["sr_no", "gc_note"]

            # Initialize page totals
            total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = total_rate = total_km = 0

            # Build rows
            for idx, d in enumerate(dispatch_subset, start=start_index + 1):
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
                # District-wise: show totals per page
                add_total = True
                dispatches_to_sum = dispatch_subset
            elif contract.rate_type != "Distric-Wise" and is_last_page:
                # Other rate types: show grand total on last page
                add_total = True
                dispatches_to_sum = all_dispatches

            if add_total:
                total_weight = total_freight_sum = total_unloading_sum_1 = total_unloading_sum_2 = total_loading_sum = total_amount_sum = total_rate = total_km = 0
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
                    total_rate += float(d.rate or 0)
                    total_km += float(d.km or 0)

                for i, field in enumerate(fields):
                    if field == "weight":
                        total_row.append(f"{total_weight:.3f}")
                    elif field == "km":
                        total_row.append(f"{total_km:.3f}")
                    elif field == "rate":
                        total_row.append(f"{total_rate:.2f}")
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
                        style = (
                            header_to_right_style_desc_heading
                            if field_name in numeric_fields
                            else header_center_style_desc
                            if field_name in center_fields
                            else header_to_style_desc
                        )
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
                ("TOPPADDING", (0,0), (-1,0), 3),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0,0), (-1,0), 3),
                ("TOPPADDING", (0,1), (-1,-2), 1),  
                ("BOTTOMPADDING", (0,1), (-1,-2), 1),
                ("LINEABOVE", (0,0), (-1,0), 0.2, colors.black),
                ("LINEBELOW", (0,0), (-1,0), 0.2, colors.black),
            ]
            if add_total:
                styles += [
                    ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                    ("SPAN", (0,-1), (2,-1)),
                    ("TOPPADDING", (0,-1), (-1,-1), 3),
                    ("BOTTOMPADDING", (0,-1), (-1,-1), 3),
                    ("LINEABOVE", (0,-1), (-1,-1), 0.2, colors.black),
                    ("LINEBELOW", (0,-1), (-1,-1), 0.2, colors.black),
                ]
            table.setStyle(TableStyle(styles))

            return table


    
        
        page_no = 1

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1, 5))

            # TO Table
            date_range_text = ""
            if f_from_date and f_to_date:
                date_range_text = f"Dispatch Report From <b>{f_from_date.strftime('%d-%m-%Y')} To {f_to_date.strftime('%d-%m-%Y')}</b>"
            elif f_from_date:
                date_range_text = f"Dispatch Report From <b>{f_from_date.strftime('%d-%m-%Y')}</b>"
            elif f_to_date:
                date_range_text = f"Dispatch Report To <b>{f_to_date.strftime('%d-%m-%Y')}</b>"
            
            to_content = [
                    Paragraph(f"Dispatch From : <b>{contract.from_center}</b>", to_style),
                    Paragraph(date_range_text, to_style) if date_range_text else Paragraph("", to_style),
                ]
            bill_no_content = [
                    Paragraph(f"Report Date : {date.today().strftime('%d-%m-%Y')}", to_style),
                    Paragraph(f"Dispacth Product : <b>{i_product_name}</b>", to_style) if i_report_type == "product_wise" else Paragraph(f"", to_style), 
                    # Paragraph(f"From : {contract.from_center}", to_style),
                    # Paragraph(f"District : {district}", to_style),
                    # Paragraph(f"Page : {page_no} of {total_pages} ", to_style)
                ]
            page_no += 1

            to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm, 50*mm])
            to_table.setStyle(TableStyle([
                ('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("LEFTPADDING",(0,0),(-1,-1),0),
                ("RIGHTPADDING",(0,0),(-1,-1),0)
            ]))
            elements.append(to_table)  
            elements.append(Spacer(1,2))
            elements.append(Paragraph("<center><b>PERTICULARS</b></center>", center_style))
            elements.append(Spacer(1,2))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            elements.append(Spacer(1,2))
            add_total_row = contract.rate_type == "Distric-Wise"
            
            # Build table and signature together to keep on same page
            table = build_table_page(
                dispatch_chunk,
                add_total_row=add_total_row,
                is_last_page=is_last_page,
                all_dispatches=dispatches,
                start_index=i,
            )
            
            # Signature section on each page - more compact
            v_by_name = request.POST.get('v_by_name', '')
            r_by_name = request.POST.get('r_by_name', '')
            signature_style = ParagraphStyle(name="Signature", fontName="Helvetica", fontSize=8, alignment=0, leading=9)
            signature_right_style = ParagraphStyle(name="SignatureRight", fontName="Helvetica", fontSize=8, alignment=2, leading=9)
            signature_data = [
                [
                    Paragraph(f"<b>Verified By</b><br/>_________________<br/>{v_by_name}", signature_style),
                    Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{r_by_name}", signature_style),
                    Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", signature_right_style),
                ]
            ]
            signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
            signature_table.setStyle(TableStyle([
                ("ALIGN",(0,0),(0,0),"LEFT"),
                ("ALIGN",(1,0),(1,0),"CENTER"),
                ("ALIGN",(2,0),(2,0),"RIGHT"),
                ("TOPPADDING",(0,0),(-1,-1),2),
                ("BOTTOMPADDING",(0,0),(-1,-1),2),
                ("VALIGN",(0,0),(-1,-1),"TOP")
            ]))
            
            # Keep table and signature together on same page
            page_content = [
                table,
                Spacer(1,2),
                signature_table
            ]
            elements.append(KeepTogether(page_content))

        # --- Build PDF ---
        try:
            doc.build(elements)
            buffer.seek(0)
            filename = f"{contract.company_name}-Dispacth-Report.pdf"
            response = FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')
            return response
        except Exception as e:
            messages.error(request, f"Error generating PDF: {str(e)}")
            return redirect("client-report-view")
    else:
        # Handle non-POST requests
        messages.error(request, "Invalid request method!")
        return redirect("client-report-view")

    
##########################################
## END OF DOWNLOAD GENRATED INOVICE PDF ##
##########################################

def width_for_chars(num_chars, font_size=6, factor=0.6):
    """Estimate width in mm for given characters at a font size."""
    char_width_pt = font_size * factor  # width in points
    total_width_pt = num_chars * char_width_pt  
    return total_width_pt / 2.835 



def internal_report(request):

    """
    Internal report view (Create Report For US).
    This should behave the same as the client report view as far as
    populating the contract dropdown is concerned.
    """
    alldata = {}
    try:
        company_id = request.session["company_info"]["company_id"]
        financial_year = request.session.get('financial_year', get_current_financial_year())
        start_date, end_date = get_financial_year_start_end(financial_year)
        
        # Filter contracts that are active during the financial year
        # A contract is active if it overlaps with the financial year period
        # Contract overlaps if: (c_start_date <= end_date) AND (c_end_date >= start_date OR c_end_date is NULL)
        contracts = T_Contract.objects.filter(
            company_id_id=company_id
        ).filter(
            Q(c_start_date__lte=end_date) & (
                Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True)
            )
        ).order_by('-id')
        alldata["allcontracts"] = contracts
    except T_Contract.DoesNotExist:
        messages.error(request, "No contracts found.")
        alldata["contracts"] = None

    return render(request, "our-report-view.html", alldata)


@session_required
def download_our_report(request):
    """
    Download PDF report for internal use (our report).
    Same as client report but includes 5 additional columns:
    - truck_booking_rate
    - total_paid_truck_onwer
    - advance_paid
    - panding_amount
    - net_profit
    """
    if request.method == "POST":     
        i_contract_id = request.POST.get("contract_no")
        i_product_name = request.POST.get("product_name")
        i_bill_no = request.POST.get("bill_no")
        i_report_type = request.POST.get("type_of_report")

        # Fetch contract and dispatch data
        try:
            contract = T_Contract.objects.get(id=i_contract_id)
            i_company_id = Company_user.objects.get(id=request.session['company_info']['company_id'])
            company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
            company = Company_user.objects.get(id=request.session['company_info']['company_id'])
        except T_Contract.DoesNotExist:
            messages.error(request, "Contract not found!")
            return redirect("internal-report")
        except Company_user.DoesNotExist: 
            messages.error(request, "user not found!")
            return redirect("internal-report")

        if i_report_type == "product_wise":
            i_p_from_date = request.POST.get("p_from_date")
            i_p_to_date = request.POST.get("p_to_date")  
            f_from_date = datetime.strptime(i_p_from_date, "%Y-%m-%d").date() if i_p_from_date else None
            f_to_date = datetime.strptime(i_p_to_date, "%Y-%m-%d").date() if i_p_to_date else None
            dispatches = Dispatch.objects.filter(contract_id = i_contract_id,
                                              product_name = i_product_name,
                                              dep_date__range=(i_p_from_date, i_p_to_date),
                                              company_id = request.session['company_info']['company_id']
                                              ).order_by('dep_date')
        elif i_report_type == "date_wise":
            i_d_from_date = request.POST.get("d_from_date")
            i_d_to_date = request.POST.get("d_to_date")
            f_from_date = datetime.strptime(i_d_from_date, "%Y-%m-%d").date() if i_d_from_date else None
            f_to_date = datetime.strptime(i_d_to_date, "%Y-%m-%d").date() if i_d_to_date else None
            dispatches = Dispatch.objects.filter(contract_id = i_contract_id,
                                              dep_date__range=(i_d_from_date, i_d_to_date),
                                              company_id = request.session['company_info']['company_id']
                                              ).order_by('dep_date')
        else:
            messages.error(request, "Invalid report type selected!")
            return redirect("internal-report")
        
        # Check if dispatches exist
        if not dispatches.exists():
            messages.error(request, "No dispatches found for the selected criteria!")
            return redirect("internal-report")
   
        # --- PDF Generation ---
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
        styles = getSampleStyleSheet()
        elements = []

        # --- Styles --- (optimized for better fit with more columns)
        # Slightly larger fonts and spacing for a clearer internal report,
        # but keep column names a bit smaller than data rows.
        center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=10, alignment=1 ,leading=12)
        center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=8, alignment=1 ,leading=10)
        title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=11, alignment=1 ,leading=13) 
        to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0 ,leading=11)
        to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2 ,leading=11)
        total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=8, alignment=2, leading=10)
        to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=8, alignment=0 ,leading=10)
        to_right_style_desc_heading = ParagraphStyle(name="ToRightDescHeading", fontName="Helvetica-Bold", fontSize=8, alignment=2 ,leading=10)
        to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=8, alignment=2 ,leading=10)

        # Header (column name) styles - slightly smaller
        header_center_style_desc_internal = ParagraphStyle(
            name="HeaderCenterDescInternal",
            parent=center_style_desc,
            fontSize=center_style_desc.fontSize - 1,
            leading=center_style_desc.leading - 1,
        )
        header_to_style_desc_internal = ParagraphStyle(
            name="HeaderToDescInternal",
            parent=to_style_desc,
            fontSize=to_style_desc.fontSize - 1,
            leading=to_style_desc.leading - 1,
        )
        header_to_right_style_desc_heading_internal = ParagraphStyle(
            name="HeaderToRightDescHeadingInternal",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize - 1,
            leading=to_right_style_desc_heading.leading - 1,
        )

        # --- Header Table ---
        report_title = "<b>Date Wise Dispacth Report</b>" if i_report_type == "date_wise" else "<b>Product Wise Dispacth Report</b>"
        header_data = [
            [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
            # [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
            [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
            [Paragraph(report_title, title_style)]
        ]
        header_table = Table(header_data, colWidths=[288*mm])
        header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

        fields = contract.invoice_fields
        # print("Fields for report:", fields)
        # Add the 5 additional columns for internal report
        additional_fields = ["truck_booking_rate", "total_paid_truck_onwer", "advance_paid", "panding_amount", "net_profit"]
        fields = fields + additional_fields if fields else additional_fields
        # Fewer rows per page for better readability with many columns
        chunk_size = 10  # Fixed to 10 entries per page

        # --- Build table for a page ---
        def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None, start_index=0):
            # Header row with better formatting and shorter labels
            header_row = []
            dc_field_label = contract.dc_field if contract.dc_field and contract.dc_field not in [None, "None", "null", ""] else "Challan No"
            
            for f in fields:
                if f == "dc_field":
                    header_text = dc_field_label
                elif f == "truck_no":
                    header_text = "Truck No"
                elif f == "total_paid_truck_onwer":
                    header_text = "Total Paid Owner"  # Shorter label
                elif f == "panding_amount":
                    header_text = "Pending Amt"  # Shorter label
                elif f == "unloading_charge_1":
                    header_text = "Unload Chg 1"  # Shorter label
                elif f == "unloading_charge_2":
                    header_text = "Unload Chg 2"  # Shorter label
                elif f == "loading_charge":
                    header_text = "Loading Chg"  # Shorter label
                elif f == "truck_booking_rate":
                    header_text = "Truck Rate"  # Shorter label
                elif f == "gc_note":
                    header_text = "GC Note"
                elif f == "sr_no":
                    header_text = "Sr No"
                elif f == "product_name" or f == "product":
                    header_text = "Product"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)
            data = [header_row]

            numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                            "amount", "loading_charge", "totalfreight", "unloading_charge_2",
                            "truck_booking_rate", "total_paid_truck_onwer", "advance_paid", 
                            "panding_amount", "net_profit"]
            center_fields = ["sr_no", "gc_note"]

            # Initialize page totals
            total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = total_rate = total_km = 0
            total_truck_booking_rate = total_paid_truck_owner = total_advance_paid = total_panding_amount = total_net_profit = 0

            # Build rows
            for idx, d in enumerate(dispatch_subset, start=start_index + 1):
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
                
                # Additional fields totals
                total_truck_booking_rate += float(d.truck_booking_rate or 0)
                total_paid_truck_owner += float(d.total_paid_truck_onwer or 0)
                total_advance_paid += float(d.advance_paid or 0)
                total_panding_amount += float(d.panding_amount or 0)
                total_net_profit += float(d.net_profit or 0)

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
                    elif field == "truck_booking_rate":
                        row.append(f"{float(d.truck_booking_rate or 0):.2f}")
                    elif field == "total_paid_truck_onwer":
                        row.append(f"{float(d.total_paid_truck_onwer or 0):.2f}")
                    elif field == "advance_paid":
                        row.append(f"{float(d.advance_paid or 0):.2f}")
                    elif field == "panding_amount":
                        row.append(f"{float(d.panding_amount or 0):.2f}")
                    elif field == "net_profit":
                        row.append(f"{float(d.net_profit or 0):.2f}")
                    else:
                        row.append(getattr(d, field, ""))
                data.append(row)                

            # Determine total row logic
            add_total = False
            total_row = []

            if contract.rate_type == "Distric-Wise" and add_total_row:
                # District-wise: show totals per page
                add_total = True
                dispatches_to_sum = dispatch_subset
            elif contract.rate_type != "Distric-Wise" and is_last_page:
                # Other rate types: show grand total on last page
                add_total = True
                dispatches_to_sum = all_dispatches

            if add_total:
                total_weight = total_freight_sum = total_unloading_sum_1 = total_unloading_sum_2 = total_loading_sum = total_amount_sum = total_rate = total_km = 0
                total_truck_booking_rate = total_paid_truck_owner = total_advance_paid = total_panding_amount = total_net_profit = 0
                
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
                    total_rate += float(d.rate or 0)
                    total_km += float(d.km or 0)
                    
                    # Additional fields totals
                    total_truck_booking_rate += float(d.truck_booking_rate or 0)
                    total_paid_truck_owner += float(d.total_paid_truck_onwer or 0)
                    total_advance_paid += float(d.advance_paid or 0)
                    total_panding_amount += float(d.panding_amount or 0)
                    total_net_profit += float(d.net_profit or 0)

                for i, field in enumerate(fields):
                    if field == "weight":
                        total_row.append(f"{total_weight:.3f}")
                    elif field == "km":
                        total_row.append(f"{total_km:.3f}")
                    elif field == "rate":
                        total_row.append(f"{total_rate:.2f}")
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
                    elif field == "truck_booking_rate":
                        total_row.append(f"{total_truck_booking_rate:.2f}")
                    elif field == "total_paid_truck_onwer":
                        total_row.append(f"{total_paid_truck_owner:.2f}")
                    elif field == "advance_paid":
                        total_row.append(f"{total_advance_paid:.2f}")
                    elif field == "panding_amount":
                        total_row.append(f"{total_panding_amount:.2f}")
                    elif field == "net_profit":
                        total_row.append(f"{total_net_profit:.2f}")
                    else:
                        total_row.append("")
                total_row[0] = "TOTAL"
                data.append(total_row)

            # Special column widths - optimized for better fit with all columns
            special_widths = {
                "Sr No": 7 * mm,
                dc_field_label: 18 * mm,
                "Truck No": 14 * mm,
                "Party Name": 22 * mm,
                "Product": 18 * mm,
                "Product Name": 18 * mm,
                "GC Note": 11 * mm,
                "Gc Note": 11 * mm,
                "Weight": 11 * mm,
                "Km": 9 * mm,
                "Rate": 11 * mm,
                "Luggage": 13 * mm,
                "Unload Chg 1": 14 * mm,
                "Unloading Charge 1": 14 * mm,
                "Unload Chg 2": 14 * mm,
                "Unloading Charge 2": 14 * mm,
                "Loading Chg": 13 * mm,
                "Loading Charge": 13 * mm,
                "Truck Rate": 14 * mm,
                "Truck Booking Rate": 14 * mm,
                "Total Paid Owner": 16 * mm,
                "Total Paid Truck Onwer": 16 * mm,
                "Advance Paid": 13 * mm,
                "Pending Amt": 14 * mm,
                "Panding Amount": 14 * mm,
                "Net Profit": 13 * mm,
            }

            table_width = 288 * mm
            headers = data[0]

            # Calculate column widths - improved algorithm
            col_widths = []
            for col_name in headers:
                # Try exact match first
                width = special_widths.get(col_name, None)
                if width is None:
                    # Try case-insensitive match
                    width = next((special_widths[k] for k in special_widths.keys() if k.lower() == col_name.lower()), None)
                if width is None:
                    # Try partial match for common fields
                    col_lower = col_name.lower()
                    if "challan" in col_lower or "dc" in col_lower:
                        width = special_widths.get(dc_field_label, 18 * mm)
                    elif "truck" in col_lower and "no" in col_lower:
                        width = special_widths.get("Truck No", 14 * mm)
                    elif "unloading" in col_lower:
                        width = special_widths.get("Unload Chg 1", 14 * mm)
                    elif "loading" in col_lower:
                        width = special_widths.get("Loading Chg", 13 * mm)
                    elif "product" in col_lower:
                        width = special_widths.get("Product", 18 * mm)
                    else:
                        # Default width for unknown columns
                        width = 14 * mm
                col_widths.append(width)

            # Adjust column widths proportionally if total exceeds table width
            fixed_total = sum(col_widths)
            if fixed_total > table_width:
                # Scale down proportionally
                scale_factor = table_width / fixed_total
                col_widths = [w * scale_factor for w in col_widths]
            elif fixed_total < table_width:
                # Distribute remaining space proportionally
                remaining = table_width - fixed_total
                per_col = remaining / len(col_widths)
                col_widths = [w + per_col for w in col_widths]

            # Format cells
            for i, row in enumerate(data):
                for j, cell in enumerate(row):
                    field_name = fields[j]
                    if i == 0:  # header
                        style = (
                            header_to_right_style_desc_heading_internal
                            if field_name in numeric_fields
                            else header_center_style_desc_internal
                            if field_name in center_fields
                            else header_to_style_desc_internal
                        )
                        row[j] = Paragraph(f"<b>{cell}</b>", style)
                    elif add_total and i == len(data) - 1:  # total/grand total row
                        row[j] = Paragraph(str(cell), total_style)
                    else:
                        style = to_right_style_desc if field_name in numeric_fields else center_style_desc if field_name in center_fields else to_style_desc
                        row[j] = Paragraph(str(cell), style)

            table = Table(data, colWidths=col_widths, repeatRows=1)

            # Table styles - optimized padding for better fit
            styles = [
                ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),  # Changed to MIDDLE for better vertical alignment
                ("ALIGN", (0,0), (-1,0), "CENTER"),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("LEFTPADDING", (0,0), (-1,-1), 1),  # Reduced padding
                ("RIGHTPADDING", (0,0), (-1,-1), 1),  # Reduced padding
                ("TOPPADDING", (0,0), (-1,0), 2),  # Reduced padding
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0,0), (-1,0), 2),  # Reduced padding
                ("TOPPADDING", (0,1), (-1,-2), 1),  
                ("BOTTOMPADDING", (0,1), (-1,-2), 1),
                ("LINEABOVE", (0,0), (-1,0), 0.2, colors.black),
                ("LINEBELOW", (0,0), (-1,0), 0.2, colors.black),
            ]
            if add_total:
                styles += [
                    ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                    ("SPAN", (0,-1), (2,-1)),
                    ("TOPPADDING", (0,-1), (-1,-1), 2),  # Reduced padding
                    ("BOTTOMPADDING", (0,-1), (-1,-1), 2),  # Reduced padding
                    ("LINEABOVE", (0,-1), (-1,-1), 0.2, colors.black),
                    ("LINEBELOW", (0,-1), (-1,-1), 0.2, colors.black),
                ]
            table.setStyle(TableStyle(styles))

            return table

    
        
        page_no = 1

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1, 5))

            # TO Table
            date_range_text = ""
            if f_from_date and f_to_date:
                date_range_text = f"Dispatch Report From <b>{f_from_date.strftime('%d-%m-%Y')} To {f_to_date.strftime('%d-%m-%Y')}</b>"
            elif f_from_date:
                date_range_text = f"Dispatch Report From <b>{f_from_date.strftime('%d-%m-%Y')}</b>"
            elif f_to_date:
                date_range_text = f"Dispatch Report To <b>{f_to_date.strftime('%d-%m-%Y')}</b>"
            
            to_content = [
                    Paragraph(f"Dispatch From : <b>{contract.from_center}</b>", to_style),
                    Paragraph(date_range_text, to_style) if date_range_text else Paragraph("", to_style),
                ]
            bill_no_content = [
                    Paragraph(f"Report Date : {date.today().strftime('%d-%m-%Y')}", to_style),
                    Paragraph(f"Dispacth Product : <b>{i_product_name}</b>", to_style) if i_report_type == "product_wise" else Paragraph(f"", to_style), 
                    # Paragraph(f"From : {contract.from_center}", to_style),
                    # Paragraph(f"District : {district}", to_style),
                    # Paragraph(f"Page : {page_no} of {total_pages} ", to_style)
                ]
            page_no += 1

            to_table = Table([[to_content, bill_no_content]], colWidths=[238*mm, 50*mm])
            to_table.setStyle(TableStyle([
                ('LINEBELOW',(0,0),(-1,0),0.5,colors.black),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("LEFTPADDING",(0,0),(-1,-1),0),
                ("RIGHTPADDING",(0,0),(-1,-1),0)
            ]))
            elements.append(to_table)  
            elements.append(Spacer(1,2))
            elements.append(Paragraph("<center><b>PERTICULARS</b></center>", center_style))
            elements.append(Spacer(1,2))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            elements.append(Spacer(1,2))
            add_total_row = contract.rate_type == "Distric-Wise"
            
            # Build table and signature together to keep on same page
            table = build_table_page(
                dispatch_chunk,
                add_total_row=add_total_row,
                is_last_page=is_last_page,
                all_dispatches=dispatches,
                start_index=i,
            )
            
            # Signature section on each page - more compact
            v_by_name = request.POST.get('v_by_name', '')
            r_by_name = request.POST.get('r_by_name', '')
            signature_style = ParagraphStyle(name="Signature", fontName="Helvetica", fontSize=8, alignment=0, leading=9)
            signature_right_style = ParagraphStyle(name="SignatureRight", fontName="Helvetica", fontSize=8, alignment=2, leading=9)
            signature_data = [
                [
                    Paragraph(f"<b>Verified By</b><br/>_________________<br/>{v_by_name}", signature_style),
                    Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{r_by_name}", signature_style),
                    Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", signature_right_style),
                ]
            ]
            signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
            signature_table.setStyle(TableStyle([
                ("ALIGN",(0,0),(0,0),"LEFT"),
                ("ALIGN",(1,0),(1,0),"CENTER"),
                ("ALIGN",(2,0),(2,0),"RIGHT"),
                ("TOPPADDING",(0,0),(-1,-1),2),
                ("BOTTOMPADDING",(0,0),(-1,-1),2),
                ("VALIGN",(0,0),(-1,-1),"TOP")
            ]))
            
            # Keep table and signature together on same page
            page_content = [
                table,
                Spacer(1,2),
                signature_table
            ]
            elements.append(KeepTogether(page_content))

        # --- Build PDF ---
        try:
            doc.build(elements)
            buffer.seek(0)
            filename = f"{contract.company_name}-Dispacth-Report.pdf"
            response = FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')
            return response
        except Exception as e:
            messages.error(request, f"Error generating PDF: {str(e)}")
            return redirect("internal-report")
    else:
        # Handle non-POST requests
        messages.error(request, "Invalid request method!")
        return redirect("internal-report")


##########################################
## DISTANCE MASTER PDF GENERATION ##
##########################################

@session_required
def download_distance_master_pdf(request):
    """Generate PDF for all distance master data"""
    try:
        # Get current financial year
        company_id = request.session['company_info']['company_id']
        financial_year = request.session.get('financial_year', get_current_financial_year())
        start_date, end_date = get_financial_year_start_end(financial_year)

        # Get contract_id from request if provided (single select)
        contract_id = request.GET.get('contract_id')
        contract = None

        # Contracts active in the current financial year
        active_contracts = T_Contract.objects.filter(
            company_id_id=company_id
        ).filter(
            Q(c_start_date__lte=end_date) & (
                Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True)
            )
        )
        active_contract_ids = active_contracts.values_list('id', flat=True)

        # Fetch all distance data for the company, limited to active-year contracts
        all_routes = Destination.objects.filter(
            company_id=company_id,
            contract_id__in=active_contract_ids,
        ).order_by('id')
        
        # Filter by contract if contract_id is provided
        if contract_id:
            try:
                contract = T_Contract.objects.get(
                    id=contract_id,
                    company_id_id=company_id
                )
                # Only allow filtering by a contract that is active in the current financial year
                if contract.id in active_contract_ids:
                    all_routes = all_routes.filter(contract_id=contract_id)
                else:
                    messages.error(request, "Selected contract is not active in the current financial year.")
                    return redirect("rout-view")
            except T_Contract.DoesNotExist:
                messages.error(request, "Contract not found!")
                return redirect("rout-view")
        
        # Get company information
        company_profile = Company_profile.objects.get(company_id_id=request.session['company_info']['company_id'])
        company = Company_user.objects.get(id=request.session['company_info']['company_id'])
        
        # Check if routes exist
        if not all_routes.exists():
            messages.error(request, "No distance data found!")
            return redirect("rout-view")
        
        # --- PDF Generation ---
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
        styles = getSampleStyleSheet()
        elements = []
        
        # --- Styles ---
        center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=9, alignment=1, leading=12)
        center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=8, alignment=1, leading=10)
        title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=11, alignment=1, leading=15)
        to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0, leading=12)
        to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=8, alignment=2, leading=10)
        to_right_style_desc_heading = ParagraphStyle(name="ToRightDescHeading", fontName="Helvetica-Bold", fontSize=8, alignment=2, leading=10)
        to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=8, alignment=0, leading=10)
        
        # --- Header Table ---
        # Build report title with contract info if contract is selected
        report_title = "<b>Distance Master Report</b>"
        if contract:
            report_title = f"<b>Distance Master Report</b><br/><font size='9'>Contract: {contract.company_name} - {contract.contract_no} ({contract.rate_type})</font>"
        
        header_data = [
            [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
            [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
            [Paragraph(report_title, title_style)]
        ]
        header_table = Table(header_data, colWidths=[288*mm])
        header_table.setStyle(TableStyle([
            ('LINEBELOW', (0, 2), (-1, 2), 0.5, colors.black),
            ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black)
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 10))
        
        # Report date
        report_date_content = [
            Paragraph(f"Report Date : {date.today().strftime('%d-%m-%Y')}", to_style),
            Paragraph(f"Total Records : <b>{all_routes.count()}</b>", to_style)
        ]
        if contract:
            report_date_content.append(Paragraph(f"Contract Type : <b>{contract.rate_type}</b>", to_style))
        if contract:
            report_date_content.append(Paragraph(f"Contract Type : <b>{contract.rate_type}</b>", to_style))
        date_table = Table([[report_date_content]], colWidths=[288*mm])
        date_table.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0)
        ]))
        elements.append(date_table)
        elements.append(Spacer(1, 3))
        elements.append(Paragraph("<center><b>DISTANCE MASTER DATA</b></center>", center_style))
        elements.append(Spacer(1, 3))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
        elements.append(Spacer(1, 3))
        
        # --- Build table data ---
        chunk_size = 20  # Number of rows per page
        
        def build_distance_table(route_subset, is_last_page=False):
            # Header row
            headers = [
                "Sr No",
                "Contract ID",
                "From Center",
                "Destination",
                "Delivery Taluka",
                "Delivery District",
                "Kilometers"
            ]
            
            # Build data rows
            data = [headers]
            for idx, route in enumerate(route_subset, start=1):
                row = [
                    idx,
                    str(route.contract_id) if route.contract_id else "",
                    route.from_center or "",
                    route.destination or "",
                    route.taluka or "",
                    route.district or "",
                    route.km or 0
                ]
                data.append(row)
            
            # Column widths
            table_width = 288 * mm
            col_widths = [
                15 * mm,   # Sr No
                25 * mm,   # Contract ID
                35 * mm,   # From Center
                35 * mm,   # Destination
                30 * mm,   # Delivery Taluka
                30 * mm,   # Delivery District
                20 * mm    # Kilometers
            ]
            # Adjust remaining width
            fixed_total = sum(col_widths)
            remaining = table_width - fixed_total
            if remaining > 0:
                # Distribute remaining width proportionally
                col_widths[2] += remaining * 0.3  # From Center
                col_widths[3] += remaining * 0.3  # Destination
                col_widths[4] += remaining * 0.2  # Taluka
                col_widths[5] += remaining * 0.2  # District
            
            # Format cells
            for i, row in enumerate(data):
                for j, cell in enumerate(row):
                    if i == 0:  # Header row
                        if j == 0:  # Sr No
                            row[j] = Paragraph(f"<b>{cell}</b>", center_style_desc)
                        elif j == 6:  # Kilometers (numeric)
                            row[j] = Paragraph(f"<b>{cell}</b>", to_right_style_desc_heading)
                        else:
                            row[j] = Paragraph(f"<b>{cell}</b>", to_style_desc)
                    else:  # Data rows
                        if j == 0:  # Sr No
                            row[j] = Paragraph(str(cell), center_style_desc)
                        elif j == 6:  # Kilometers (numeric)
                            row[j] = Paragraph(str(cell), to_right_style_desc)
                        else:
                            row[j] = Paragraph(str(cell), to_style_desc)
            
            table = Table(data, colWidths=col_widths, repeatRows=1)
            
            # Table styles
            table_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, 0), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 1), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
                ("LINEABOVE", (0, 0), (-1, 0), 0.2, colors.black),
                ("LINEBELOW", (0, 0), (-1, 0), 0.2, colors.black),
            ]
            table.setStyle(TableStyle(table_style))
            
            return table
        
        # Paginate and build tables
        total_routes = all_routes.count()
        for i in range(0, total_routes, chunk_size):
            route_chunk = all_routes[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= total_routes
            
            if i > 0:
                elements.append(PageBreak())
                elements.append(header_table)
                elements.append(Spacer(1, 10))
            
            elements.append(build_distance_table(route_chunk, is_last_page))
            elements.append(Spacer(1, 20))
        
        # --- Build PDF ---
        try:
            doc.build(elements)
            buffer.seek(0)
            # Update filename to include contract info if contract is selected
            if contract:
                # Sanitize contract name and number for filename
                contract_name_safe = contract.company_name.replace(" ", "_").replace("/", "-")[:30]
                contract_no_safe = contract.contract_no.replace(" ", "_").replace("/", "-")
                filename = f"{request.session['company_info']['company_name']}-Distance-Master-{contract_name_safe}-{contract_no_safe}-{contract.rate_type}.pdf"
            else:
                filename = f"{request.session['company_info']['company_name']}-Distance-Master-Report.pdf"
            response = FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')
            return response
        except Exception as e:
            messages.error(request, f"Error generating PDF: {str(e)}")
            return redirect("rout-view")
            
    except Company_profile.DoesNotExist:
        messages.error(request, "Company profile not found!")
        return redirect("rout-view")
    except Company_user.DoesNotExist:
        messages.error(request, "Company not found!")
        return redirect("rout-view")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect("rout-view")