from erp.utils.decorators import session_required
from transport.models import T_Contract, Company_user, Dispatch, Invoice, GC_Note
from company.models import Company_user , Company_profile
from django.shortcuts import render ,redirect ,get_object_or_404
from django.http import HttpResponse, FileResponse
from django.contrib import messages
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from datetime import datetime , date
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle ,PageBreak , HRFlowable
from reportlab.lib.units import mm
from operator import attrgetter
import math
from itertools import groupby
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

@session_required
def client_report_view(request):
    alldata = {} 
    try: 
        contracts = T_Contract.objects.filter(company_id_id=request.session['company_info']['company_id'])
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
        if i_report_type == "date_wise":
            i_d_from_date = request.POST.get("d_from_date")
            i_d_to_date = request.POST.get("d_to_date")
            f_from_date = datetime.strptime(i_d_from_date, "%Y-%m-%d").date() if i_d_from_date else None
            f_to_date = datetime.strptime(i_d_to_date, "%Y-%m-%d").date() if i_d_to_date else None
            dispatches = Dispatch.objects.filter(contract_id = i_contract_id,
                                              dep_date__range=(i_d_from_date, i_d_to_date),
                                              company_id = request.session['company_info']['company_id']
                                              ).order_by('dep_date')
   
    # --- PDF Generation ---
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
    styles = getSampleStyleSheet()
    elements = []

    # --- Styles ---
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=9, alignment=1 ,leading=12)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=8, alignment=1 ,leading=10)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=11, alignment=1 ,leading=15) 
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
        [Paragraph("<b>Date Wise Dispacth Report</b>", title_style)] if i_report_type == "dispatch_report" else [Paragraph("<b>Product Wise Dispacth Report</b>", title_style)] 
    ]
    header_table = Table(header_data, colWidths=[288*mm])
    header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

    fields = contract.invoice_fields
    # print("Fields for report:", fields)
    chunk_size = int(request.POST.get('chunk', 10))


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
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
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


    
    
    page_no = 1

    for i in range(0, len(dispatches), chunk_size):
        dispatch_chunk = dispatches[i:i+chunk_size]
        is_last_page = (i + chunk_size) >= len(dispatches)

        if i > 0:
            elements.append(PageBreak())

        elements.append(header_table)
        elements.append(Spacer(1, 10))

            # TO Table
        to_content = [
                Paragraph(f"Dispatch From : <b>{contract.from_center}</b>", to_style),
                Paragraph(f"Dispatch Report From <b>{f_from_date.strftime("%d-%m-%Y")} To {f_to_date.strftime("%d-%m-%Y")}</b>", to_style),
            ]
        bill_no_content = [
                Paragraph(f"Report Date : {date.today().strftime("%d-%m-%Y")}", to_style),
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
        elements.append(Spacer(1,3))
        elements.append(Paragraph("<cneter><b>PERTICULARS</b></center>", center_style))
        elements.append(Spacer(1,3))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
        elements.append(Spacer(1,3))
        # **Build table only ONCE per page**
        elements.append(build_table_page(dispatch_chunk, add_total_row=False, is_last_page=is_last_page, all_dispatches=dispatches))
        elements.append(Spacer(1,20))
        # Signature
        # signature_data = [
        #     [
        #         Paragraph(f"<b>Verified By</b><br/>_________________<br/>{request.POST.get('v_by_name')}", to_style),
        #         Paragraph(f"<b>Recommended By</b><br/>_________________<br/>{request.POST.get('r_by_name')}", to_style),
        #         Paragraph(f"<b>For, {request.session['company_info']['company_name']}</b><br/>_________________", to_right_style),
        #     ]
        # ]
        # signature_table = Table(signature_data, colWidths=[70*mm,70*mm,70*mm])
        # signature_table.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),5)]))
        # elements.append(signature_table)

    # --- Build PDF ---
    doc.build(elements)
    buffer.seek(0)
    filename = f"{contract.company_name}-Dispacth-Report.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename)

    
##########################################
## END OF DOWNLOAD GENRATED INOVICE PDF ##
##########################################

def width_for_chars(num_chars, font_size=6, factor=0.6):
    """Estimate width in mm for given characters at a font size."""
    char_width_pt = font_size * factor  # width in points
    total_width_pt = num_chars * char_width_pt  
    return total_width_pt / 2.835 



def internal_report(request):

    return render(request, 'our-report-view.html')