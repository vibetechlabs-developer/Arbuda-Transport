from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from company.models import Company_profile, Company_user
from erp.utils.csv_export import csv_response


def company_header(company_id):
    company = Company_user.objects.filter(id=company_id).first()
    profile = Company_profile.objects.filter(company_id_id=company_id).first()
    name = company.company_name if company else "Transport Company"
    gst = company.gst_number if company else ""
    address = profile.address if profile else ""
    return name, gst, address


def pdf_response(filename, story, landscape_mode=False, tight=False):
    buffer = BytesIO()
    pagesize = landscape(A4) if landscape_mode else A4
    margin = 8 * mm if tight else 12 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def table_story(title, headers, rows, company_id, subtitle=""):
    name, gst, address = company_header(company_id)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(name, styles["Title"]),
        Paragraph(f"GSTIN: {gst}", styles["Normal"]),
        Paragraph(address or "", styles["Normal"]),
        Spacer(1, 6),
        Paragraph(title, styles["Heading2"]),
    ]
    if subtitle:
        story.append(Paragraph(subtitle, styles["Normal"]))
        story.append(Spacer(1, 6))
    data = [headers] + [[("" if c is None else str(c)) for c in row] for row in rows]
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#696cff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f9")]),
            ]
        )
    )
    story.append(tbl)
    return story


def excel_table_response(filename, headers, rows):
    html = ["<table border='1'><tr>"]
    html.extend(f"<th>{h}</th>" for h in headers)
    html.append("</tr>")
    for row in rows:
        html.append("<tr>")
        html.extend(f"<td>{'' if c is None else c}</td>" for c in row)
        html.append("</tr>")
    html.append("</table>")
    response = HttpResponse("".join(html), content_type="application/vnd.ms-excel")
    if not filename.endswith(".xls"):
        filename = f"{filename}.xls"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def export_rows(request, filename, headers, rows):
    fmt = (request.GET.get("export") or "").lower()
    if fmt == "pdf":
        company_id = request.session["company_info"]["company_id"]
        return pdf_response(
            f"{filename}.pdf",
            table_story(filename.replace("_", " ").title(), headers, rows, company_id),
            landscape_mode=True,
        )
    if fmt in ("xlsx", "xls", "excel"):
        return excel_table_response(filename, headers, rows)
    return csv_response(filename=filename, header=headers, rows=rows)


def _amt(v):
    if v is None or v == 0:
        return ""
    return f"{v}"


def invoice_pdf(invoice, company_id):
    name, gst, address = company_header(company_id)
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    story = [
        Paragraph(name, styles["Title"]),
        Paragraph(f"GSTIN: {gst}", small),
        Paragraph(address or "", small),
        Paragraph("TRANSPORT INVOICE", styles["Heading2"]),
        Spacer(1, 6),
    ]
    meta = [
        ["Bill No", invoice.invoice_no, "Date", invoice.invoice_date.strftime("%d-%m-%Y")],
        ["Customer", invoice.party.name if invoice.party else "", "GSTIN", invoice.gstin or ""],
        ["Address", invoice.customer_address or "", "Material", invoice.material or ""],
    ]
    story.append(Table(meta, colWidths=[70, 220, 70, 220]))
    story.append(Spacer(1, 8))
    headers = ["Date", "Lorry No", "From", "Destination", "Taluka", "Weight", "Rate", "Rent", "Labour", "Total", "Advance", "Balance"]
    rows = [headers]
    linked = list(invoice.invoice_trips.select_related("trip", "trip__truck").all())
    if linked:
        for it in linked:
            trip = it.trip
            rows.append(
                [
                    trip.trip_date.strftime("%d-%m-%Y") if trip.trip_date else "",
                    (invoice.truck.registration_no if invoice.truck else "") or (trip.truck.registration_no if trip.truck_id else ""),
                    trip.start_location or "",
                    trip.destination or "",
                    invoice.taluka or "",
                    _amt(trip.loaded_weight),
                    _amt(invoice.rate),
                    _amt(trip.freight_amount),
                    "",
                    _amt(trip.freight_amount),
                    _amt(trip.advance_received),
                    _amt(trip.pending_amount),
                ]
            )
    else:
        rows.append(
            [
                invoice.invoice_date.strftime("%d-%m-%Y"),
                invoice.truck.registration_no if invoice.truck else "",
                invoice.from_location or "",
                invoice.destination or "",
                invoice.taluka or "",
                _amt(invoice.weight),
                _amt(invoice.rate),
                _amt(invoice.freight),
                _amt(invoice.labour),
                _amt(invoice.total_amount),
                _amt(invoice.advance),
                _amt(invoice.balance),
            ]
        )
    rows.append(
        [
            "TOTAL",
            "",
            "",
            "",
            "",
            _amt(invoice.weight),
            "",
            _amt(invoice.freight),
            _amt(invoice.labour),
            _amt(invoice.total_amount),
            _amt(invoice.advance),
            _amt(invoice.balance),
        ]
    )
    tbl = Table(rows, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eee")),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(tbl)
    return pdf_response(f"invoice_{invoice.invoice_no}.pdf", story, landscape_mode=True)


def voucher_pdf(voucher, company_id):
    name, gst, address = company_header(company_id)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(name, styles["Title"]),
        Paragraph("TRIP / TRUCK VOUCHER", styles["Heading2"]),
        Paragraph(f"Voucher No: {voucher.voucher_no}    Date: {voucher.voucher_date.strftime('%d-%m-%Y')}", styles["Normal"]),
        Spacer(1, 8),
    ]
    rows = [
        ["Trip", voucher.trip.trip_no if voucher.trip else ""],
        ["Truck", voucher.truck.registration_no if voucher.truck else ""],
        ["Driver", voucher.driver.name if voucher.driver else ""],
        ["Weight", str(voucher.weight)],
        ["Loading", str(voucher.loading)],
        ["Unloading", str(voucher.unloading)],
        ["Labour", str(voucher.labour)],
        ["Commission", str(voucher.commission)],
        ["Toll Tax", str(voucher.toll_tax)],
        ["Day Expenses", str(voucher.day_expenses)],
        ["Night Expenses", str(voucher.night_expenses)],
        ["Diesel Bills", str(voucher.diesel_bills)],
        ["Repair & Maintenance (Labour)", str(voucher.repair_labour)],
        ["Repair & Spare Parts", str(voucher.repair_parts)],
        ["Truck Expenses", str(voucher.truck_expenses)],
        ["FASTag Statement", str(voucher.fastag_amount)],
        ["Other Expenses", str(voucher.other_expenses)],
        ["TOTAL", str(voucher.total_amount)],
    ]
    tbl = Table([["Particular", "Amount"]] + rows, colWidths=[320, 140])
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#696cff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eee")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    story.append(tbl)
    return pdf_response(f"voucher_{voucher.voucher_no}.pdf", story)
