from erp.utils.decorators import session_required
from erp.utils.financial_year import get_current_financial_year, get_financial_year_start_end
from transport.models import T_Contract, Company_user, Dispatch, Invoice, GC_Note, Destination
from company.models import Company_user , Company_profile
from django.shortcuts import render ,redirect ,get_object_or_404
from django.http import HttpResponse, FileResponse
from django.contrib import messages
from django.db.models import Q, Func, F, IntegerField
from io import BytesIO
import csv
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
def outstanding_report_view(request):
    """
    Outstanding report view.
    Same contract dropdown and filters as client report, but the actual
    data (PDF/CSV + preview) will only include dispatches whose invoices
    have NOT been generated yet (inv_status = False).
    """
    alldata = {}
    try:
        company_id = request.session["company_info"]["company_id"]
        financial_year = request.session.get(
            "financial_year", get_current_financial_year()
        )
        start_date, end_date = get_financial_year_start_end(financial_year)

        contracts = (
            T_Contract.objects.filter(company_id_id=company_id)
            .filter(
                Q(c_start_date__lte=end_date)
                & (Q(c_end_date__gte=start_date) | Q(c_end_date__isnull=True))
            )
            .order_by("-id")
        )
        alldata["allcontracts"] = contracts
    except T_Contract.DoesNotExist:
        messages.error(request, "No contracts found.")
        alldata["contracts"] = None

    return render(request, "outstanding-report-view.html", alldata)


