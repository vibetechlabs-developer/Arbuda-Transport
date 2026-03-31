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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle ,PageBreak , HRFlowable, KeepTogether
from reportlab.lib.units import mm
from operator import attrgetter
import math
import re
from itertools import groupby
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from erp.utils.financial_year import get_current_financial_year, get_financial_year_start_end
from django.db.models import Q
from reportlab.platypus import KeepTogether


def _safe_filename_part(value: object) -> str:
    """
    Make a value safe for use in a filename across OSes (Windows in particular).
    Keeps alphanumerics, dash, underscore, and dot; converts other runs to '-'
    and trims leading/trailing separators.
    """
    s = str(value or "").strip()
    # Replace slashes first (common in bill numbers like "GJ-07/059")
    s = s.replace("/", "-").replace("\\", "-")
    # Collapse any remaining unsafe characters
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-. _")
    return s or "NA"


def _invoice_pdf_filename(*, company_name: str, contract_no: str, bill_no: str, invoice_id: int | None = None) -> str:
    """
    Generate a stable, unique-ish filename for an invoice PDF.

    We include contract_no because Bill_no can repeat across different contracts,
    which otherwise causes downloaded files to overwrite on the user's machine.
    """
    parts = [
        _safe_filename_part(company_name),
        _safe_filename_part(contract_no),
        _safe_filename_part(bill_no),
    ]
    if invoice_id is not None:
        parts.append(str(invoice_id))
    return "_".join([p for p in parts if p]) + ".pdf"


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
    total_option = request.POST.get("total_option", "every_page")  # Default to every_page
    
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
                # GC Note date should match the dispatch (dep_date), not the invoice bill_date.
                gc_date=(d.dep_date or bill_date),
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
    # Optimized margins for full-page utilization while maintaining professional appearance.
    # Use the same margins as the download view so the preview and download PDFs
    # paginate identically (header + 12 rows + TOTAL + footer on a single page).
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        # Tighter side/top margins so 12 rows + TOTAL + signatures reliably fit on one page
        rightMargin=6 * mm,
        leftMargin=6 * mm,
        topMargin=6 * mm,
        # Match download_generate_invoice_pdf: smaller bottom margin prevents
        # ReportLab from pushing the table + footer to a second (mostly blank) page.
        bottomMargin=6 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []
    
    # Calculate available width for full-page utilization
    available_width = landscape(A4)[0] - doc.leftMargin - doc.rightMargin

    # --- Styles ---
    # Typography tuned so header + 12 rows + TOTAL + signatures fit on a single landscape A4 page
    # Centered style for headings like "PARTICULARS" – no extra vertical spacing
    center_style = ParagraphStyle(
        name="Center",
        fontName="Helvetica",
        fontSize=12,
        alignment=1,
        leading=12,
        spaceBefore=0,
        spaceAfter=0,
    )
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=10, alignment=1, leading=12)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=16, alignment=1, leading=18)
    # Slightly larger font for bill details on the right so they are easier to read.
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=10, alignment=0, leading=12)
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=11, alignment=2, leading=13)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=10, alignment=2, leading=12)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=9, alignment=0, leading=10)
    # Uniform header style for all column names - slightly smaller so long labels fit in one line
    to_right_style_desc_heading = ParagraphStyle(
        name="ToRightDesc",
        fontName="Helvetica-Bold",
        fontSize=9,
        alignment=1,
        leading=11,
    )
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=10, alignment=2, leading=13)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='16'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Tax Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[available_width])
    header_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 2), (-1, 2), 1.0, colors.black),
                ("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.black),
                # Slightly tighter padding so the header block consumes less height.
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    # --- Invoice footer helper ---
    # def build_footer_block():
    #     footer_elements = []
        
    #     # Decide footer "For" company name – prefer explicit footer name,
    #     # else fall back to logged-in main company profile name.
    #     footer_name = (
    #         getattr(contract, "footer_company_name", None)
    #         or request.session['company_info']['company_name']
    #     )

    #     # Build left side content: Verified By and Recommended By on same line
    #     left_items = []
    #     if getattr(contract, "show_verified_by", False):
    #         left_items.append(Paragraph("Verified By", to_style))
    #     if getattr(contract, "show_recommended_by", False):
    #         left_items.append(Paragraph("Recommended By", to_style))
        
    #     # Create nested table for left side to place items side by side
    #     if left_items:
    #         left_table_data = [left_items]
    #         left_table = Table(left_table_data, colWidths=[available_width * 0.2] * len(left_items))
    #         left_table.setStyle(TableStyle([
    #             ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    #             ("VALIGN", (0, 0), (-1, -1), "TOP"),
    #             ("LEFTPADDING", (0, 0), (-1, -1), 0),
    #             ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    #             ("TOPPADDING", (0, 0), (-1, -1), 0),
    #             ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    #         ]))
    #         left_label = left_table
    #     else:
    #         left_label = Paragraph("", to_style)
        
    #     # Right side: Company name always on the right
    #     right_label = Paragraph(f"For, {footer_name}", to_right_style)

    #     # Create signature rows - need to match the nested table structure
    #     if left_items:
    #         left_sig_items = [Paragraph("__________________", to_style) for _ in left_items]
    #         left_sig_table = Table([left_sig_items], colWidths=[available_width * 0.2] * len(left_items))
    #         left_sig_table.setStyle(TableStyle([
    #             ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    #             ("VALIGN", (0, 0), (-1, -1), "TOP"),
    #             ("LEFTPADDING", (0, 0), (-1, -1), 0),
    #             ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    #             ("TOPPADDING", (0, 0), (-1, -1), 0),
    #             ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    #         ]))
    #         left_signature = left_sig_table
    #     else:
    #         left_signature = Paragraph("", to_style)
    #     right_signature = Paragraph("__________________", to_right_style)

    #     # Always use 50/50 split to keep layout consistent
    #     # Left side always reserved for Verified By/Recommended By (even if empty)
    #     # Right side always for company name
    #     left_width = available_width * 0.5
    #     right_width = available_width * 0.5

    #     # Create table with left and right columns
    #     footer_data = [
    #         [left_label, right_label],  # Labels row
    #         [left_signature, right_signature],  # Signatures row
    #     ]

    #     # Do not allow the footer table to split between rows across pages
    #     footer_table = Table(footer_data, colWidths=[left_width, right_width], splitByRow=0)
    #     footer_table.setStyle(
    #         TableStyle(
    #             [
    #                 ("ALIGN", (0, 0), (0, -1), "LEFT"),  # Left column left-aligned
    #                 ("ALIGN", (1, 0), (1, -1), "RIGHT"),  # Right column right-aligned
    #                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
    #                 # Very tight vertical padding so labels and lines stay close
    #                 ("TOPPADDING", (0, 0), (-1, 0), 2),
    #                 ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
    #                 ("TOPPADDING", (0, 1), (-1, -1), 1),
    #                 ("BOTTOMPADDING", (0, 1), (-1, -1), 1),
    #             ]
    #         )
    #     )
    #     # Keep the entire footer block (labels + signatures) together
    #     footer_elements.append(KeepTogether(footer_table))
    #     return footer_elements

    def build_footer_block():
        """
        Common footer used for invoice *creation* PDF:
        exactly three equal sections:
            - Verified By
            - Recommended By
            - For, <Company>
        with signature lines directly underneath, matching
        the visual from the sample invoice.
        """
        footer_elements = []

        footer_name = (
            getattr(contract, "footer_company_name", None)
            or request.session['company_info']['company_name']
        )

        # Labels
        verified_label = (
            Paragraph("Verified By", to_style)
            if getattr(contract, "show_verified_by", False)
            else Paragraph("", to_style)
        )
        recommended_label = (
            Paragraph("Recommended By", to_style)
            if getattr(contract, "show_recommended_by", False)
            else Paragraph("", to_style)
        )
        company_label = Paragraph(f"For, {footer_name}", to_style)

        # Signature lines (same width visually as in design)
        sign_line = "__________________"
        verified_sign = (
            Paragraph(sign_line, to_style)
            if getattr(contract, "show_verified_by", False)
            else Paragraph("", to_style)
        )
        recommended_sign = (
            Paragraph(sign_line, to_style)
            if getattr(contract, "show_recommended_by", False)
            else Paragraph("", to_style)
        )
        company_sign = Paragraph(sign_line, to_style)

        # 3 equal columns so spacing matches design precisely
        footer_data = [
            [verified_label, recommended_label, company_label],
            [verified_sign, recommended_sign, company_sign],
        ]

        # Use a narrower total width than the full printable area so that
        # left and right margins have some blank space (important for punching).
        # Tune this factor (currently 0.85) if you want more/less side space.
        footer_total_width = available_width * 0.85
        equal_width = footer_total_width / 3.0
        footer_table = Table(
            footer_data,
            colWidths=[equal_width, equal_width, equal_width],
            splitByRow=0,
            # Slightly right‑biased so the visual margin on the right side is smaller
            # (more space on the left, less on the right, matching your requirement).
            hAlign="RIGHT",
        )

        footer_table.setStyle(
            TableStyle(
                [
                    # Center all three sections horizontally, like the sample
                    ("ALIGN", (0, 0), (2, -1), "CENTER"),
                    ("VALIGN", (0, 0), (2, -1), "TOP"),

                    # Tight padding so labels and lines stay visually grouped
                    ("LEFTPADDING", (0, 0), (2, -1), 0),
                    ("RIGHTPADDING", (0, 0), (2, -1), 0),

                    ("TOPPADDING", (0, 0), (2, 0), 10),   # space above labels
                    ("BOTTOMPADDING", (0, 0), (2, 0), 3),
                    ("TOPPADDING", (0, 1), (2, 1), 3),    # space between label and line
                    ("BOTTOMPADDING", (0, 1), (2, 1), 12),
                ]
            )
        )

        footer_elements.append(KeepTogether(footer_table))
        return footer_elements
            
    fields = contract.invoice_fields
    # Target 12 rows per page so header + 12 rows + TOTAL + signatures fit on one page
    # (UI is locked to 12 so this stays consistent)
    chunk_size = 12
    # If total dispatches are fewer than 12, keep them on a single page
    if len(dispatches) < 12:
        chunk_size = len(dispatches) or 1

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None, start_index=1):
        def _sanitize_cell_text(val: object) -> str:
            """
            ReportLab Tables in this file use *fixed row heights* to guarantee a stable
            "N rows per page" layout. If any cell contains explicit line breaks
            (e.g. user data with '\\n' or '<br>'), ReportLab will render multiple lines
            inside the fixed-height row and the extra line visually "overwrites" the
            next row (what users report as 'override/breaking').
            This helper forces single-line cell text by removing hard line breaks and
            collapsing whitespace.
            """
            if val in (None, "None", "null", "NULL"):
                return ""
            s = str(val)
            # Normalise common HTML line breaks into spaces
            s = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", s)
            # Normalise newline chars into spaces
            s = s.replace("\r", " ").replace("\n", " ")
            # Collapse runs of whitespace
            s = re.sub(r"\s{2,}", " ", s).strip()
            return s

        # Use exactly the fields selected on the contract for the invoice.
        # Do NOT auto-hide loading / unloading columns even if all values are 0,
        # because the user expects the column to appear with 0.00 when they have
        # enabled that field while creating the contract.
        active_fields = list(fields)

        # Always keep main_party and sub_party (if enabled in invoice_fields)
        # and reposition them so they appear directly after dc_field.
        main_party_in_fields = "main_party" in active_fields
        sub_party_in_fields = "sub_party" in active_fields
        if main_party_in_fields or sub_party_in_fields:
            try:
                # Remove from current positions
                active_fields = [
                    f for f in active_fields if f not in ("main_party", "sub_party")
                ]
                dc_field_idx = active_fields.index("dc_field")
                insert_idx = dc_field_idx + 1
                if main_party_in_fields:
                    active_fields.insert(insert_idx, "main_party")
                    insert_idx += 1
                if sub_party_in_fields:
                    active_fields.insert(insert_idx, "sub_party")
            except ValueError:
                # If dc_field is not present, keep original order
                pass

        # Header row (short, standard labels so nothing breaks into 2 lines)
        # Sanitize dc_field label so very long custom labels (e.g. "Shipment Number") don't overflow.
        dc_raw = getattr(contract, "dc_field", None)
        if dc_raw in [None, "None", "null", ""]:
            dc_label = "Challan\u00A0No"
        else:
            dc_label = str(dc_raw).strip()
            # If label is long, prefer the first word (e.g. "Shipment") to keep header compact.
            if len(dc_label) > 10:
                dc_label = dc_label.split()[0]
            dc_label = dc_label.replace(" ", "\u00A0")
        label_map = {
            "sr_no": "Sr\u00A0No",  # Non-breaking space
            "depature_date": "Dep\u00A0Date",  # Non-breaking space
            "dep_date": "Dep\u00A0Date",  # Non-breaking space
            "dc_field": dc_label,
            "truck_no": "Truck\u00A0No",  # Non-breaking space
            "party_name": "Party\u00A0Name",  # Non-breaking space
            "product_name": "Product",
            "destination": "Dest.",  # Short label to avoid wrapping
            "district": "Dist.",
            "taluka": "Tal.",
            "unloading_charge_1": "Unload\u00A01",  # Non-breaking space to prevent breaking
            "unloading_charge_2": "Unload\u00A02",  # Non-breaking space to prevent breaking
            "loading_charge": "Loading",
            "totalfreight": "Freight",
            "luggage": "Lugg.",
            "gc_note": "GC\u00A0Note",  # Non-breaking space
            "main_party": "Main\u00A0Party",  # Non-breaking space
            "sub_party": "Sub\u00A0Party",  # Non-breaking space
        }
        data = [[label_map.get(f, f.replace("_", " ").title()) for f in active_fields]]

        # Treat only true amount/quantity columns as numeric-right aligned.
        # Keep KM, shipment (dc_field) and truck no centered for better readability
        # and to avoid visual mixing of values under adjacent headers.
        numeric_fields = [
            "weight",
            "rate",
            "luggage",
            "unloading_charge_1",
            "amount",
            "loading_charge",
            "totalfreight",
            "unloading_charge_2",
        ]
        center_fields = ["sr_no", "gc_note", "km", "dc_field", "truck_no"]

        # Use the same compact typography as the download invoice PDF so that
        # header + 12 rows + TOTAL + footer fit identically on a single page.
        compact_fs = 8.0
        compact_leading = 9

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
            # Prevent mid-word breaks like "AHMEDABA" + "D" in tight columns
            splitLongWords=0,
            wordWrap="NOBREAK",  # keep cell text on a single line
        )
        district_style_local = ParagraphStyle(
            name="DistrictCell",
            parent=to_style_desc_local,
            alignment=1,  # center short district names
            splitLongWords=0,
            wordWrap="NOBREAK",  # keep long district names on a single line
        )
        # Uniform header style for all column names – same sizing as download PDF.
        header_style_uniform = ParagraphStyle(
            name="HeaderUniform",
            parent=to_right_style_desc_heading,
            fontSize=8.5,
            leading=10,
            alignment=1,  # Center all headers
            splitLongWords=0,
        )
        to_right_style_desc_local = ParagraphStyle(
            name="ToRightDescLocal",
            parent=to_right_style_desc,
            fontSize=compact_fs or to_right_style_desc.fontSize,
            leading=compact_leading or to_right_style_desc.leading,
            splitLongWords=0,  # don't split long numbers
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
            splitLongWords=0,
        )
        total_label_style_local = ParagraphStyle(
            name="TotalLabelStyleLocal",
            parent=to_style_desc_local,
            fontName="Helvetica-Bold",
            alignment=0,  # LEFT
            wordWrap="NOBREAK",
        )

        # Initialize page totals
        total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = 0

        def _num(val, decimals=3):
            """
            Safe numeric formatter for PDF cells.
            Ensures missing/blank numeric values don't render as 'None' and don't break table structure.
            """
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return f"{0:.{decimals}f}"
                return f"{float(val):.{decimals}f}"
            except Exception:
                return f"{0:.{decimals}f}"

        def _num_exact(val):
            """Format numeric values without forcing a fixed number of decimals."""
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0"
                s = f"{float(val):.6f}".rstrip('0').rstrip('.')
                return s if s else "0"
            except Exception:
                return "0"

        def _int(val):
            """Format numeric values as integer (no decimal point)."""
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0"
                return str(int(float(val)))
            except Exception:
                return "0"

        def _money(val):
            """
            Format currency (Rs.) values with exactly 2 decimal places.
            """
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0.00"
                return f"{float(val):.2f}"
            except Exception:
                return "0.00"

        # Build rows
        for idx, d in enumerate(dispatch_subset, start=start_index):
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
            for field in active_fields:
                if field == "sr_no":
                    row.append(idx)
                elif field in ("depature_date", "dep_date"):
                    row.append(d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "")
                elif field == "dc_field" or field == "None":
                    row.append(d.challan_no)
                elif field in ("luggage", "totalfreight"):
                    # keep invoice structure consistent even when freight is missing; show Rs with 2 decimals
                    row.append(_money(d.totalfreight))
                elif field in ("product_name", "product"):
                    row.append(d.product_name)
                elif field == "amount":
                    # Total amount (Rs.) per row – always 2 decimals
                    row.append(_money(total_amount))
                elif field == "gc_note":
                    row.append(d.gc_note_no)
                elif field == "main_party":
                    row.append(d.main_party or "")
                elif field == "sub_party":
                    row.append(d.sub_party or "")
                elif field in ("unloading_charge_1", "unloading_charge_2", "loading_charge"):
                    # Loading / unloading (Rs.) – always 2 decimals
                    row.append(_money(getattr(d, field, None)))
                elif field in ("weight",):
                    row.append(_num(getattr(d, field, None), decimals=3))
                elif field == "km":
                    # Show km as integer (no decimal point)
                    row.append(_int(getattr(d, field, None)))
                elif field == "rate":
                    # Keep rate with 2 fixed decimals
                    row.append(_num(getattr(d, field, None), decimals=2))
                else:
                    # Avoid 'None' showing in PDF
                    v = getattr(d, field, "")
                    row.append("" if v in (None, "None", "null", "NULL") else v)
            data.append(row)

        # Determine total row logic
        # Standard invoice pagination: 12 rows per page, and show a per-page TOTAL row on every page.
        add_total = bool(add_total_row)
        # If it's the last page and we're showing totals, use all_dispatches for grand total
        if is_last_page and add_total and all_dispatches is not None:
            dispatches_to_sum = all_dispatches
        else:
            dispatches_to_sum = dispatch_subset
        total_row = []

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

            for i, field in enumerate(active_fields):
                if field == "weight":
                    # Show total weight (MT) with 3 decimals
                    total_row.append(f"{total_weight:.3f}")
                elif field in ("km", "rate"):
                    # No totals for km and rate
                    total_row.append("")
                elif field in ("luggage", "totalfreight"):
                    # Freight total (Rs.) – 2 decimals
                    total_row.append(_money(total_freight_sum))
                elif field == "unloading_charge_1":
                    total_row.append(_money(total_unloading_sum_1))
                elif field == "unloading_charge_2":
                    total_row.append(_money(total_unloading_sum_2))
                elif field == "loading_charge":
                    total_row.append(_money(total_loading_sum))
                elif field == "amount":
                    total_row.append(_money(total_amount_sum))
                else:
                    total_row.append("")
            # Total label rendered during cell formatting
            data.append(total_row)

        # Use full available width for table - distribute columns proportionally
        table_width = available_width
        headers = data[0]
        num_cols = len(headers)

        # Base column widths - will be scaled to fill full width
        # Keys MUST match the actual header text (from label_map) so widths apply correctly.
        # Use the same dc_label we computed for header so the Shipment/Challan column gets an appropriate width.
        base_widths = {
            "Sr\u00A0No": 10,  # Match label_map with non-breaking space
            dc_label: 26,  # Wider so "Shipment" or custom labels fit on one line
            "Truck\u00A0No": 20,
            "Party\u00A0Name": 28,  # Wider to keep on one line
            "Product": 16,
            "GC\u00A0Note": 20,  # Wider so header text stays on a single line
            # Give numeric columns a bit more width so totals never wrap (e.g. 1698.000)
            "Weight": 16,
            "Km": 13,
            "Rate": 16,
            "Lugg.": 22,
            "Unload\u00A01": 18,  # Match label_map with non-breaking space
            "Unload\u00A02": 18,  # Match label_map with non-breaking space
            "Loading": 14,
            "Freight": 14,
            "Amount": 20,
            "Dep\u00A0Date": 20,  # Match label_map with non-breaking space
            "Dest.": 24,
            "Dist.": 26,  # wider so "AHMEDABAD" fits on one line
            "Tal.": 16,
            "Main\u00A0Party": 20,  # Match label_map with non-breaking space
            "Sub\u00A0Party": 20,  # Match label_map with non-breaking space
        }

        # Calculate proportional widths
        col_widths = []
        total_base = 0
        for col_name in headers:
            base = base_widths.get(col_name, 10)  # Default base width
            col_widths.append(base)
            total_base += base

        # Scale all columns to fill full table width
        if total_base > 0:
            scale_factor = table_width / total_base
            col_widths = [w * scale_factor for w in col_widths]
        else:
            # Fallback: equal distribution
            col_widths = [table_width / num_cols] * num_cols

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = active_fields[j]
                if i == 0:  # header - use uniform style for all column names, prevent wrapping
                    # Use non-breaking spaces and prevent wrapping
                    cell_text = str(cell).replace(' ', '\u00A0')  # Replace spaces with non-breaking spaces
                    row[j] = Paragraph(f"<b>{cell_text}</b>", header_style_uniform)
                elif add_total and i == len(data) - 1:  # total row
                    if j == 0:
                        row[j] = Paragraph("TOTAL", total_label_style_local)
                    else:
                        row[j] = Paragraph(str(cell), total_style_local)
                else:
                    if field_name == "district":
                        style = district_style_local
                    else:
                        style = to_right_style_desc_local if field_name in numeric_fields else center_style_desc_local if field_name in center_fields else to_style_desc_local
                    row[j] = Paragraph(str(cell), style)

        # Let ReportLab auto-size row heights so rows with large text (e.g. long
        # party names) grow vertically instead of visually overriding the next row.
        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles - keep fully in sync with download_generate_invoice_pdf so
        # that both PDFs have identical visual layout (padding, borders, etc.).
        styles = [
            # Header styling
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            # Ultra-tight paddings so table visually touches "PARTICULARS"
            ("LEFTPADDING", (0,0), (-1,-1), 0.5),
            ("RIGHTPADDING", (0,0), (-1,-1), 0.5),
            ("TOPPADDING", (0,0), (-1,0), 0),   # Header padding
            ("BOTTOMPADDING", (0,0), (-1,0), 0),
            ("TOPPADDING", (0,1), (-1,-2), 0),  # Data rows padding
            ("BOTTOMPADDING", (0,1), (-1,-2), 0),
            # Clean borders - top and bottom of header
            ("LINEABOVE", (0,0), (-1,0), 1.0, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 1.0, colors.black),
            # Grid lines for all cells - simple and standard
            ("GRID", (0,0), (-1,-1), 0.5, colors.black),
            # Allow wrapping inside cells so that long text breaks into multiple
            # lines within the same row (together with auto row heights above,
            # this keeps each logical row visually separate).
            ("WORDWRAP", (0,0), (-1,-1), "CJK"),
        ]
        # No zebra striping - clean and simple
        if add_total:
            # Span the TOTAL label across the non-numeric columns before the first numeric total
            numeric_total_fields = set(numeric_fields) | {"amount"}
            first_total_idx = None
            for idx, f in enumerate(active_fields):
                if f in numeric_total_fields:
                    first_total_idx = idx
                    break
            span_end = min((first_total_idx - 1) if first_total_idx is not None else 0, num_cols - 1)
            if span_end >= 1:
                styles.append(("SPAN", (0, -1), (span_end, -1)))
                styles.append(("ALIGN", (0, -1), (span_end, -1), "LEFT"))

            styles += [
                ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                # Slightly larger total-row padding so TOTAL stands out but still fits 12 rows
                ("TOPPADDING", (0,-1), (-1,-1), 3),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 3),
                ("LINEABOVE", (0,-1), (-1,-1), 1.0, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table

    # --- Split dispatches per page ---

    if contract.rate_type == "Distric-Wise":
        # Sort dispatches by district, then by challan_no (ascending) within each district
        page_no = 1

        def sort_key(d):
            def get_numeric_value(challan_no):
                if not challan_no:
                    return 0
                num_match = re.search(r"\d+", str(challan_no))
                return int(num_match.group(0)) if num_match else 0

            # Positive for ascending challan order within each district
            return (d.district or "", get_numeric_value(d.challan_no))

        dispatches_sorted = sorted(dispatches, key=sort_key)

        # Group by district
        for district, district_dispatches_iter in groupby(
            dispatches_sorted, key=attrgetter("district")
        ):
            district_dispatches = list(district_dispatches_iter)

            # Paginate within the district
            for i in range(0, len(district_dispatches), chunk_size):
                dispatch_chunk = district_dispatches[i : i + chunk_size]
                if page_no > 1:
                    elements.append(PageBreak())

                # Header
                elements.append(header_table)
                elements.append(Spacer(1, 3))  # Minimal spacing for 12 rows per page

                # TO Table with Page number
                to_content = [
                    Paragraph("<b>TO</b>", to_style),
                    Paragraph(f"{contract.c_designation}, ", to_style),
                    Paragraph(f"{contract.company_name},", to_style),
                    Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                    Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                    Paragraph(f"GST NO. : {contract.gst_number}", to_style),
                ]
                # Include RR No. (only when provided) with bill details on every page
                rr_display = request.POST.get("rr_number", "").strip()
                bill_no_content = [
                    Paragraph(f"Bill No : {invoice.Bill_no}", to_right_style),
                    Paragraph(f"Bill Date : {bill_date.strftime('%d-%m-%Y')}", to_right_style),
                ]
                if rr_display:
                    bill_no_content.append(Paragraph(f"RR No : {rr_display}", to_right_style))
                bill_no_content.extend(
                    [
                        Paragraph(f"From : {contract.from_center}", to_right_style),
                        Paragraph(f"District : {district}", to_right_style),
                        Paragraph(f"Page : {page_no} ", to_right_style),
                    ]
                )

                # Calculate widths based on available space
                to_table_width = available_width
                to_table = Table(
                    [[to_content, bill_no_content]],
                    colWidths=[to_table_width * 0.82, to_table_width * 0.18],
                )
                to_table.setStyle(
                    TableStyle(
                        [
                            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("ALIGN", (0, 0), (0, 0), "LEFT"),
                            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                elements.append(to_table)
                elements.append(Spacer(1, 3))
                elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
                elements.append(Spacer(1, 3))

                # Dispatch Table for this page
                # Determine if we should show total based on total_option
                if total_option == "every_page":
                    show_total = True
                else:
                    # For "last_page", this district-wise branch behaves same as standard:
                    # only show total on the last page of this invoice.
                    is_last_page = (i + chunk_size) >= len(dispatches)
                    show_total = is_last_page

                page_block = [
                    build_table_page(
                        dispatch_chunk,
                        add_total_row=show_total,
                        is_last_page=False,
                        all_dispatches=dispatches,
                        start_index=(i + 1),
                    ),
                    # Very small gap between table and footer
                    Spacer(1, 2),
                ]
                page_block.extend(build_footer_block())
                # Do not force table+footer to stay together; this avoids pushing the
                # whole block to a new page and leaving a large blank gap.
                elements.extend(page_block)

                page_no += 1
    else:
        page_no = 1
        total_pages = math.ceil(len(dispatches) / chunk_size)

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i : i + chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            # Reduce vertical gap between header and TO table
            elements.append(Spacer(1, 1))

            # TO Table
            to_content = [
                Paragraph("<b>TO</b>", to_style),
                Paragraph(f"{contract.c_designation}, ", to_style),
                Paragraph(f"{contract.company_name},", to_style),
                Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                Paragraph(f"GST NO. : {contract.gst_number}", to_style),
            ]
            rr_display = request.POST.get("rr_number", "").strip()
            bill_no_content = [
                Paragraph(f"Bill No : {invoice.Bill_no}", to_right_style),
                Paragraph(f"Bill Date : {bill_date.strftime('%d-%m-%Y')}", to_right_style),
            ]
            if rr_display:
                bill_no_content.append(Paragraph(f"RR No : {rr_display}", to_right_style))
            bill_no_content.extend(
                [
                    Paragraph(f"From : {contract.from_center}", to_right_style),
                    Paragraph(f"Page : {page_no} of {total_pages}", to_right_style),
                ]
            )

            # Calculate widths based on available space
            to_table_width = available_width
            to_table = Table(
                [[to_content, bill_no_content]],
                colWidths=[to_table_width * 0.82, to_table_width * 0.18],
            )

            to_table.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ALIGN", (0, 0), (0, 0), "LEFT"),
                        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )

            elements.append(to_table)
            elements.append(Spacer(1, 1))
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            # Keep spacing here minimal so the dispatch table starts higher on the page
            elements.append(Spacer(1, 1))

            # Determine if we should show total based on total_option
            if total_option == "every_page":
                show_total = True
            else:
                show_total = is_last_page  # Only show on last page

            page_block = [
                build_table_page(
                    dispatch_chunk,
                    add_total_row=show_total,
                    is_last_page=is_last_page,
                    all_dispatches=dispatches,
                    start_index=(i + 1),
                ),
                # Smaller spacer between table and footer
                Spacer(1, 2),
            ]
            page_block.extend(build_footer_block())
            # Allow table/footer to split naturally so the table can start
            # immediately after "PARTICULARS" without an artificial page break.
            elements.extend(page_block)

            page_no += 1

    # --- Build PDF (no Verified / Recommended / For footer, as per latest requirement) ---
    doc.build(elements)
    buffer.seek(0)
    filename = _invoice_pdf_filename(
        company_name=contract.company_name,
        contract_no=contract.contract_no,
        bill_no=i_bill_no,
        invoice_id=getattr(invoice, "id", None),
    )

    # For the "preview" flow this view is used for, we always want an inline preview,
    # not a forced download. The explicit download button should call the dedicated
    # download view instead of relying on this one.
    from django.http import HttpResponse

    response = HttpResponse(buffer, content_type="application/pdf")
    # Use inline disposition so browsers open the PDF viewer instead of saving the file.
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response

################################
## END OF GENRATE INOVICE PDF ##
################################

@session_required
def download_generate_invoice_pdf(request):
    if request.method == "POST":     
        contract_id = request.POST.get("contract_id")
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

        # --- Decide which dispatches to include in the PDF ---
        # On the "View & Download Invoice" screen, checkboxes are hidden; in that case,
        # no dispatch_ids are posted and we should include all dispatches attached to the invoice.
        dispatch_ids_raw = request.POST.getlist("dispatch_ids")
        if dispatch_ids_raw:
            try:
                dispatch_ids = [int(i) for i in dispatch_ids_raw]
                dispatches = Dispatch.objects.filter(id__in=dispatch_ids).order_by('dep_date')
            except (TypeError, ValueError):
                # Fallback to all invoice dispatches if anything goes wrong with IDs
                dispatches = invoice.dispatch_list.all().order_by('dep_date')
        else:
            # No explicit selection → use all dispatch rows for this invoice
            dispatches = invoice.dispatch_list.all().order_by('dep_date')

        # Sort by challan_no in ascending order
        dispatches = sort_dispatches_by_challan_asc(dispatches)
   
        bill_date_str = request.POST.get("bill_date")
        bill_date = datetime.strptime(bill_date_str, "%Y-%m-%d").date() if bill_date_str else None
        total_option = request.POST.get("total_option", "every_page")  # Default to every_page
        
    # --- PDF Generation ---
    buffer = BytesIO()
    # Optimized margins for full-page utilization while maintaining professional appearance
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        # Tighter margins so header + 12 rows + TOTAL + signatures fit on one page
        rightMargin=6 * mm,
        leftMargin=6 * mm,
        # Slightly smaller top margin so table block starts higher on the page
        topMargin=4 * mm,
        # Keep a reasonable bottom margin but not too large
        bottomMargin=6 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []
    
    # Calculate available width for full-page utilization
    available_width = landscape(A4)[0] - doc.leftMargin - doc.rightMargin

    # --- Styles ---
    # Typography tuned so header + 12 rows + TOTAL + signatures fit on a single landscape A4 page
    center_style = ParagraphStyle(name="Center", fontName="Helvetica", fontSize=12, alignment=1, leading=14)
    center_style_desc = ParagraphStyle(name="CenterDesc", fontName="Helvetica", fontSize=10, alignment=1, leading=12)
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=16, alignment=1, leading=18)
    to_style = ParagraphStyle(name="To", fontName="Helvetica", fontSize=10, alignment=0, leading=12)
    # Slightly larger font for bill details on the right so they are easier to read.
    to_right_style = ParagraphStyle(name="ToRight", fontName="Helvetica", fontSize=11, alignment=2, leading=13)
    total_style = ParagraphStyle(name="TotalStyle", fontName="Helvetica-Bold", fontSize=10, alignment=2, leading=12)
    to_style_desc = ParagraphStyle(name="ToDesc", fontName="Helvetica", fontSize=9, alignment=0, leading=10)
    # Uniform header style for all column names - slightly smaller so long labels fit in one line
    to_right_style_desc_heading = ParagraphStyle(
        name="ToRightDesc",
        fontName="Helvetica-Bold",
        fontSize=9,
        alignment=1,
        leading=11,
    )
    to_right_style_desc = ParagraphStyle(name="ToRightDesc", fontName="Helvetica", fontSize=10, alignment=2, leading=13)

    # --- Header Table ---
    header_data = [
        [Paragraph(f"<font color='black' size='16'><b>{request.session['company_info']['company_name']}</b></font><br/>{company_profile.address}, {company_profile.city}, {company_profile.state}-{company_profile.pincode}", center_style)],    
        [Paragraph(f"GST : {company.gst_number}, Pan no. : {company_profile.pan_number}", center_style)],
        [Paragraph("<b>Tax Invoice</b>", title_style)],
    ]
    header_table = Table(header_data, colWidths=[available_width])
    header_table.setStyle(TableStyle([
        ('LINEBELOW', (0,2), (-1,2), 1.0, colors.black), 
        ('LINEBELOW', (0,1), (-1,1), 0.8, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    # --- Invoice footer helper ---
    def build_footer_block():
        """
        Common footer used for invoice *download* PDF.
        Layout is kept identical to the create-invoice PDF:
            Verified By | Recommended By | For, <Company>
        with three equal columns and signature lines underneath.
        """
        footer_elements = []

        footer_name = (
            getattr(contract, "footer_company_name", None)
            or request.session['company_info']['company_name']
        )

        # Labels
        verified_label = (
            Paragraph("Verified By", to_style)
            if getattr(contract, "show_verified_by", False)
            else Paragraph("", to_style)
        )
        recommended_label = (
            Paragraph("Recommended By", to_style)
            if getattr(contract, "show_recommended_by", False)
            else Paragraph("", to_style)
        )
        company_label = Paragraph(f"For, {footer_name}", to_style)

        # Signature lines
        sign_line = "__________________"
        verified_sign = (
            Paragraph(sign_line, to_style)
            if getattr(contract, "show_verified_by", False)
            else Paragraph("", to_style)
        )
        recommended_sign = (
            Paragraph(sign_line, to_style)
            if getattr(contract, "show_recommended_by", False)
            else Paragraph("", to_style)
        )
        company_sign = Paragraph(sign_line, to_style)

        footer_data = [
            [verified_label, recommended_label, company_label],
            [verified_sign, recommended_sign, company_sign],
        ]

        # Match the same visual margins as the create-invoice PDF footer
        # (narrower block centered on the page so both sides have equal space)
        footer_total_width = available_width * 0.85
        equal_width = footer_total_width / 3.0
        footer_table = Table(
            footer_data,
            colWidths=[equal_width, equal_width, equal_width],
            splitByRow=0,
            # Keep same right‑biased alignment as create‑invoice PDF
            hAlign="RIGHT",
        )

        footer_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (2, -1), "CENTER"),
                    ("VALIGN", (0, 0), (2, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (2, -1), 0),
                    ("RIGHTPADDING", (0, 0), (2, -1), 0),
                    ("TOPPADDING", (0, 0), (2, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (2, 0), 3),
                    ("TOPPADDING", (0, 1), (2, 1), 3),
                    ("BOTTOMPADDING", (0, 1), (2, 1), 12),
                ]
            )
        )

        footer_elements.append(KeepTogether(footer_table))
        return footer_elements

    fields = contract.invoice_fields
    # Target 12 rows per page so header + 12 rows + TOTAL + signatures fit on one page
    # (UI is locked to 12 so this stays consistent)
    chunk_size = 12
    # If total dispatches are fewer than 12, keep them on a single page
    if len(dispatches) < 12:
        chunk_size = len(dispatches) or 1

    # --- Build table for a page ---
    def build_table_page(dispatch_subset, add_total_row=True, is_last_page=False, all_dispatches=None, start_index=1):

        # Use exactly the fields selected on the contract for the invoice download.
        # Do NOT auto-hide loading / unloading columns even if all values are 0,
        # because the user expects the column to appear with 0.00 when they have
        # enabled that field while creating the contract.
        active_fields = list(fields)

        # Always keep main_party and sub_party (if enabled in invoice_fields)
        # and reposition them so they appear directly after dc_field.
        main_party_in_fields = "main_party" in active_fields
        sub_party_in_fields = "sub_party" in active_fields
        if main_party_in_fields or sub_party_in_fields:
            try:
                # Remove from current positions
                active_fields = [
                    f for f in active_fields if f not in ("main_party", "sub_party")
                ]
                dc_field_idx = active_fields.index("dc_field")
                insert_idx = dc_field_idx + 1
                if main_party_in_fields:
                    active_fields.insert(insert_idx, "main_party")
                    insert_idx += 1
                if sub_party_in_fields:
                    active_fields.insert(insert_idx, "sub_party")
            except ValueError:
                # If dc_field is not present, keep original order
                pass

        # Header row (short, standard labels so nothing breaks into 2 lines)
        # Sanitize dc_field label so very long custom labels (e.g. "Shipment Number") don't overflow.
        dc_raw = getattr(contract, "dc_field", None)
        if dc_raw in [None, "None", "null", ""]:
            dc_label = "Challan\u00A0No"
        else:
            dc_label = str(dc_raw).strip()
            if len(dc_label) > 10:
                dc_label = dc_label.split()[0]
            dc_label = dc_label.replace(" ", "\u00A0")
        label_map = {
            "sr_no": "Sr\u00A0No",  # Non-breaking space
            "depature_date": "Dep\u00A0Date",  # Non-breaking space
            "dep_date": "Dep\u00A0Date",  # Non-breaking space
            "dc_field": dc_label,
            "truck_no": "Truck\u00A0No",  # Non-breaking space
            "party_name": "Party\u00A0Name",  # Non-breaking space
            "product_name": "Product",
            "destination": "Dest.",  # Short label to avoid wrapping
            "district": "Dist.",
            "taluka": "Tal.",
            "unloading_charge_1": "Unload\u00A01",  # Non-breaking space to prevent breaking
            "unloading_charge_2": "Unload\u00A02",  # Non-breaking space to prevent breaking
            "loading_charge": "Loading",
            "totalfreight": "Freight",
            "luggage": "Lugg.",
            "gc_note": "GC\u00A0Note",  # Non-breaking space
            "main_party": "Main\u00A0Party",  # Non-breaking space
            "sub_party": "Sub\u00A0Party",  # Non-breaking space
        }
        data = [[label_map.get(f, f.replace("_", " ").title()) for f in active_fields]]

        # Same alignment rules as invoice creation PDF:
        # numeric amount/quantity columns right aligned,
        # KM, shipment (dc_field) and truck no centered.
        numeric_fields = [
            "weight",
            "rate",
            "luggage",
            "unloading_charge_1",
            "amount",
            "loading_charge",
            "totalfreight",
            "unloading_charge_2",
        ]
        center_fields = ["sr_no", "gc_note", "km", "dc_field", "truck_no"]

        # Fixed compact sizing so header + up to 12 rows + TOTAL + footer
        # reliably fit on a single landscape A4 page without text breaking across lines.
        compact_fs = 8.0
        compact_leading = 9

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
            splitLongWords=0,
            wordWrap="NOBREAK",  # keep cell text on a single line
        )
        district_style_local = ParagraphStyle(
            name="DistrictCellDl",
            parent=to_style_desc_local,
            alignment=1,
            splitLongWords=0,
            wordWrap="NOBREAK",  # keep long district names on a single line
        )
        to_right_style_desc_local = ParagraphStyle(
            name="ToRightDescLocalDl",
            parent=to_right_style_desc,
            fontSize=compact_fs or to_right_style_desc.fontSize,
            leading=compact_leading or to_right_style_desc.leading,
            splitLongWords=0,  # don't split long numbers
        )
        # Uniform header style for all column names.
        header_style_uniform = ParagraphStyle(
            name="HeaderUniformDl",
            parent=to_right_style_desc_heading,
            fontSize=8.5,
            leading=10,
            alignment=1,  # Center all headers
            splitLongWords=0,
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
            splitLongWords=0,
        )
        total_label_style_local = ParagraphStyle(
            name="TotalLabelStyleLocalDl",
            parent=to_style_desc_local,
            fontName="Helvetica-Bold",
            alignment=0,  # LEFT
            wordWrap="NOBREAK",
        )

        def _sanitize_cell_text(val: object) -> str:
            """
            Force single-line text to prevent cell contents from overflowing fixed row heights.
            This avoids the visual 'override/breaking' when values contain '\\n' or '<br>'.
            """
            if val in (None, "None", "null", "NULL"):
                return ""
            s = str(val)
            s = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", s)
            s = s.replace("\r", " ").replace("\n", " ")
            s = re.sub(r"\s{2,}", " ", s).strip()
            return s

        # Initialize page totals
        total_freight_sum = total_unloading_sum_1 = total_loading_sum = total_unloading_sum_2 = total_amount_sum = total_weight = 0

        def _num(val, decimals=3):
            """
            Safe numeric formatter for PDF cells.
            Ensures missing/blank numeric values don't render as 'None' and don't break table structure.
            """
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return f"{0:.{decimals}f}"
                return f"{float(val):.{decimals}f}"
            except Exception:
                return f"{0:.{decimals}f}"

        def _num_exact(val):
            """Format numeric values without forcing a fixed number of decimals."""
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0"
                s = f"{float(val):.6f}".rstrip('0').rstrip('.')
                return s if s else "0"
            except Exception:
                return "0"

        def _int(val):
            """Format numeric values as integer (no decimal point)."""
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0"
                return str(int(float(val)))
            except Exception:
                return "0"

        def _money(val):
            """
            Format currency (Rs.) values with exactly 2 decimal places.
            """
            try:
                if val in (None, "", "None", "null", "NULL", "-"):
                    return "0.00"
                return f"{float(val):.2f}"
            except Exception:
                return "0.00"

        # Build rows
        for idx, d in enumerate(dispatch_subset, start=start_index):
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
            for field in active_fields:
                if field == "sr_no":
                    row.append(idx)
                elif field in ("depature_date", "dep_date"):
                    row.append(d.dep_date.strftime("%d-%m-%Y") if d.dep_date else "")
                elif field == "dc_field" or field == "None":
                    row.append(_sanitize_cell_text(d.challan_no))
                elif field in ("luggage", "totalfreight"):
                    # Freight per row (Rs.) – 2 decimals
                    row.append(_money(d.totalfreight))
                elif field in ("product_name", "product"):
                    row.append(_sanitize_cell_text(d.product_name))
                elif field == "amount":
                    # Total amount (Rs.) per row – 2 decimals
                    row.append(_money(total_amount))
                elif field == "gc_note":
                    row.append(_sanitize_cell_text(d.gc_note_no))
                elif field == "main_party":
                    row.append(_sanitize_cell_text(d.main_party))
                elif field == "sub_party":
                    row.append(_sanitize_cell_text(d.sub_party))
                elif field in ("unloading_charge_1", "unloading_charge_2", "loading_charge"):
                    # Loading / unloading (Rs.) – 2 decimals
                    row.append(_money(getattr(d, field, None)))
                elif field in ("weight",):
                    row.append(_num(getattr(d, field, None), decimals=3))
                elif field == "km":
                    # Show km as integer (no decimal point)
                    row.append(_int(getattr(d, field, None)))
                elif field == "rate":
                    # Keep rate with 2 fixed decimals
                    row.append(_num(getattr(d, field, None), decimals=2))
                else:
                    v = getattr(d, field, "")
                    row.append(_sanitize_cell_text(v))
            data.append(row)                

        # Determine total row logic
        # Standard invoice pagination: 12 rows per page, and show a per-page TOTAL row on every page.
        add_total = bool(add_total_row)
        # If it's the last page and we're showing totals, use all_dispatches for grand total
        # UNLESS the user explicitly requested "every_page", which strictly means page-totals only.
        if is_last_page and add_total and all_dispatches is not None and total_option != "every_page":
            dispatches_to_sum = all_dispatches
        else:
            dispatches_to_sum = dispatch_subset
        total_row = []

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

            for i, field in enumerate(active_fields):
                if field == "weight":
                    # Show total weight (MT) with 3 decimals
                    total_row.append(f"{total_weight:.3f}")
                elif field in ("km", "rate"):
                    # No totals for km and rate
                    total_row.append("")
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
                else:
                    total_row.append("")
            # Total label rendered during cell formatting
            data.append(total_row)

        # Use full available width for table - distribute columns proportionally
        # Increased widths to prevent column names and data from breaking/wrapping
        table_width = available_width
        headers = data[0]
        num_cols = len(headers)

        # Base column widths - will be scaled to fill full width
        # Keys MUST match the actual header text (from label_map) so widths apply correctly.
        # Keep this mapping in sync with generate_invoice_pdf so both PDFs have the same layout.
        base_widths = {
            "Sr\u00A0No": 10,  # Match label_map with non-breaking space
            dc_label: 26,  # Wider so "Shipment" or custom labels fit on one line
            "Truck\u00A0No": 20,
            "Party\u00A0Name": 28,  # Wider to keep on one line
            "Product": 16,
            "GC\u00A0Note": 20,  # Wider so header text stays on a single line
            # Give numeric columns a bit more width so totals never wrap (e.g. 1698.000)
            "Weight": 16,
            "Km": 13,
            "Rate": 16,
            "Lugg.": 22,
            "Unload\u00A01": 18,  # Match label_map with non-breaking space
            "Unload\u00A02": 18,  # Match label_map with non-breaking space
            "Loading": 14,
            "Freight": 14,
            "Amount": 20,
            "Dep\u00A0Date": 20,  # Match creation-invoice PDF
            "Dest.": 24,
            "Dist.": 26,  # wider so "AHMEDABAD" fits on one line
            "Tal.": 16,
            "Main\u00A0Party": 20,  # Match label_map with non-breaking space
            "Sub\u00A0Party": 20,  # Match label_map with non-breaking space
        }

        # Calculate proportional widths
        col_widths = []
        total_base = 0
        for col_name in headers:
            base = base_widths.get(col_name, 10)  # Default base width
            col_widths.append(base)
            total_base += base

        # Scale all columns to fill full table width
        if total_base > 0:
            scale_factor = table_width / total_base
            col_widths = [w * scale_factor for w in col_widths]
        else:
            # Fallback: equal distribution
            col_widths = [table_width / num_cols] * num_cols

        # Format cells
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                field_name = active_fields[j]
                if i == 0:  # header - use uniform style for all column names, prevent wrapping
                    # Use non-breaking spaces and prevent wrapping
                    cell_text = str(cell).replace(' ', '\u00A0')  # Replace spaces with non-breaking spaces
                    row[j] = Paragraph(f"<b>{cell_text}</b>", header_style_uniform)
                elif add_total and i == len(data) - 1:  # total row
                    if j == 0:
                        row[j] = Paragraph("TOTAL", total_label_style_local)
                    else:
                        row[j] = Paragraph(str(cell), total_style_local)
                else:
                    if field_name == "district":
                        style = district_style_local
                    else:
                        style = to_right_style_desc_local if field_name in numeric_fields else center_style_desc_local if field_name in center_fields else to_style_desc_local
                    row[j] = Paragraph(str(cell), style)

        # Let ReportLab dynamically auto-size row heights based on font size and strict padding.
        # This prevents hardcoded heights from catastrophically breaking page boundaries if a 
        # specific company has an oversized multi-line header/address that dynamically shrinks available height.
        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Table styles - simple, elegant, standard structure (no background colors)
        styles = [
            # Header styling
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
            # Moderately tight paddings so the table appears larger but still fits 12 rows per page plus footer
            ("LEFTPADDING", (0,0), (-1,-1), 1.0),
            ("RIGHTPADDING", (0,0), (-1,-1), 1.0),
            ("TOPPADDING", (0,0), (-1,0), 3.5),   # Header padding stretched
            ("BOTTOMPADDING", (0,0), (-1,0), 3.5),
            ("TOPPADDING", (0,1), (-1,-2), 3.5),  # Data rows padding stretched softly
            ("BOTTOMPADDING", (0,1), (-1,-2), 3.5),
            # Clean borders - top and bottom of header
            ("LINEABOVE", (0,0), (-1,0), 1.0, colors.black),
            ("LINEBELOW", (0,0), (-1,0), 1.0, colors.black),
            # Grid lines for all cells - simple and standard
            ("GRID", (0,0), (-1,-1), 0.5, colors.black),
            # Allow wrapping; together with auto row heights above this keeps each
            # logical row visually distinct even with large content.
            ("WORDWRAP", (0,0), (-1,-1), "CJK"),
        ]
        # No zebra striping - clean and simple
        if add_total:
            # Span the TOTAL label across the non-numeric columns before the first numeric total
            numeric_total_fields = set(numeric_fields) | {"amount"}
            first_total_idx = None
            for idx, f in enumerate(active_fields):
                if f in numeric_total_fields:
                    first_total_idx = idx
                    break
            span_end = min((first_total_idx - 1) if first_total_idx is not None else 0, num_cols - 1)
            if span_end >= 1:
                styles.append(("SPAN", (0, -1), (span_end, -1)))
                styles.append(("ALIGN", (0, -1), (span_end, -1), "LEFT"))

            styles += [
                ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
                ("BACKGROUND", (0,-1), (-1,-1), colors.whitesmoke),
                # Slightly larger total-row padding so TOTAL stands out but still fits 12 rows
                ("TOPPADDING", (0,-1), (-1,-1), 3),
                ("BOTTOMPADDING", (0,-1), (-1,-1), 3),
                ("LINEABOVE", (0,-1), (-1,-1), 1.0, colors.black),
            ]
        table.setStyle(TableStyle(styles))

        return table




    # --- Split dispatches per page ---
    if contract.rate_type == "Distric-Wise":
        page_no = 1

        # Sort dispatches by district, then by challan_no (ascending) within each district
        def sort_key(d):
            def get_numeric_value(challan_no):
                if not challan_no:
                    return 0
                num_match = re.search(r"\d+", str(challan_no))
                return int(num_match.group(0)) if num_match else 0

            # Positive for ascending challan order within each district
            return (d.district or "", get_numeric_value(d.challan_no))

        dispatches_sorted = sorted(dispatches, key=sort_key)

        # --- Correct total page count for district-wise pagination ---
        # We cannot simply do ceil(len(dispatches_sorted) / chunk_size) because
        # pagination is RESET for every district. Example:
        #   District A -> 13 rows (needs 2 pages with chunk_size=12)
        #   District B -> 13 rows (also 2 pages)
        #   Total rows = 26 → ceil(26 / 12) = 3  (WRONG)
        #   Actual pages = 2 + 2 = 4          (CORRECT)
        #
        # To avoid "Page 5 of 4" style mismatches, we first materialise all
        # district groups and then sum the pages required for each group.
        district_groups = []
        for district, district_dispatches_iter in groupby(
            dispatches_sorted, key=attrgetter("district")
        ):
            district_list = list(district_dispatches_iter)
            district_groups.append((district, district_list))

        total_pages = 0
        for _district, district_list in district_groups:
            if district_list:
                total_pages += math.ceil(len(district_list) / chunk_size)

        # Group by district using the pre-built list so our page counter matches
        # the actual rendered pages.
        for district, district_dispatches in district_groups:
            # print(district_dispatches)
            # Paginate within the district
            for i in range(0, len(district_dispatches), chunk_size):
                dispatch_chunk = district_dispatches[i:i+chunk_size]
                if page_no > 1: 
                    elements.append(PageBreak())
                
                # Header
                elements.append(header_table)
                # Very tight spacing between company header and "TO" block
                elements.append(Spacer(1, 1))

                # TO Table with Page number
                to_content = [
                    Paragraph("<b>TO</b>", to_style),
                    Paragraph(f"{contract.c_designation}, ", to_style),
                    Paragraph(f"{contract.company_name},", to_style),  # Company name on left side, left-aligned
                    Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                    Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                    Paragraph(f"GST NO. : {contract.gst_number}", to_style)
                ]
                bill_no_content = [
                    Paragraph(f"Bill No : {invoice.Bill_no}", to_right_style),
                    Paragraph(f"Bill Date : {bill_date.strftime('%d-%m-%Y')}", to_right_style),
                    Paragraph(f"From : {contract.from_center}", to_right_style),
                    Paragraph(f"District : {district}", to_right_style),
                    Paragraph(f"Page : {page_no} of {total_pages} ", to_right_style)
                ]
                page_no += 1
                
                # Calculate widths based on available space
                to_table_width = available_width
                to_table = Table([[to_content, bill_no_content]], colWidths=[to_table_width * 0.82, to_table_width * 0.18])
                to_table.setStyle(TableStyle([
                    ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("ALIGN",(0,0),(0,0),"LEFT"),
                    ("ALIGN",(1,0),(1,0),"RIGHT"),  
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2),
                    ("TOPPADDING",(0,0),(-1,-1),2),
                    ("BOTTOMPADDING",(0,0),(-1,-1),2)
                ]))
                elements.append(to_table)
                # Keep a very small, positive gap so "PARTICULARS" is clearly visible
                # and never overlapped by the table header in any viewer.
                elements.append(Spacer(1, 1))
                elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))

                # Dispatch Table for this page
                # Determine if we should show total based on total_option
                show_total = (total_option == "every_page")

                # Small positive spacer so the table starts just below "PARTICULARS"
                # without overlapping the heading in the rendered PDF.
                elements.append(Spacer(1, 1))
                elements.append(
                    build_table_page(
                        dispatch_chunk,
                        add_total_row=show_total,
                    )
                )
                # Small gap before footer only (does not affect space above table)
                elements.append(Spacer(1, 4))
                elements.extend(build_footer_block())

    else:
        page_no = 1
        total_pages = math.ceil(len(dispatches) / chunk_size)

        for i in range(0, len(dispatches), chunk_size):
            dispatch_chunk = dispatches[i:i+chunk_size]
            is_last_page = (i + chunk_size) >= len(dispatches)

            if i > 0:
                elements.append(PageBreak())

            elements.append(header_table)
            elements.append(Spacer(1, 1))  # Very tight spacing below header

            # TO Table
            to_content = [
                Paragraph("<b>TO</b>", to_style),
                Paragraph(f"{contract.c_designation}, ", to_style),
                Paragraph(f"{contract.company_name},", to_style),  # Company name on left side, left-aligned
                Paragraph(f"{contract.billing_address}, {contract.billing_city}", to_style),
                Paragraph(f"{contract.billing_state}, {contract.billing_pin}", to_style),
                Paragraph(f"GST NO. : {contract.gst_number}", to_style)
            ]
            bill_no_content = [
                Paragraph(f"Bill No : {invoice.Bill_no}", to_right_style),
                Paragraph(f"Bill Date : {bill_date.strftime('%d-%m-%Y')}", to_right_style),
                Paragraph(f"From : {contract.from_center}", to_right_style),
                Paragraph(f"Page : {page_no} of {total_pages}", to_right_style)
            ]
            page_no += 1

            # Calculate widths based on available space
            to_table_width = available_width
            to_table = Table([[to_content, bill_no_content]], colWidths=[to_table_width * 0.82, to_table_width * 0.18])
            to_table.setStyle(TableStyle([
                ('LINEBELOW',(0,0),(-1,0),0.8,colors.black),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("ALIGN",(0,0),(0,0),"LEFT"),
                ("ALIGN",(1,0),(1,0),"RIGHT"),
                ("LEFTPADDING",(0,0),(-1,-1),2),
                ("RIGHTPADDING",(0,0),(-1,-1),2),
                ("TOPPADDING",(0,0),(-1,-1),2),
                ("BOTTOMPADDING",(0,0),(-1,-1),2)
            ]))
            elements.append(to_table)  
            # Small positive space so "PARTICULARS" appears clearly between
            # the TO block and the dispatch table.
            elements.append(Spacer(1, 1))
            elements.append(Paragraph("<center><b>PARTICULARS</b></center>", center_style))
            # Small positive spacer before the table so the heading is not clipped
            # or hidden under the table header lines.
            elements.append(Spacer(1, 1))

            # **Build table only ONCE per page**
            # Use start_index so Sr No continues across pages (13 after 12, etc.)
            # Determine if we should show total based on total_option
            if total_option == "every_page":
                show_total = True
            else:
                show_total = is_last_page  # Only show on last page
            elements.append(
                build_table_page(
                    dispatch_chunk,
                    add_total_row=show_total,
                    is_last_page=is_last_page,
                    all_dispatches=dispatches,
                    start_index=(i + 1),
                )
            )
            # Reduce gap before footer so everything fits on one page
            elements.append(Spacer(1, 4))
            elements.extend(build_footer_block())

    # --- Build PDF ---
    doc.build(elements)
    buffer.seek(0)
    filename = _invoice_pdf_filename(
        company_name=contract.company_name,
        contract_no=contract.contract_no,
        bill_no=invoice.Bill_no,
        invoice_id=getattr(invoice, "id", None),
    )

    # Decide whether to preview inline or force download based on the "download" flag
    download_flag = (request.POST.get("download") or "").strip()
    if download_flag:
        # Explicit download button → send as file attachment
        return FileResponse(buffer, as_attachment=True, filename=filename)

    # Preview button (no download flag) → open inline in browser
    from django.http import HttpResponse

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


