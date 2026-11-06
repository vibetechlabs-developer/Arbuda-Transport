from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from truckmaster.paper import money_txt
from truckmaster.reports import pdf_response

BLACK = colors.black
GRID = [
    ("GRID", (0, 0), (-1, -1), 0.4, BLACK),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 7),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ("TOPPADDING", (0, 0), (-1, -1), 2),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
]


def _a(v, keep_zero=False):
    return money_txt(v, blank_zero=not keep_zero)


def _d(value):
    if not value:
        return ""
    return value.strftime("%d-%m-%Y")


def _title(text, size=14):
    return Paragraph(
        text,
        ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=size, alignment=1, leading=size + 2),
    )


def _sub(text):
    return Paragraph(
        text or "",
        ParagraphStyle("s", fontName="Helvetica", fontSize=9, alignment=1, leading=12),
    )


def pnl_pdf(ctx, filename):
    trucks = ctx.get("trucks") or []
    codes = ctx.get("truck_codes") or [""]
    n = max(len(codes), 1)
    header1 = [ctx.get("month_label") or "", ""] + [ctx.get("company_name") or ""] * n + ["Profit & Loss a/c", "MONTHLY"]
    header2 = ["Particular", ""] + list(codes or ["-"]) + ["", "AMT"]
    data = [header1, header2]
    for row in ctx.get("display_rows") or []:
        keep = bool(row.get("is_net"))
        line = [row["label"], ""] + [_a(v, keep) for v in row.get("values") or []]
        while len(line) < 2 + n:
            line.append("")
        line.extend(["", _a(row.get("total"), True)])
        data.append(line)
    prev = [ctx.get("prev_label") or "", ""] + [_a(v, True) for v in ctx.get("prev_nets") or []]
    while len(prev) < 2 + n:
        prev.append("")
    prev.extend(["", ""])
    data.append(prev)
    col_w = [95, 28] + [62] * n + [80, 70]
    tbl = Table(data, colWidths=col_w, repeatRows=2)
    style = list(GRID) + [
        ("SPAN", (2, 0), (1 + n, 0)),
        ("ALIGN", (0, 0), (-1, 1), "CENTER"),
        ("ALIGN", (2, 2), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#f2f2f2")),
    ]
    tbl.setStyle(TableStyle(style))
    story = [_title(ctx.get("company_name") or ""), _sub(ctx.get("company_address") or ""), Spacer(1, 6), tbl]
    return pdf_response(filename, story, landscape_mode=True, tight=True)


def vakara_pdf(ctx, filename):
    data = [[
        "Date", "Trip", "Weight", "Description", "Part Name", "Rate M.T.", "Freight",
        "Payment", "BILL NO", "Diesel", "Pump", "Dri.Adv", "RIPAIRING",
    ]]
    for r in ctx.get("rows") or []:
        data.append([
            _d(r["date"]),
            r["trip"],
            _a(r["weight"], r.get("is_hold")),
            r.get("description") or "",
            r.get("party") or "",
            _a(r.get("rate")),
            _a(r.get("freight"), True),
            r.get("payment") or "",
            r.get("bill_no") or "",
            _a(r.get("diesel")),
            r.get("pump") or "",
            _a(r.get("advance")),
            _a(r.get("repair")),
        ])
    tot = ctx.get("tot") or {}
    data.append([
        "TOTAL", "", _a(tot.get("weight"), True), "", "", "",
        _a(tot.get("freight"), True), "", "", _a(tot.get("diesel_ltr"), True), "",
        _a(tot.get("advance"), True), _a(tot.get("repair"), True),
    ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle(GRID + [
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ALIGN", (5, 1), (6, -1), "RIGHT"),
        ("ALIGN", (9, 1), (9, -1), "RIGHT"),
        ("ALIGN", (11, 1), (12, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
    ]))
    party_rows = [["Recd Freight List", "Amt"]]
    for name, amt in ctx.get("party_totals") or []:
        party_rows.append([name, _a(amt)])
    party_rows.append(["CASH", _a(ctx.get("cash_total"))])
    party_rows.append(["CHEQUE", _a(ctx.get("cheque_total"))])
    party_rows.append(["TOTAL", _a(ctx.get("freight_total"), True)])
    left = Table(party_rows)
    left.setStyle(TableStyle(GRID + [("ALIGN", (1, 1), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2"))]))
    box_rows = [["Particular", "AMT"]]
    for b in ctx.get("box") or []:
        box_rows.append([b["label"], _a(b.get("amount"), True)])
    right = Table(box_rows)
    right.setStyle(TableStyle(GRID + [("ALIGN", (1, 1), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2"))]))
    bottom = Table([[left, right]], colWidths=[140 * mm, 140 * mm])
    story = [
        _title(ctx.get("company_name") or ""),
        _sub(ctx.get("date_range") or ""),
        _sub(f"{ctx.get('truck_no') or ''}   VAKARA-REPORT"),
        Spacer(1, 6),
        tbl,
        Spacer(1, 8),
        bottom,
    ]
    return pdf_response(filename, story, landscape_mode=True, tight=True)


def voucher_month_pdf(ctx, filename):
    data = [[
        "Date", "Trip", "Weight", "Loading", "Unloading", "Labour", "Commi", "Toll Tax", "Other Exp", "Total", "Remark",
    ]]
    for r in ctx.get("rows") or []:
        data.append([
            _d(r["date"]),
            r["trip"],
            _a(r.get("weight")),
            _a(r.get("loading")),
            _a(r.get("unloading")),
            _a(r.get("labour")),
            _a(r.get("commission")),
            _a(r.get("toll")),
            _a(r.get("other")),
            _a(r.get("total"), True),
            r.get("remark") or "",
        ])
    t = ctx.get("totals") or {}
    data.append([
        "TOTAL", "", _a(t.get("weight"), True), _a(t.get("loading"), True), _a(t.get("unloading"), True),
        _a(t.get("labour"), True), _a(t.get("commission"), True), _a(t.get("toll"), True),
        _a(t.get("other"), True), _a(t.get("total"), True), "",
    ])
    data.append(["EXPENCESS", "DAY", str(ctx.get("day_count") or ""), _a(ctx.get("day_exp")), "", "", "", "", "", _a(ctx.get("day_exp"), True), ""])
    data.append(["", "NIGHT", str(ctx.get("night_count") or ""), _a(ctx.get("night_exp")), "", "", "", "", "", _a(ctx.get("night_exp"), True), ""])
    formula = ctx.get("diesel_formula") or ""
    data.append([f"DIESEL BILL {formula}", "", "", _a(ctx.get("diesel_total")), "", "", "", "", "", _a(ctx.get("diesel_total"), True), ""])
    data.append(["Repair & Maintenance (With Labour)", "", "", "", "", "", "", "", "", "", ""])
    for m in ctx.get("repairs") or []:
        name = (m.description or m.get_maintenance_type_display() or "").upper()
        data.append([_d(m.entry_date), name, "", _a(m.labour_charges), "", "", "", "", "", _a(m.labour_charges), ""])
    data.append(["", "", "", "", "", "", "", "", "", _a(ctx.get("repair_labour_total"), True), ""])
    data.append(["Repair & Spare parts(Material)", "", "", "", "", "", "", "", "", "", ""])
    for m in ctx.get("parts_repairs") or []:
        name = (m.description or m.get_maintenance_type_display() or "").upper()
        data.append([_d(m.entry_date), name, "", _a(m.spare_parts_cost), "", "", "", "", "", _a(m.spare_parts_cost), ""])
    data.append(["", "", "", "", "", "", "", "", "", _a(ctx.get("parts_total"), True), ""])
    data.append(["Truck Expenses", "", "", "", "", "", "", "", "", "", ""])
    for e in ctx.get("truck_exp_rows") or []:
        data.append(["", e["name"], "", _a(e["amount"]), "", "", "", "", "", _a(e["amount"]), ""])
    data.append(["", "", "", "", "", "", "", "", "", _a(ctx.get("truck_exp_total"), True), ""])
    data.append(["FAST TAG STATEMENT (BANK)", "", "", "", "", "", "", "", "", _a(ctx.get("fastag_total"), True), ""])
    data.append(["NET TOTAL", "", "", "", "", "", "", "", "", _a(ctx.get("net"), True), ""])
    tbl = Table(data, repeatRows=1)
    last = len(data) - 1
    tbl.setStyle(TableStyle(GRID + [
        ("ALIGN", (2, 1), (9, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("SPAN", (0, last), (8, last)),
    ]))
    story = [
        _title(ctx.get("company_name") or ""),
        _sub(ctx.get("truck_no") or ""),
        _sub(f"{ctx.get('date_range') or ''}   VOUCHER - REPORT"),
        Spacer(1, 6),
        tbl,
    ]
    return pdf_response(filename, story, landscape_mode=False, tight=True)


def invoice_statement_pdf(ctx, filename):
    name = ctx.get("company_name") or ""
    gst = ctx.get("company_gst") or ""
    address = ctx.get("company_address") or ""
    party = ctx.get("party")
    obj = ctx.get("obj")
    bill_no = ctx.get("bill_no") or (obj.invoice_no if obj else "")
    date_txt = ""
    if obj:
        date_txt = obj.invoice_date.strftime("%d-%b-%y")
    elif ctx.get("end"):
        date_txt = ctx["end"].strftime("%d-%b-%y")
    party_name = ""
    party_gst = ""
    if party:
        party_name = party.name
        party_gst = party.gstin or ""
    elif obj:
        party_name = obj.party.name if obj.party_id else ""
        party_gst = obj.gstin or ""
    left = [
        [Paragraph(f"<b>{name}</b>", ParagraphStyle("n", fontSize=12, leading=14))],
        [address],
        [f"GSTIN: {gst}"],
        [f"SAC CODE : 996511"],
    ]
    right = [
        [f"Bill No : {bill_no}"],
        [f"Date : {date_txt}"],
        [f"Customer : {party_name}"],
        [f"GST No : {party_gst}"],
    ]
    head = Table([[Table(left), Table(right)]], colWidths=[160 * mm, 110 * mm])
    data = [[
        "No.", "Date", "Invoice No.", "Lorry No.", "From", "Destination", "Taluka", "Dist.",
        "Weight", "Rent", "Lab", "Total", "Advance", "Balance",
    ]]
    for line in ctx.get("lines") or []:
        data.append([
            str(line["no"]),
            _d(line["date"]),
            line.get("invoice_no") or "",
            line.get("lorry") or "",
            line.get("from_location") or "",
            line.get("destination") or "",
            line.get("taluka") or "",
            line.get("district") or "",
            _a(line.get("weight")),
            _a(line.get("rent")),
            _a(line.get("labour")),
            _a(line.get("total")),
            _a(line.get("advance")),
            _a(line.get("balance")),
        ])
    tot = ctx.get("totals") or {}
    data.append([
        "", "", "", "", "", "", "", "Total",
        _a(tot.get("weight"), True), _a(tot.get("rent"), True), _a(tot.get("labour"), True),
        _a(tot.get("total"), True), _a(tot.get("advance"), True), _a(tot.get("balance"), True),
    ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle(GRID + [
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (8, 1), (13, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    sign = Paragraph(
        f"<b>FOR {name.upper()}</b><br/>AUTHORISED",
        ParagraphStyle("sg", fontSize=9, alignment=2, leading=12),
    )
    story = [head, Spacer(1, 8), tbl, Spacer(1, 18), sign]
    return pdf_response(filename, story, landscape_mode=True, tight=True)