@session_required
def download_report(request):
    if request.method == "POST":     
        i_contract_id = request.POST.get("contract_no")
        i_product_name = request.POST.get("product_name")
        i_bill_no = request.POST.get("bill_no")
        i_report_type = request.POST.get("type_of_report")
        export_type = request.POST.get("export_type", "pdf")
        # When called from the Outstanding Report screen, this flag will be set.
        # In that mode we only include dispatches which are NOT yet billed
        # (inv_status = False).
        outstanding_only = (request.POST.get("outstanding_only") or "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

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
            base_qs = Dispatch.objects.filter(
                contract_id=i_contract_id,
                product_name=i_product_name,
                dep_date__range=(i_p_from_date, i_p_to_date),
                company_id=request.session["company_info"]["company_id"],
            )
            if outstanding_only:
                base_qs = base_qs.filter(inv_status=False)

            # Order: latest dispatch date first, and within each date challan_no ascending (numeric)
            dispatches = (
                base_qs.annotate(
                    challan_int=Func(
                        F("challan_no"),
                        function="CAST",
                        template="CAST(%(expressions)s AS UNSIGNED)",
                        output_field=IntegerField(),
                    )
                )
                .order_by("-dep_date", "challan_int")
            )
        elif i_report_type == "date_wise":
            i_d_from_date = request.POST.get("d_from_date")
            i_d_to_date = request.POST.get("d_to_date")
            f_from_date = datetime.strptime(i_d_from_date, "%Y-%m-%d").date() if i_d_from_date else None
            f_to_date = datetime.strptime(i_d_to_date, "%Y-%m-%d").date() if i_d_to_date else None
            base_qs = Dispatch.objects.filter(
                contract_id=i_contract_id,
                dep_date__range=(i_d_from_date, i_d_to_date),
                company_id=request.session["company_info"]["company_id"],
            )
            if outstanding_only:
                base_qs = base_qs.filter(inv_status=False)

            # Order: latest dispatch date first, and within each date challan_no ascending (numeric)
            dispatches = (
                base_qs.annotate(
                    challan_int=Func(
                        F("challan_no"),
                        function="CAST",
                        template="CAST(%(expressions)s AS UNSIGNED)",
                        output_field=IntegerField(),
                    )
                )
                .order_by("-dep_date", "challan_int")
            )
        else:
            messages.error(request, "Invalid report type selected!")
            return redirect("client-report-view")
        
        # Check if dispatches exist
        if not dispatches.exists():
            messages.error(request, "No dispatches found for the selected criteria!")
            return redirect("client-report-view")

        # If user requested CSV export, generate CSV instead of PDF
        if export_type == "csv":
            # Use same fields as invoice/report table
            fields = contract.invoice_fields or []

            # Build readable header labels similar to PDF
            dc_field_label = getattr(contract, "dc_field", None)
            dc_field_label = dc_field_label if dc_field_label not in [None, "None", "null", ""] else "Challan No"

            header_row = []
            for f in fields:
                if f == "dc_field":
                    header_text = dc_field_label
                elif f == "sr_no":
                    # Very short label so it never overwrites adjacent column
                    header_text = "Sr"
                elif f in ("depature_date", "dep_date"):
                    header_text = "Dep Date"
                elif f == "truck_no":
                    header_text = "Truck No"
                elif f == "party_name":
                    header_text = "Party Name"
                elif f in ("product_name", "product"):
                    header_text = "Product"
                elif f == "gc_note":
                    header_text = "GC No"
                elif f == "unloading_charge_1":
                    header_text = "Unload Chg 1"
                elif f == "unloading_charge_2":
                    header_text = "Unload Chg 2"
                elif f == "loading_charge":
                    header_text = "Loading Chg"
                elif f == "amount":
                    header_text = "Amount"
                elif f == "totalfreight":
                    header_text = "Freight"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)

            # Prepare HTTP response
            filename = f"{contract.company_name}-Dispatch-Report.csv"
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

            writer = csv.writer(response)
            writer.writerow(header_row)

            # Write data rows
            for idx, d in enumerate(dispatches, start=1):
                total_amount = (
                    float(d.totalfreight or 0)
                    + float(d.unloading_charge_1 or 0)
                    + float(d.unloading_charge_2 or 0)
                    + float(d.loading_charge or 0)
                )

                row = []
                for field in fields:
                    if field == "sr_no":
                        row.append(idx)
                    elif field in ("depature_date", "dep_date"):
                        # Write date as plain text to avoid Excel showing ##### on narrow columns
                        if d.dep_date:
                            date_str = d.dep_date.strftime("%d-%m-%Y")
                            row.append(f"'{date_str}")
                        else:
                            row.append("")
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

                writer.writerow(row)

            return response

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
        # Header styles: slightly smaller font and **no wrapping** so column
        # names never break like "Luggag" / "e" or "Unload Ch" / "g 1".
        header_center_style_desc = ParagraphStyle(
            name="HeaderCenterDesc",
            parent=center_style_desc,
            fontSize=center_style_desc.fontSize - 1,
            leading=center_style_desc.leading - 1,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )
        header_to_style_desc = ParagraphStyle(
            name="HeaderToDesc",
            parent=to_style_desc,
            fontSize=to_style_desc.fontSize - 1,
            leading=to_style_desc.leading - 1,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )
        header_to_right_style_desc_heading = ParagraphStyle(
            name="HeaderToRightDescHeading",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize - 1,
            leading=to_right_style_desc_heading.leading - 1,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )

        # Styles where content must NOT break across lines (for clean standard layout)
        no_break_date_style = ParagraphStyle(
            name="NoBreakDateClient",
            parent=center_style_desc,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )
        no_break_text_style = ParagraphStyle(
            name="NoBreakTextClient",
            parent=to_style_desc,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )

        # --- Header Table ---
        base_title = (
            "Date Wise Dispacth Report"
            if i_report_type == "date_wise"
            else "Product Wise Dispacth Report"
        )
        if outstanding_only:
            report_title = f"<b>Outstanding {base_title}</b>"
        else:
            report_title = f"<b>{base_title}</b>"
        header_data = [
            [Paragraph(f"<font color='black' size='14'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
            # [Paragraph(f"{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],
            [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
            [Paragraph(report_title, title_style)]
        ]
        header_table = Table(header_data, colWidths=[288*mm])
        header_table.setStyle(TableStyle([('LINEBELOW', (0,2), (-1,2), 0.5, colors.black), ('LINEBELOW', (0,1), (-1,1), 0.5, colors.black)]))

        fields = contract.invoice_fields
        # Use 12 rows per page so layout matches invoice and other reports
        chunk_size = 12

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
                # Use very short labels for money columns so they never overwrite neighbours
                elif f == "luggage":
                    header_text = "Lugg"
                elif f == "unloading_charge_1":
                    header_text = "Unld1"
                elif f == "unloading_charge_2":
                    header_text = "Unld2"
                elif f == "loading_charge":
                    header_text = "Load"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)

            data = [header_row]

            numeric_fields = ["weight", "km", "rate", "luggage", "unloading_charge_1",
                            "amount", "loading_charge", "totalfreight", "unloading_charge_2"]
            # Center some key text columns to create natural space from cell borders
            # (visually increasing space between Dep Date & Truck No, Destination & Product, District & Product).
            center_fields = [
                "sr_no",
                "gc_note",
                "depature_date",
                "dep_date",
                "destination",
                "district",
                "product_name",
                "product",
            ]

            # Initialize page totals
            total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = total_rate = total_km = 0

            # --- Numeric format helpers (for consistent decimals in the report) ---
            def _money(val):
                """Format currency/amount values with exactly 2 decimal places."""
                try:
                    if val in (None, "", "None", "null", "NULL", "-"):
                        return "0.00"
                    return f"{float(val):.2f}"
                except Exception:
                    return "0.00"

            def _num2(val):
                """Generic 2‑decimal formatter (for Rate etc.)."""
                try:
                    if val in (None, "", "None", "null", "NULL", "-"):
                        return "0.00"
                    return f"{float(val):.2f}"
                except Exception:
                    return "0.00"

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
                        # Use non‑breaking hyphens so the date never splits across lines
                        row.append(d.dep_date.strftime("%d\u2011%m\u2011%Y") if d.dep_date else "")
                    elif field == "dc_field" or field == "None":
                        row.append(d.challan_no)
                    elif field in ("luggage", "totalfreight"):
                        # Show per‑row freight with 2 decimals
                        row.append(_money(d.totalfreight))
                    elif field in ("product_name", "product"):
                        row.append(d.product_name)
                    elif field == "amount":
                        # Per‑row total amount with 2 decimals
                        row.append(_money(total_amount))
                    elif field == "weight":
                        # Weight with exactly 2 decimals for this report
                        row.append(_num2(d.weight))
                    elif field == "gc_note":
                        row.append(d.gc_note_no)
                    elif field == "rate":
                        # Rate with exactly 2 decimals
                        row.append(_num2(d.rate))
                    else:
                        row.append(getattr(d, field, ""))
                data.append(row)                

            # Determine total row logic
            # For this client report, show a TOTAL row **on every page**.
            # Each page's TOTAL reflects only the dispatches shown on that page.
            add_total = True
            total_row = []
            dispatches_to_sum = dispatch_subset

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
                        # Show total weight (MT) with 2 decimals
                        total_row.append(_num2(total_weight))
                    elif field in ("km", "rate"):
                        # Do not show totals for km and rate fields
                        total_row.append("")
                    elif field in ("depature_date", "dep_date"):
                        total_row.append("")  # No total for date
                    elif field in ("dc_field", "challan_no"):
                        total_row.append("")  # No total for challan no
                    elif field in ("luggage", "totalfreight"):
                        # Freight total with 2 decimals
                        total_row.append(_money(total_freight_sum))
                    elif field == "unloading_charge_1":
                        total_row.append(_money(total_unloading_sum_1))
                    elif field == "unloading_charge_2":
                        total_row.append(_money(total_unloading_sum_2))
                    elif field == "loading_charge":
                        total_row.append(_money(total_loading_sum))
                    elif field == "amount":
                        # Grand total amount with 2 decimals
                        total_row.append(_money(total_amount_sum))
                    else:
                        total_row.append("")
                total_row[0] = "TOTAL"
                data.append(total_row)

            # Special column widths
            special_widths = {
                # Sr column slightly wider so number + header fit cleanly
                "Sr": 10 * mm,
                "Sr No": 10 * mm,
                # Widened so full date (e.g. 13‑03‑2026) fits on one line and
                # leaves a bit of blank space before the Truck No column.
                "Dep Date": 18 * mm,
                f"{contract.dc_field}": 18 * mm,
                "truck_no": 14 * mm,
                # Key text columns widened so destination / district / product names don't break
                # and to create more visual separation between these adjacent columns.
                "Party Name": 24 * mm,
                "Product Name": 20 * mm,
                "Destination": 24 * mm,
                "District": 20 * mm,
                "Taluka": 16 * mm,
                "Gc Note": 10 * mm,
                "Weight": 12 * mm,
                "Km": 9 * mm,
                "Rate": 11 * mm,
                # Money columns: short labels and enough width so they don't overwrite neighbours
                "Lugg": 13 * mm,
                "Luggage": 13 * mm,
                "Unld1": 15 * mm,
                "Unld2": 15 * mm,
                "Unload Chg 1": 15 * mm,
                "Unload Chg 2": 15 * mm,
                "Unloading Charge 1": 15 * mm,
                "Loading Charge": 13 * mm,
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
                        # Prevent header labels like "Dep Date" or "Party Name"
                        # from breaking into two lines by using non‑breaking spaces
                        cell_text = str(cell).replace(" ", "\u00A0")
                        style = (
                            header_to_right_style_desc_heading
                            if field_name in numeric_fields
                            else header_center_style_desc
                            if field_name in center_fields
                            else header_to_style_desc
                        )
                        row[j] = Paragraph(f"<b>{cell_text}</b>", style)
                    elif add_total and i == len(data) - 1:  # total/grand total row
                        row[j] = Paragraph(str(cell), total_style)
                    else:
                        # Force no‑wrap for dates and key text fields so data never splits
                        if field_name in ("depature_date", "dep_date"):
                            style = no_break_date_style
                        elif field_name in ("destination", "district", "taluka", "party_name", "product_name", "product"):
                            style = no_break_text_style
                        else:
                            style = (
                                to_right_style_desc
                                if field_name in numeric_fields
                                else center_style_desc
                                if field_name in center_fields
                                else to_style_desc
                            )
                        row[j] = Paragraph(str(cell), style)

            table = Table(data, colWidths=col_widths, repeatRows=1)

            # Table styles (tuned for clean, standard spacing)
            styles = [
                ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
                # Keep text visually centered in each cell to avoid cramped / glitchy look
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("ALIGN", (0,0), (-1,0), "CENTER"),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                # Slightly more horizontal and vertical padding for breathing room
                ("LEFTPADDING", (0,0), (-1,-1), 3),
                ("RIGHTPADDING", (0,0), (-1,-1), 3),
                # Header row padding
                ("TOPPADDING", (0,0), (-1,0), 4),
                ("BOTTOMPADDING", (0,0), (-1,0), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                # Data rows padding
                ("TOPPADDING", (0,1), (-1,-2), 3),  
                ("BOTTOMPADDING", (0,1), (-1,-2), 3),
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
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            elements.append(Spacer(1,2))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            elements.append(Spacer(1,2))
            # Always show a TOTAL row per page for this client report
            add_total_row = True
            
            # Build table and signature together to keep on same page
            table = build_table_page(
                dispatch_chunk,
                add_total_row=add_total_row,
                is_last_page=is_last_page,
                all_dispatches=dispatches,
                start_index=i,
            )

            # Only the table (no Verified / Recommended / For footer)
            elements.append(table)

        # --- Build PDF ---
        try:
            doc.build(elements)
            buffer.seek(0)
            filename = f"{contract.company_name}-Dispacth-Report.pdf"
            # Inline preview by default; only download when ?download=1 or hidden input is sent
            download_flag = request.POST.get("download") or request.GET.get("download")
            response = FileResponse(
                buffer,
                as_attachment=bool(download_flag),
                filename=filename,
                content_type='application/pdf',
            )
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
        export_type = request.POST.get("export_type", "pdf")

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

        # --- CSV Generation (internal report for us) ---
        if export_type == "csv":
            # Base fields come from contract.invoice_fields; append internal-only columns
            base_fields = list(contract.invoice_fields or [])
            additional_fields = ["truck_booking_rate", "total_paid_truck_onwer", "advance_paid", "panding_amount", "net_profit"]
            fields = base_fields + additional_fields

            # Build readable header labels similar to client CSV
            dc_field_label = getattr(contract, "dc_field", None)
            dc_field_label = dc_field_label if dc_field_label not in [None, "None", "null", ""] else "Challan No"

            header_row = []
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
                elif f == "amount":
                    header_text = "Amount"
                elif f == "totalfreight":
                    header_text = "Freight"
                elif f == "truck_booking_rate":
                    header_text = "Truck Rate"
                elif f == "total_paid_truck_onwer":
                    # Stack into two lines so it doesn't collide with neighbours
                    header_text = "Total Paid<br/>Owner"
                elif f == "advance_paid":
                    header_text = "Advance Paid"
                elif f == "panding_amount":
                    header_text = "Pending Amt"
                elif f == "net_profit":
                    header_text = "Net Profit"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)

            filename = f"{contract.company_name}-Internal-Dispatch-Report.csv"
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename=\"{filename}\"'

            writer = csv.writer(response)
            writer.writerow(header_row)

            for idx, d in enumerate(dispatches, start=1):
                total_amount = (
                    float(d.totalfreight or 0)
                    + float(d.unloading_charge_1 or 0)
                    + float(d.unloading_charge_2 or 0)
                    + float(d.loading_charge or 0)
                )

                row = []
                for field in fields:
                    if field == "sr_no":
                        row.append(idx)
                    elif field in ("depature_date", "dep_date"):
                        if d.dep_date:
                            date_str = d.dep_date.strftime("%d-%m-%Y")
                            row.append(f"'{date_str}")
                        else:
                            row.append("")
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

                writer.writerow(row)

            return response

        # --- PDF Generation ---
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=2*mm, leftMargin=2*mm, topMargin=3*mm, bottomMargin=5*mm)
        styles = getSampleStyleSheet()
        elements = []

        # --- Styles ---
        # Keep internal report visually consistent with client report, just with
        # a slightly more compact data font so additional columns fit cleanly.
        center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=10, alignment=1, leading=12)
        center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=9, alignment=1, leading=11)
        title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=11, alignment=1, leading=13)
        to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=9, alignment=0, leading=11)
        to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=9, alignment=2, leading=11)
        total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)
        to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=8, alignment=0, leading=10)
        to_right_style_desc_heading = ParagraphStyle(
            name="ToRightDescHeading",
            fontName="Helvetica-Bold",
            fontSize=8,
            alignment=2,
            leading=10,
        )
        to_right_style_desc = ParagraphStyle(
            name="ToRightDesc",
            fontName="Helvetica",
            fontSize=8,
            alignment=2,
            leading=10,
        )

        # Header styles: use non‑breaking spaces and no wrapping so column names
        # never split across lines (same idea as client report).
        # For internal report (more columns), use slightly smaller header fonts and
        # allow wrapping on long labels so they don't visually overwrite neighbours.
        header_center_style_desc_internal = ParagraphStyle(
            name="HeaderCenterDescInternal",
            parent=center_style_desc,
            fontSize=center_style_desc.fontSize - 1.5,
            leading=center_style_desc.leading - 1,
            # allow natural wrapping for long labels
            wordWrap="CJK",
            splitLongWords=0,
        )
        header_to_style_desc_internal = ParagraphStyle(
            name="HeaderToDescInternal",
            parent=to_style_desc,
            fontSize=to_style_desc.fontSize - 1.5,
            leading=to_style_desc.leading - 1,
            wordWrap="CJK",
            splitLongWords=0,
        )
        header_to_right_style_desc_heading_internal = ParagraphStyle(
            name="HeaderToRightDescHeadingInternal",
            parent=to_right_style_desc_heading,
            fontSize=to_right_style_desc_heading.fontSize - 0.5,
            leading=to_right_style_desc_heading.leading - 0.5,
            # numeric headers are short; keep them on one line
            wordWrap="NOBREAK",
            splitLongWords=0,
        )
        # Cells where data must NEVER break across lines (dates, key text columns)
        no_break_date_style = ParagraphStyle(
            name="NoBreakDateInternal",
            parent=center_style_desc,
            wordWrap="NOBREAK",
            splitLongWords=0,
        )
        no_break_text_style = ParagraphStyle(
            name="NoBreakTextInternal",
            parent=to_style_desc,
            wordWrap="NOBREAK",
            splitLongWords=0,
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
        # Add internal-only columns for internal report (exclude truck_booking_rate)
        additional_fields = [
            "total_paid_truck_onwer",
            "advance_paid",
            "panding_amount",
            "net_profit",
        ]
        fields = fields + additional_fields if fields else additional_fields
        # Use 12 rows per page for internal report as well, to keep all reports consistent
        chunk_size = 12

        # --- Build table for a page ---
        def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None, start_index=0):
            """
            Build one page of the internal report table.
            Layout philosophy:
            - Reuse client report styling so headers and data never look broken.
            - Treat all money/amount columns as right‑aligned with fixed decimals.
            - Keep key text columns on a single line using non‑breaking spaces.
            """
            # Header row with readable, compact labels
            header_row = []
            dc_field_label = (
                contract.dc_field
                if contract.dc_field and contract.dc_field not in [None, "None", "null", ""]
                else "Challan No"
            )

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
                    header_text = "GC No"
                elif f == "luggage":
                    header_text = "Lugg"
                elif f == "unloading_charge_1":
                    header_text = "Unld1"
                elif f == "unloading_charge_2":
                    header_text = "Unld2"
                elif f == "loading_charge":
                    header_text = "Load"
                elif f == "total_paid_truck_onwer":
                    header_text = "Total Paid Owner"
                elif f == "advance_paid":
                    header_text = "Adv<br/>Paid"
                elif f == "panding_amount":
                    header_text = "Pending<br/>Amt"
                elif f == "net_profit":
                    header_text = "Net<br/>Profit"
                else:
                    header_text = f.replace("_", " ").title()
                header_row.append(header_text)
            data = [header_row]

            numeric_fields = [
                "weight",
                "km",
                "rate",
                "luggage",
                "unloading_charge_1",
                "amount",
                "loading_charge",
                "totalfreight",
                "unloading_charge_2",
                "total_paid_truck_onwer",
                "advance_paid",
                "panding_amount",
                "net_profit",
            ]
            # Center some small identifier columns
            center_fields = ["sr_no", "gc_note"]

            # Numeric helpers (match client behaviour: money/qty → 2 decimals)
            def _money(val):
                try:
                    if val in (None, "", "None", "null", "NULL", "-"):
                        return "0.00"
                    return f"{float(val):.2f}"
                except Exception:
                    return "0.00"

            def _num2(val):
                try:
                    if val in (None, "", "None", "null", "NULL", "-"):
                        return "0.00"
                    return f"{float(val):.2f}"
                except Exception:
                    return "0.00"

            # Initialize page totals
            total_freight_sum = (
                total_unloading_sum_1
            ) = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = total_rate = total_km = 0
            total_paid_truck_owner = total_advance_paid = total_panding_amount = total_net_profit = 0

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
                total_paid_truck_owner += float(d.total_paid_truck_onwer or 0)
                total_advance_paid += float(d.advance_paid or 0)
                total_panding_amount += float(d.panding_amount or 0)
                total_net_profit += float(d.net_profit or 0)

                row = []
                for field in fields:
                    if field == "sr_no":
                        row.append(idx)
                    elif field in ("depature_date", "dep_date"):
                        # Use non‑breaking hyphens so the date never splits across lines
                        row.append(d.dep_date.strftime("%d\u2011%m\u2011%Y") if d.dep_date else "")
                    elif field == "dc_field" or field == "None":
                        row.append(d.challan_no)
                    elif field in ("luggage", "totalfreight"):
                        # per‑row freight/luggage – 2 decimals
                        row.append(_money(d.totalfreight))
                    elif field in ("product_name", "product"):
                        row.append(d.product_name)
                    elif field == "amount":
                        # per‑row total amount – 2 decimals
                        row.append(_money(total_amount))
                    elif field == "gc_note":
                        row.append(d.gc_note_no)
                    elif field == "weight":
                        row.append(_num2(d.weight))
                    elif field == "rate":
                        row.append(_num2(d.rate))
                    elif field == "km":
                        row.append(_num2(d.km))
                    elif field == "total_paid_truck_onwer":
                        row.append(_money(d.total_paid_truck_onwer))
                    elif field == "advance_paid":
                        row.append(_money(d.advance_paid))
                    elif field == "panding_amount":
                        row.append(_money(d.panding_amount))
                    elif field == "net_profit":
                        row.append(_money(d.net_profit))
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
                total_weight = (
                    total_freight_sum
                ) = total_unloading_sum_1 = total_unloading_sum_2 = total_loading_sum = total_amount_sum = total_rate = total_km = 0
                total_paid_truck_owner = total_advance_paid = total_panding_amount = total_net_profit = 0

                for d in dispatches_to_sum:
                    total_amount = (
                        float(d.totalfreight or 0)
                        + float(d.unloading_charge_1 or 0)
                        + float(d.unloading_charge_2 or 0)
                        + float(d.loading_charge or 0)
                    )
                    total_freight_sum += float(d.totalfreight or 0)
                    total_unloading_sum_1 += float(d.unloading_charge_1 or 0)
                    total_unloading_sum_2 += float(d.unloading_charge_2 or 0)
                    total_loading_sum += float(d.loading_charge or 0)
                    total_amount_sum += total_amount
                    total_weight += float(d.weight or 0)
                    total_rate += float(d.rate or 0)
                    total_km += float(d.km or 0)

                    # Additional fields totals
                    total_paid_truck_owner += float(d.total_paid_truck_onwer or 0)
                    total_advance_paid += float(d.advance_paid or 0)
                    total_panding_amount += float(d.panding_amount or 0)
                    total_net_profit += float(d.net_profit or 0)

                for i, field in enumerate(fields):
                    if field == "weight":
                        # Show total weight (MT) with 2 decimals
                        total_row.append(_num2(total_weight))
                    elif field in ("km", "rate"):
                        # No totals for km and rate
                        total_row.append("")
                    elif field in ("depature_date", "dep_date"):
                        total_row.append("")  # No total for date
                    elif field in ("dc_field", "challan_no"):
                        total_row.append("")  # No total for challan no
                    elif field in ("luggage", "totalfreight"):
                        total_row.append(_money(total_freight_sum))
                    elif field == "unloading_charge_1":
                        total_row.append(_money(total_unloading_sum_1))
                    elif field == "unloading_charge_2":
                        total_row.append(_money(total_unloading_sum_2))
                    elif field == "loading_charge":
                        total_row.append(_money(total_loading_sum))
                    elif field == "amount":
                        total_row.append(_money(total_amount_sum))
                    elif field == "total_paid_truck_onwer":
                        total_row.append(_money(total_paid_truck_owner))
                    elif field == "advance_paid":
                        total_row.append(_money(total_advance_paid))
                    elif field == "panding_amount":
                        total_row.append(_money(total_panding_amount))
                    elif field == "net_profit":
                        total_row.append(_money(total_net_profit))
                    else:
                        total_row.append("")
                total_row[0] = "TOTAL"
                data.append(total_row)

            # Column widths – mirror client report philosophy, with extra room for
            # internal numeric columns so headers & data stay on one line.
            special_widths = {
                # extra space between Sr / Date / Truck so they don't feel glued together
                "Sr No": 12 * mm,
                "Dep Date": 22 * mm,
                dc_field_label: 20 * mm,
                "Truck No": 20 * mm,
                "Party Name": 24 * mm,
                "Product": 18 * mm,
                "Product Name": 18 * mm,
                "GC Note": 11 * mm,
                "Gc Note": 11 * mm,
                "Weight": 11 * mm,
                "Km": 9 * mm,
                "Rate": 11 * mm,
                "Lugg": 12 * mm,
                "Luggage": 12 * mm,
                "Unld1": 13 * mm,
                "Unld2": 13 * mm,
                "Unload Chg 1": 13 * mm,
                "Unload Chg 2": 13 * mm,
                "Load": 12 * mm,
                "Loading Chg": 12 * mm,
                "Total Paid Owner": 17 * mm,
                "Adv Paid": 13 * mm,
                "Pending Amt": 15 * mm,
                "Net Profit": 13 * mm,
                "District": 18 * mm,
                "Destination": 22 * mm,
                "Taluka": 14 * mm,
            }

            table_width = 288 * mm
            headers = data[0]

            col_widths = []
            for col_name in headers:
                width = special_widths.get(col_name)
                if width is None:
                    # Default width for unknown columns
                    width = 14 * mm
                col_widths.append(width)

            # Scale widths if sum doesn't match table width
            fixed_total = sum(col_widths)
            if fixed_total > 0:
                scale_factor = table_width / fixed_total
                col_widths = [w * scale_factor for w in col_widths]

            # Format cells
            for i, row in enumerate(data):
                for j, cell in enumerate(row):
                    field_name = fields[j]
                    if i == 0:  # header
                        # For internal header row, allow normal spaces / <br/> so
                        # long labels can wrap inside their own cells instead of
                        # visually overwriting neighbouring columns.
                        cell_text = str(cell)
                        style = (
                            header_to_right_style_desc_heading_internal
                            if field_name in numeric_fields
                            else header_center_style_desc_internal
                            if field_name in center_fields
                            else header_to_style_desc_internal
                        )
                        row[j] = Paragraph(f"<b>{cell_text}</b>", style)
                    elif add_total and i == len(data) - 1:  # total/grand total row
                        row[j] = Paragraph(str(cell), total_style)
                    else:
                        # Force no‑wrap for dates and key text fields so data never splits
                        if field_name in ("depature_date", "dep_date"):
                            style = no_break_date_style
                        elif field_name in (
                            "district",
                            "destination",
                            "taluka",
                            "party_name",
                            "product_name",
                            "product",
                        ):
                            style = no_break_text_style
                        else:
                            style = (
                                to_right_style_desc
                                if field_name in numeric_fields
                                else center_style_desc
                                if field_name in center_fields
                                else to_style_desc
                            )
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
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            elements.append(Spacer(1,2))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            elements.append(Spacer(1,2))
            add_total_row = contract.rate_type == "Distric-Wise"
            
            # Build table only (no Verified / Recommended / For footer as per latest requirement)
            table = build_table_page(
                dispatch_chunk,
                add_total_row=add_total_row,
                is_last_page=is_last_page,
                all_dispatches=dispatches,
                start_index=i,
            )
            elements.append(table)

        # --- Build PDF ---
        try:
            doc.build(elements)
            buffer.seek(0)
            filename = f"{contract.company_name}-Dispacth-Report.pdf"

            # Match client report behaviour:
            # preview inline by default, download only when ?download=1 or hidden input is sent
            download_flag = request.POST.get("download") or request.GET.get("download")
            response = FileResponse(
                buffer,
                as_attachment=bool(download_flag),
                filename=filename,
                content_type="application/pdf",
            )
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