##########################################
## END OF DOWNLOAD GENRATED INOVICE PDF ##
##########################################


@session_required
def download_gc_pdf(request):
    if request.method != "POST":
        return redirect("view-gc-note")

    preview_flag = (request.POST.get("preview") or "").strip()

    if request.method == "POST":
        selected_gc_ids = request.POST.getlist('dispatch_ids')
        if not selected_gc_ids:
            messages.error(request, "No GC Notes selected for PDF generation.")
            return redirect("view-gc-note")

        # The UI sends selected ids via the `dispatch_ids` key.
        # Sometimes it can contain invalid values (e.g. "undefined") which would raise a 500.
        selected_gc_ids_int = []
        for _id in selected_gc_ids:
            try:
                selected_gc_ids_int.append(int(_id))
            except (TypeError, ValueError):
                continue

        if not selected_gc_ids_int:
            messages.error(request, "No valid GC Notes selected for PDF generation.")
            return redirect("view-gc-note")

        gc_notes = GC_Note.objects.filter(
            id__in=selected_gc_ids_int,
            company_id=request.session['company_info']['company_id'],
        ).order_by('gc_no')
   

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
        # GC Note date should match dispatch (dep_date), not the stored gc_date (which may be older).
        date_val = None
        if getattr(gc, "dispatch_id", None):
            date_val = gc.dispatch_id.dep_date
        if not date_val:
            date_val = gc.gc_date

        to_table_data = [[Paragraph("<b>GOODS CONSINGNMENT NOTE</b>",styles["Normal"]), Paragraph(f"<b>NO : {gc.gc_no} </b>", styles["Normal"])]]

        to_table = Table(to_table_data, colWidths=[400, 88])  #adjust widths to fit page
        to_table.setStyle(TableStyle([ 
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (0,0), (0,0), "LEFT"),   
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
                  
        ]))  

        details_table_data = [
            [Paragraph(f"<b>Date</b>",styles["font9"]),":",Paragraph(f"{date_val.strftime('%d-%m-%Y') if date_val else ''}",styles["font9"]), Paragraph(f"<b>Truck No. </b>", styles["font9"]),":", Paragraph(f"{gc.truck_no}",styles["font9"])],
            [Paragraph(f"<b>Consignor</b>",styles["font9"]),":",Paragraph(f"{gc.consignor}",styles["font9"]), "", "" , ""],
            # Always show 3 digits after decimal for weight (e.g. 12.345)
            [Paragraph(f"<b>Depacth From</b>",styles["font9"]),":",Paragraph(f"{gc.dispatch_from}",styles["font9"]), Paragraph(f"<b>Weight</b>",styles["font9"]), ":" , Paragraph(f"{(gc.weight or 0):.3f}",styles["font9"])],
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
    # Preview means show inline in browser; download means download as attachment.
    response['Content-Disposition'] = (
        'inline; filename="gc_notes.pdf"'
        if preview_flag
        else 'attachment; filename="gc_notes.pdf"'
    )
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
    # Optional flag: when enabled, summary becomes "page wise" –
    # the Bill No column is replaced by Page No (simply the running page index).
    page_wise_summary = (request.POST.get("page_wise_summary") or "").lower() in ("1", "true", "yes", "on")
    show_bill_summary_title = (request.POST.get("show_bill_summary_title") or "").lower() in ("1", "true", "yes", "on")
    show_from_product_row = (request.POST.get("show_from_product_row") or "").lower() in ("1", "true", "yes", "on")
    show_total_weight = (request.POST.get("show_total_weight") or "").lower() in ("1", "true", "yes", "on")
    
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
    
    # Collect bill/page data with totals
    bills_data = []
    total_mt = 0
    total_bill_amount = 0
    total_loading = 0
    total_unloading1 = 0
    total_unloading2 = 0
    total_grand_total = 0
    
    chunk_size = 12  # Must match invoice pagination (12 rows per page)
    for invoice in invoices:
        dispatches_qs = invoice.dispatch_list.all()
        dispatches = list(sort_dispatches_by_challan_asc(dispatches_qs))

        if not dispatches:
            continue

        if page_wise_summary:
            # One summary row per **invoice page** (page totals), not one row per bill.
            #
            # IMPORTANT:
            #   The way rows are split into pages must exactly mirror the invoice
            #   PDF pagination logic, otherwise "Page 1" in the invoice will not
            #   match "Page 1" in this summary.
            #
            # For normal (non "Distric-Wise") contracts the invoice groups rows in
            # simple chunks of 12.  For "Distric-Wise" contracts, however, the
            # invoice groups rows by district first and then paginates **inside**
            # each district (see download_generate_invoice_pdf).
            #
            # We reproduce that behaviour here so the per‑page totals line up.

            page_counter = 0  # running page index for this invoice

            if getattr(contract, "rate_type", "") == "Distric-Wise":
                # --- District‑wise pagination (must match download_generate_invoice_pdf) ---
                def _challan_numeric(challan_no):
                    if not challan_no:
                        return 0
                    num_match = re.search(r"\d+", str(challan_no))
                    return int(num_match.group(0)) if num_match else 0

                # Order by (district, challan number ascending) just like invoice PDF
                dispatches_sorted = sorted(
                    dispatches,
                    key=lambda d: (d.district or "", _challan_numeric(d.challan_no)),
                )

                # Group by district then paginate each district block
                for _district, district_dispatches_iter in groupby(
                    dispatches_sorted, key=attrgetter("district")
                ):
                    district_dispatches = list(district_dispatches_iter)

                    for i in range(0, len(district_dispatches), chunk_size):
                        page_counter += 1
                        page_dispatches = district_dispatches[i : i + chunk_size]

                        page_mt = sum(
                            float(d.weight) for d in page_dispatches if d.weight
                        )
                        page_amount = sum(
                            float(d.totalfreight)
                            for d in page_dispatches
                            if d.totalfreight
                        )
                        page_loading = sum(
                            float(d.loading_charge)
                            for d in page_dispatches
                            if d.loading_charge
                        )
                        page_unloading1 = sum(
                            float(d.unloading_charge_1)
                            for d in page_dispatches
                            if d.unloading_charge_1
                        )
                        page_unloading2 = sum(
                            float(d.unloading_charge_2)
                            for d in page_dispatches
                            if d.unloading_charge_2
                        )
                        page_grand_total = (
                            page_amount
                            + page_loading
                            + page_unloading1
                            + page_unloading2
                        )

                        bills_data.append(
                            {
                                "bill_no": invoice.Bill_no,
                                "page_no": page_counter,
                                "mt": page_mt,
                                "bill_amount": page_amount,
                                "loading": page_loading,
                                "unloading1": page_unloading1,
                                "unloading2": page_unloading2,
                                "grand_total": page_grand_total,
                            }
                        )

                        total_mt += page_mt
                        total_bill_amount += page_amount
                        total_loading += page_loading
                        total_unloading1 += page_unloading1
                        total_unloading2 += page_unloading2
                        total_grand_total += page_grand_total
            else:
                # --- Standard pagination: simple sequential chunks of 12 rows ---
                for page_idx in range(0, len(dispatches), chunk_size):
                    page_counter += 1
                    page_dispatches = dispatches[page_idx : page_idx + chunk_size]
                    page_mt = sum(float(d.weight) for d in page_dispatches if d.weight)
                    page_amount = sum(
                        float(d.totalfreight) for d in page_dispatches if d.totalfreight
                    )
                    page_loading = sum(
                        float(d.loading_charge)
                        for d in page_dispatches
                        if d.loading_charge
                    )
                    page_unloading1 = sum(
                        float(d.unloading_charge_1)
                        for d in page_dispatches
                        if d.unloading_charge_1
                    )
                    page_unloading2 = sum(
                        float(d.unloading_charge_2)
                        for d in page_dispatches
                        if d.unloading_charge_2
                    )
                    page_grand_total = (
                        page_amount
                        + page_loading
                        + page_unloading1
                        + page_unloading2
                    )

                    bills_data.append(
                        {
                            "bill_no": invoice.Bill_no,
                            "page_no": page_counter,
                            "mt": page_mt,
                            "bill_amount": page_amount,
                            "loading": page_loading,
                            "unloading1": page_unloading1,
                            "unloading2": page_unloading2,
                            "grand_total": page_grand_total,
                        }
                    )

                    total_mt += page_mt
                    total_bill_amount += page_amount
                    total_loading += page_loading
                    total_unloading1 += page_unloading1
                    total_unloading2 += page_unloading2
                    total_grand_total += page_grand_total
        else:
            bill_mt = sum(float(d.weight) for d in dispatches if d.weight)
            bill_amount = sum(float(d.totalfreight) for d in dispatches if d.totalfreight)
            bill_loading = sum(float(d.loading_charge) for d in dispatches if d.loading_charge)
            bill_unloading1 = sum(float(d.unloading_charge_1) for d in dispatches if d.unloading_charge_1)
            bill_unloading2 = sum(float(d.unloading_charge_2) for d in dispatches if d.unloading_charge_2)

            bill_grand_total = bill_amount + bill_loading + bill_unloading1 + bill_unloading2

            bills_data.append({
                "bill_no": invoice.Bill_no,
                "mt": bill_mt,
                "bill_amount": bill_amount,
                "loading": bill_loading,
                "unloading1": bill_unloading1,
                "unloading2": bill_unloading2,
                "grand_total": bill_grand_total,
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
        # Use tighter margins so the summary uses more page width (less left/right whitespace).
        rightMargin=3 * mm,
        leftMargin=3 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
    )
    elements = []
    available_w = doc.width

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
    left_normal = ParagraphStyle(name="LeftNormal", parent=normal, alignment=0)

    company_name = (company.company_name or "").upper()
    pan_no = (company_profile.pan_number if company_profile and company_profile.pan_number else "") if company_profile else ""
    # Header should show our own company GSTIN (as before), not the customer's GST.
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
    has_sac = bool(getattr(contract, "sac_number", None))
    sac_line = f"SAC-{contract.sac_number}" if has_sac else ""

    header_cell = [
        Paragraph(company_name, title_center),
        Spacer(1, 2),
        *header_lines,
        Spacer(1, 2),
        Paragraph(pan_gst_line, small_center) if pan_gst_line else Paragraph("", small_center),
    ]
    header_table = Table([[header_cell]], colWidths=[available_w])
    header_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 4))

    # Center SAC and INVOICE text in the middle area just below the header box.
    if has_sac:
        elements.append(Paragraph(sac_line, small_center))
        elements.append(Paragraph("<b>INVOICE</b>", small_center))
        elements.append(Spacer(1, 8))
    else:
        elements.append(Spacer(1, 4))

    # ---- To + Date row ----
    date_str = summary_date.strftime("%d-%m-%Y")
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
    right_header_lines = []
    if page_wise_summary:
        bill_no_list = [str(b.Bill_no) for b in invoices if getattr(b, "Bill_no", None)]
        if bill_no_list:
            right_header_lines.append(Paragraph(f"Bill No.: {', '.join(bill_no_list)}", right))
    right_header_lines.append(Paragraph(f"Date: {date_str}", right))

    to_date_table = Table(
        [[to_lines, right_header_lines]],
        colWidths=[available_w * 0.7, available_w * 0.3],
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

    # Intro text block before summary table: show only when enabled in contract settings
    if getattr(contract, "show_summary_intro", False):
        elements.append(Paragraph("Sub: Submission of our Transportation Bill Summary", center_bold))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("Dear Sir,", left_normal))
        elements.append(Spacer(1, 3))
        from_center_text = contract.from_center or "our dispatch location"
        company_target = (contract.company_name or "").strip() or "your locations"
        intro_line = (
            "Please find enclosed herewith the following bills of transportation "
            f"from {from_center_text} to various destinations of {company_target}"
        )
        elements.append(Paragraph(intro_line, normal))
        elements.append(Spacer(1, 8))

    if show_bill_summary_title:
        elements.append(Paragraph("Bill Summary", center_bold))
        elements.append(Spacer(1, 6))

    # ---- FROM + Product row ----
    if show_from_product_row:
        from_text = contract.from_center or ""
        product_text = product_name or ""
        from_prod_table = Table(
            [[Paragraph(f"<b>FROM:</b> {from_text}", normal), Paragraph(f"<b>Product :</b> {product_text}", right)]],
            colWidths=[available_w * 0.5, available_w * 0.5],
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

    # ---- Determine which columns to show (hide if all values are zero) ----
    show_loading = any(bill['loading'] > 0 for bill in bills_data)
    show_unloading1 = any(bill['unloading1'] > 0 for bill in bills_data)
    show_unloading2 = any(bill['unloading2'] > 0 for bill in bills_data)

    # ---- Bills table (dynamically show/hide loading and unloading columns) ----
    # Build header row dynamically
    table_header = [
        Paragraph("Sr.", cell_header),
        Paragraph("Page No." if page_wise_summary else "Bill No.", cell_header),
        Paragraph("M.T", cell_header),
        Paragraph("Bill Amount Rs.", cell_header),
    ]
    
    if show_loading:
        table_header.append(Paragraph("Loading Rs.", cell_header))
    if show_unloading1:
        table_header.append(Paragraph("Unloading 1 Rs.", cell_header))
    if show_unloading2:
        table_header.append(Paragraph("Unloading 2 Rs.", cell_header))
    
    table_header.append(Paragraph("Grand Total Rs.", cell_header))
    
    table_data = [table_header]
    
    # Build data rows dynamically
    for idx, bill in enumerate(bills_data, 1):
        display_ref = bill.get("page_no") if page_wise_summary else bill["bill_no"]
        row = [
            Paragraph(str(idx), cell_center),
            Paragraph(str(display_ref), cell_center),
            Paragraph(f"{bill['mt']:.3f}", cell_right),
            Paragraph(f"{bill['bill_amount']:.2f}", cell_right),
        ]
        
        if show_loading:
            row.append(Paragraph(f"{bill['loading']:.2f}", cell_right))
        if show_unloading1:
            row.append(Paragraph(f"{bill['unloading1']:.2f}", cell_right))
        if show_unloading2:
            row.append(Paragraph(f"{bill['unloading2']:.2f}", cell_right))
        
        row.append(Paragraph(f"{bill['grand_total']:.2f}", cell_right))
        table_data.append(row)

    # Total row
    total_row = [
        Paragraph("Total", ParagraphStyle(name="TotalLeft", fontName="Helvetica-Bold", fontSize=9, alignment=1, leading=11)),
        "",
        Paragraph(f"{total_mt:.3f}", ParagraphStyle(name="TotalRight", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
        Paragraph(f"{total_bill_amount:.2f}", ParagraphStyle(name="TotalRight2", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)),
    ]
    
    if show_loading:
        total_row.append(Paragraph(f"{total_loading:.2f}", ParagraphStyle(name="TotalRight3", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)))
    if show_unloading1:
        total_row.append(Paragraph(f"{total_unloading1:.2f}", ParagraphStyle(name="TotalRight4", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)))
    if show_unloading2:
        total_row.append(Paragraph(f"{total_unloading2:.2f}", ParagraphStyle(name="TotalRight5", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)))
    
    total_row.append(Paragraph(f"{total_grand_total:.2f}", ParagraphStyle(name="TotalRight6", fontName="Helvetica-Bold", fontSize=9, alignment=2, leading=11)))
    table_data.append(total_row)

    # Dynamically calculate column widths based on which columns are shown
    # Fixed columns
    sr_width = 9 * mm
    bill_no_width = 35 * mm
    fixed_width = sr_width + bill_no_width
    
    # Count variable columns (MT, Bill Amount, optional charges, Grand Total)
    # Always shown: MT + Bill Amount + Grand Total = 3 columns
    var_col_count = 3
    var_col_count += int(show_loading) + int(show_unloading1) + int(show_unloading2)
    
    # Equal width for all variable columns
    var_col_width = (available_w - fixed_width) / max(var_col_count, 1)
    
    col_widths = [sr_width, bill_no_width]
    
    # Add variable-width columns
    col_widths.append(var_col_width)  # MT
    col_widths.append(var_col_width)  # Bill Amount
    
    if show_loading:
        col_widths.append(var_col_width)  # Loading
    if show_unloading1:
        col_widths.append(var_col_width)  # Unloading 1
    if show_unloading2:
        col_widths.append(var_col_width)  # Unloading 2
    
    col_widths.append(var_col_width)  # Grand Total

    # Ensure the table consumes the full available width (avoid any rounding/column-count drift)
    width_delta = available_w - sum(col_widths)
    if abs(width_delta) > 0.01:
        col_widths[-1] += width_delta

    bill_table = Table(table_data, colWidths=col_widths)
    bill_table.hAlign = "LEFT"
    bill_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("SPAN", (0, -1), (1, -1)),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(bill_table)
    elements.append(Spacer(1, 10))

    # Display overall total weight prominently below the summary table when enabled.
    if show_total_weight:
        elements.append(
            Paragraph(
                f"Total Weight (M.T): {total_mt:.3f}",
                normal_bold,
            )
        )
        elements.append(Spacer(1, 8))

    # ---- Footer note + Signature ----
    client_company_name = contract.company_name or "the Company"
    summary_footer_note = (contract.summary_footer_note or "").strip()
    if not summary_footer_note:
        summary_footer_note = f"Remark : GST shall be Payable by {client_company_name} under Reverse Charge Mechanism"
    elements.append(Paragraph(summary_footer_note, normal))
    elements.append(Spacer(1, 14))

    sig_table = Table(
        [
            [
                Paragraph("", normal),
                Paragraph(f"FOR {company_name}" if company_name else f"FOR {client_company_name}", right_bold),
            ],
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
    # Inline preview by default; only download when ?download=1 or hidden input is sent
    download_flag = request.POST.get("download") or request.GET.get("download")
    response = FileResponse(
        buffer,
        as_attachment=bool(download_flag),
        filename=filename,
        content_type="application/pdf",
    )
    return response 
