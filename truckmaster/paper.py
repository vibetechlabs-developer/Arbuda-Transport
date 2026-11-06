from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from truckmaster.models import (
    DieselEntry,
    DriverAdvance,
    DriverAttendance,
    ExpenseEntry,
    LoadingEntry,
    MaintenanceEntry,
    TollEntry,
    TransportInvoice,
    Trip,
    UnloadingEntry,
)
from truckmaster.services import d2, pnl_matrix, ZERO


def month_bounds(year, month):
    start = date(int(year), int(month), 1)
    end = date(int(year), int(month), monthrange(int(year), int(month))[1])
    return start, end


def truck_code(truck):
    digits = "".join(ch for ch in (truck.registration_no or "") if ch.isdigit())
    if len(digits) >= 4:
        return digits[-4:]
    return truck.registration_no or ""


def money_txt(v, blank_zero=True):
    v = d2(v)
    if blank_zero and v == 0:
        return ""
    if v == v.to_integral():
        return str(int(v))
    return f"{v:.2f}"


def trip_route(trip):
    start = (trip.start_location or "").upper()
    dest = (trip.destination or "").upper()
    if start and dest:
        return f"{start} TO {dest}"
    return start or dest


def vakara_context(company_id, truck, start, end):
    trips = list(
        Trip.objects.for_company(company_id)
        .filter(truck=truck, trip_date__gte=start, trip_date__lte=end)
        .exclude(status="cancelled")
        .select_related("booking", "booking__party", "driver")
        .order_by("trip_date", "id")
    )
    trips_by_day = defaultdict(list)
    for t in trips:
        trips_by_day[t.trip_date].append(t)

    diesel = list(
        DieselEntry.objects.for_company(company_id).filter(
            truck=truck, entry_date__gte=start, entry_date__lte=end
        )
    )
    diesel_by_day = defaultdict(list)
    for d in diesel:
        diesel_by_day[d.entry_date].append(d)

    advances = list(
        DriverAdvance.objects.for_company(company_id).filter(
            entry_date__gte=start, entry_date__lte=end, driver__assigned_truck=truck
        )
    )
    adv_by_day = defaultdict(list)
    for a in advances:
        adv_by_day[a.entry_date].append(a)

    repairs = list(
        MaintenanceEntry.objects.for_company(company_id).filter(
            truck=truck, entry_date__gte=start, entry_date__lte=end
        )
    )
    repair_by_day = defaultdict(list)
    for r in repairs:
        repair_by_day[r.entry_date].append(r)

    absent_days = set(
        DriverAttendance.objects.for_company(company_id)
        .filter(
            attendance_date__gte=start,
            attendance_date__lte=end,
            status__in=["absent", "leave"],
            driver__assigned_truck=truck,
        )
        .values_list("attendance_date", flat=True)
    )

    rows = []
    tot = {
        "weight": ZERO,
        "freight": ZERO,
        "diesel_ltr": ZERO,
        "advance": ZERO,
        "repair": ZERO,
    }
    day = start
    while day <= end:
        day_trips = trips_by_day.get(day, [])
        day_diesel = diesel_by_day.get(day, [])
        day_adv = adv_by_day.get(day, [])
        day_rep = repair_by_day.get(day, [])
        diesel_amt = d2(sum((x.total_amount or 0) for x in day_diesel))
        diesel_ltr = d2(sum((x.litres or 0) for x in day_diesel))
        pump = ", ".join(sorted({x.pump_name for x in day_diesel if x.pump_name}))
        adv_amt = d2(sum((x.amount or 0) for x in day_adv))
        rep_amt = d2(sum((x.total_amount or 0) for x in day_rep))
        tot["diesel_ltr"] += diesel_ltr
        tot["advance"] += adv_amt
        tot["repair"] += rep_amt

        if day_trips:
            for i, trip in enumerate(day_trips):
                party = ""
                pay_mode = ""
                bill = ""
                rate = ZERO
                if trip.booking_id:
                    if trip.booking.party_id:
                        party = trip.booking.party.name
                    pay_mode = (trip.booking.get_payment_mode_display() or "").upper()
                    bill = trip.booking.booking_no or ""
                    rate = trip.booking.freight_rate or ZERO
                weight = trip.loaded_weight or ZERO
                freight = trip.freight_amount or ZERO
                tot["weight"] += d2(weight)
                tot["freight"] += d2(freight)
                rows.append(
                    {
                        "date": day,
                        "trip": trip_route(trip),
                        "weight": weight,
                        "description": (trip.material_name or "").upper(),
                        "party": party,
                        "rate": rate,
                        "freight": freight,
                        "payment": pay_mode,
                        "bill_no": bill,
                        "diesel": diesel_ltr if i == 0 else ZERO,
                        "pump": pump if i == 0 else "",
                        "advance": adv_amt if i == 0 else ZERO,
                        "repair": rep_amt if i == 0 else ZERO,
                        "is_hold": False,
                    }
                )
        else:
            label = "ABSENT" if day in absent_days else "HOLD"
            rows.append(
                {
                    "date": day,
                    "trip": label,
                    "weight": ZERO,
                    "description": "",
                    "party": "",
                    "rate": ZERO,
                    "freight": ZERO,
                    "payment": "",
                    "bill_no": "",
                    "diesel": diesel_ltr,
                    "pump": pump,
                    "advance": adv_amt,
                    "repair": rep_amt,
                    "is_hold": True,
                }
            )
        day += timedelta(days=1)

    party_totals = defaultdict(lambda: ZERO)
    cash_total = ZERO
    cheque_total = ZERO
    for trip in trips:
        freight = d2(trip.freight_amount)
        name = "Other Party Freight"
        mode = ""
        if trip.booking_id and trip.booking.party_id:
            name = trip.booking.party.name
            mode = trip.booking.payment_mode or ""
        party_totals[name] += freight
        if mode == "cash":
            cash_total += freight
        else:
            cheque_total += freight

    pnl = pnl_matrix(company_id, start, end, truck_ids=[truck.id])
    box = _truck_pnl_box(pnl, truck.id)
    return {
        "truck": truck,
        "truck_no": truck.registration_no,
        "start": start,
        "end": end,
        "rows": rows,
        "tot": tot,
        "party_totals": sorted(party_totals.items(), key=lambda x: x[0]),
        "cash_total": cash_total,
        "cheque_total": cheque_total,
        "freight_total": tot["freight"],
        "box": box,
        "date_range": f"{start.strftime('%d/%m/%Y')} TO {end.strftime('%d/%m/%Y')}",
    }


def _truck_pnl_box(pnl, truck_id):
    labels = [
        ("gross_income", "Gross Income"),
        ("diesel", "Diesel Exp"),
        ("repairing", "Repairing Exp"),
        ("voucher", "Voucher Exp"),
        ("loan_emi", "Loan EMI"),
        ("insurance", "INSURANCE"),
        ("tyre", "Tyre Exp"),
        ("fastag", "FASTAG STATEMENT"),
        ("rto", "R.T.O TAX"),
    ]
    rows = []
    for key, label in labels:
        rows.append({"label": label, "amount": pnl["matrix"][key].get(truck_id, ZERO)})
    rows.append({"label": "NET TOTAL [+ -]", "amount": pnl["net"].get(truck_id, ZERO)})
    return rows


def voucher_month_context(company_id, truck, start, end):
    trips = list(
        Trip.objects.for_company(company_id)
        .filter(truck=truck, trip_date__gte=start, trip_date__lte=end)
        .exclude(status="cancelled")
        .select_related("booking")
        .order_by("trip_date", "id")
    )
    trips_by_day = defaultdict(list)
    for t in trips:
        trips_by_day[t.trip_date].append(t)

    loadings = list(LoadingEntry.objects.for_company(company_id).filter(truck=truck, entry_date__gte=start, entry_date__lte=end))
    unloadings = list(UnloadingEntry.objects.for_company(company_id).filter(truck=truck, entry_date__gte=start, entry_date__lte=end))
    expenses = list(
        ExpenseEntry.objects.for_company(company_id)
        .filter(truck=truck, expense_date__gte=start, expense_date__lte=end)
        .select_related("category")
    )
    tolls = list(TollEntry.objects.for_company(company_id).filter(truck=truck, entry_datetime__date__gte=start, entry_datetime__date__lte=end))
    diesel = list(DieselEntry.objects.for_company(company_id).filter(truck=truck, entry_date__gte=start, entry_date__lte=end).order_by("entry_date"))
    maint = list(MaintenanceEntry.objects.for_company(company_id).filter(truck=truck, entry_date__gte=start, entry_date__lte=end).order_by("entry_date"))

    load_by_day = defaultdict(lambda: ZERO)
    unload_by_day = defaultdict(lambda: ZERO)
    labour_by_day = defaultdict(lambda: ZERO)
    for r in loadings:
        load_by_day[r.entry_date] += d2(r.loading_charges)
        labour_by_day[r.entry_date] += d2(r.labour_charges)
    for r in unloadings:
        unload_by_day[r.entry_date] += d2(r.unloading_charges)
        labour_by_day[r.entry_date] += d2(r.labour_charges)

    comm_by_day = defaultdict(lambda: ZERO)
    toll_by_day = defaultdict(lambda: ZERO)
    other_by_day = defaultdict(lambda: ZERO)
    day_exp = ZERO
    night_exp = ZERO
    night_days = set()
    day_days = set()
    truck_exp_groups = defaultdict(lambda: ZERO)
    for e in expenses:
        code = e.category.code if e.category_id else "other"
        name = (e.category.name if e.category_id else "OTHER").upper()
        if code == "commission":
            comm_by_day[e.expense_date] += d2(e.amount)
        elif code in ("toll", "fastag"):
            toll_by_day[e.expense_date] += d2(e.amount)
        elif code == "night":
            night_exp += d2(e.amount)
            night_days.add(e.expense_date)
        elif code in ("food", "driver_allowance"):
            day_exp += d2(e.amount)
            day_days.add(e.expense_date)
        else:
            other_by_day[e.expense_date] += d2(e.amount)
            truck_exp_groups[name] += d2(e.amount)

    for t in tolls:
        if not t.is_fastag:
            toll_by_day[t.entry_datetime.date()] += d2(t.amount)

    absent_days = set(
        DriverAttendance.objects.for_company(company_id)
        .filter(
            attendance_date__gte=start,
            attendance_date__lte=end,
            status__in=["absent", "leave"],
            driver__assigned_truck=truck,
        )
        .values_list("attendance_date", flat=True)
    )

    rows = []
    totals = {
        "weight": ZERO,
        "loading": ZERO,
        "unloading": ZERO,
        "labour": ZERO,
        "commission": ZERO,
        "toll": ZERO,
        "other": ZERO,
        "total": ZERO,
    }
    day = start
    while day <= end:
        day_trips = trips_by_day.get(day, [])
        loading = load_by_day[day]
        unloading = unload_by_day[day]
        labour = labour_by_day[day]
        comm = comm_by_day[day]
        toll = toll_by_day[day]
        other = other_by_day[day]
        line_total = loading + unloading + labour + comm + toll + other
        if day_trips:
            for i, trip in enumerate(day_trips):
                use_l, use_u, use_lb, use_c, use_t, use_o = (loading, unloading, labour, comm, toll, other) if i == 0 else (ZERO, ZERO, ZERO, ZERO, ZERO, ZERO)
                use_total = use_l + use_u + use_lb + use_c + use_t + use_o
                totals["weight"] += d2(trip.loaded_weight)
                if i == 0:
                    totals["loading"] += loading
                    totals["unloading"] += unloading
                    totals["labour"] += labour
                    totals["commission"] += comm
                    totals["toll"] += toll
                    totals["other"] += other
                    totals["total"] += line_total
                rows.append(
                    {
                        "date": day,
                        "trip": trip_route(trip),
                        "weight": trip.loaded_weight,
                        "loading": use_l,
                        "unloading": use_u,
                        "labour": use_lb,
                        "commission": use_c,
                        "toll": use_t,
                        "other": use_o,
                        "total": use_total,
                        "remark": (trip.notes or "").upper(),
                        "is_hold": False,
                    }
                )
        else:
            label = "ABSENT" if day in absent_days else "HOLD"
            if line_total:
                totals["loading"] += loading
                totals["unloading"] += unloading
                totals["labour"] += labour
                totals["commission"] += comm
                totals["toll"] += toll
                totals["other"] += other
                totals["total"] += line_total
            rows.append(
                {
                    "date": day,
                    "trip": label,
                    "weight": ZERO,
                    "loading": loading,
                    "unloading": unloading,
                    "labour": labour,
                    "commission": comm,
                    "toll": toll,
                    "other": other,
                    "total": line_total,
                    "remark": "",
                    "is_hold": True,
                }
            )
        day += timedelta(days=1)

    diesel_total = d2(sum((x.total_amount or 0) for x in diesel))
    diesel_formula = "+".join(money_txt(x.total_amount, blank_zero=False) for x in diesel if d2(x.total_amount))
    labour_repairs = [m for m in maint if d2(m.labour_charges)]
    parts_repairs = [m for m in maint if d2(m.spare_parts_cost)]
    labour_repair_total = d2(sum((x.labour_charges or 0) for x in maint))
    parts_total = d2(sum((x.spare_parts_cost or 0) for x in maint))
    truck_exp_rows = [{"name": k, "amount": v} for k, v in sorted(truck_exp_groups.items())]
    truck_exp_total = d2(sum(v for v in truck_exp_groups.values()))
    fastag_total = d2(sum((x.amount or 0) for x in tolls if x.is_fastag))
    net = (
        totals["total"]
        + day_exp
        + night_exp
        + diesel_total
        + labour_repair_total
        + parts_total
        + truck_exp_total
        + fastag_total
    )
    return {
        "truck": truck,
        "truck_no": truck.registration_no,
        "start": start,
        "end": end,
        "date_range": f"{start.strftime('%d/%m/%Y')} TO {end.strftime('%d/%m/%Y')}",
        "rows": rows,
        "totals": totals,
        "day_exp": day_exp,
        "day_count": len(day_days),
        "night_exp": night_exp,
        "night_count": len(night_days),
        "diesel_bills": diesel,
        "diesel_total": diesel_total,
        "diesel_formula": diesel_formula,
        "repairs": labour_repairs,
        "parts_repairs": parts_repairs,
        "repair_labour_total": labour_repair_total,
        "parts_total": parts_total,
        "truck_exp_rows": truck_exp_rows,
        "truck_exp_total": truck_exp_total,
        "fastag_total": fastag_total,
        "net": net,
    }


def pnl_paper_context(company_id, year, month):
    start, end = month_bounds(year, month)
    prev_start, prev_end = month_bounds(int(year) - 1, month)
    data = pnl_matrix(company_id, start, end)
    prev = pnl_matrix(company_id, prev_start, prev_end)
    display_rows = []
    paper_labels = [
        ("gross_income", "Gross Income"),
        ("diesel", "Diesel Exp"),
        ("repairing", "Repairing Exp"),
        ("voucher", "Voucher Exp"),
        ("insurance", "Insurance"),
        ("loan_emi", "Loan EMI"),
        ("tyre", "TRYE EXP."),
        ("rto", "RTO TEX"),
        ("fastag", "FAST TAG STATEMENT"),
    ]
    for key, label in paper_labels:
        display_rows.append(
            {
                "label": label,
                "values": [data["matrix"][key][t.id] for t in data["trucks"]],
                "total": data["totals"][key],
            }
        )
    display_rows.append(
        {
            "label": "NET TOTAL [+ -]",
            "values": [data["net"][t.id] for t in data["trucks"]],
            "total": data["net_total"],
            "is_net": True,
        }
    )
    prev_nets = [prev["net"].get(t.id, ZERO) for t in data["trucks"]]
    return {
        "start": start,
        "end": end,
        "month_label": start.strftime("%b-%y"),
        "prev_label": prev_start.strftime("%b-%y"),
        "trucks": data["trucks"],
        "truck_codes": [truck_code(t) for t in data["trucks"]],
        "display_rows": display_rows,
        "prev_nets": prev_nets,
        "net_total": data["net_total"],
        "income_total": data["income_total"],
        "expense_total": data["expense_total"],
        "date_range": f"{start.strftime('%d/%m/%Y')} TO {end.strftime('%d/%m/%Y')}",
    }


def invoice_statement_context(company_id, start, end, party=None):
    qs = (
        TransportInvoice.objects.for_company(company_id)
        .filter(invoice_date__gte=start, invoice_date__lte=end)
        .exclude(status="cancelled")
        .select_related("party", "truck")
        .prefetch_related("invoice_trips__trip", "invoice_trips__trip__truck")
        .order_by("invoice_date", "id")
    )
    if party:
        qs = qs.filter(party=party)
    lines = []
    totals = {
        "weight": ZERO,
        "rent": ZERO,
        "labour": ZERO,
        "total": ZERO,
        "advance": ZERO,
        "balance": ZERO,
    }
    n = 0
    for inv in qs:
        linked = list(inv.invoice_trips.all())
        if linked:
            for it in linked:
                n += 1
                trip = it.trip
                rent = d2(trip.freight_amount or inv.freight)
                labour = d2(inv.labour) if n == 1 or len(linked) == 1 else ZERO
                total = rent + labour
                advance = d2(trip.advance_received or 0)
                balance = total - advance
                weight = d2(trip.loaded_weight or inv.weight)
                totals["weight"] += weight
                totals["rent"] += rent
                totals["labour"] += labour
                totals["total"] += total
                totals["advance"] += advance
                totals["balance"] += balance
                lines.append(
                    {
                        "no": n,
                        "date": trip.trip_date or inv.invoice_date,
                        "invoice_no": inv.invoice_no,
                        "lorry": (trip.truck.registration_no if trip.truck_id else "") or (inv.truck.registration_no if inv.truck_id else ""),
                        "from_location": trip.start_location or inv.from_location or "",
                        "destination": trip.destination or inv.destination or "",
                        "taluka": inv.taluka or "",
                        "district": inv.district or "",
                        "weight": weight,
                        "rent": rent,
                        "labour": labour,
                        "total": total,
                        "advance": advance,
                        "balance": balance,
                    }
                )
        else:
            n += 1
            totals["weight"] += d2(inv.weight)
            totals["rent"] += d2(inv.freight)
            totals["labour"] += d2(inv.labour)
            totals["total"] += d2(inv.total_amount)
            totals["advance"] += d2(inv.advance)
            totals["balance"] += d2(inv.balance)
            lines.append(
                {
                    "no": n,
                    "date": inv.invoice_date,
                    "invoice_no": inv.invoice_no,
                    "lorry": inv.truck.registration_no if inv.truck_id else "",
                    "from_location": inv.from_location or "",
                    "destination": inv.destination or "",
                    "taluka": inv.taluka or "",
                    "district": inv.district or "",
                    "weight": inv.weight,
                    "rent": inv.freight,
                    "labour": inv.labour,
                    "total": inv.total_amount,
                    "advance": inv.advance,
                    "balance": inv.balance,
                }
            )
    return {
        "party": party,
        "start": start,
        "end": end,
        "date_range": f"{start.strftime('%d/%m/%Y')} TO {end.strftime('%d/%m/%Y')}",
        "lines": lines,
        "totals": totals,
        "bill_no": f"NT/{start.strftime('%m')}" if not party else "",
    }


def invoice_print_context(invoice):
    linked = list(invoice.invoice_trips.select_related("trip", "trip__truck").all())
    lines = []
    totals = {
        "weight": ZERO,
        "rent": ZERO,
        "labour": ZERO,
        "total": ZERO,
        "advance": ZERO,
        "balance": ZERO,
    }
    if linked:
        for i, it in enumerate(linked, start=1):
            trip = it.trip
            rent = d2(trip.freight_amount or invoice.freight)
            labour = d2(invoice.labour) if len(linked) == 1 else (d2(invoice.labour) if i == 1 else ZERO)
            total = rent + labour
            advance = d2(trip.advance_received or 0)
            if i == 1 and not advance:
                advance = d2(invoice.advance)
            balance = total - advance
            weight = d2(trip.loaded_weight or invoice.weight)
            totals["weight"] += weight
            totals["rent"] += rent
            totals["labour"] += labour
            totals["total"] += total
            totals["advance"] += advance
            totals["balance"] += balance
            lines.append(
                {
                    "no": i,
                    "date": trip.trip_date or invoice.invoice_date,
                    "invoice_no": invoice.invoice_no,
                    "lorry": (trip.truck.registration_no if trip.truck_id else "") or (invoice.truck.registration_no if invoice.truck_id else ""),
                    "from_location": trip.start_location or invoice.from_location or "",
                    "destination": trip.destination or invoice.destination or "",
                    "taluka": invoice.taluka or "",
                    "district": invoice.district or "",
                    "weight": weight,
                    "rent": rent,
                    "labour": labour,
                    "total": total,
                    "advance": advance,
                    "balance": balance,
                }
            )
    else:
        totals = {
            "weight": d2(invoice.weight),
            "rent": d2(invoice.freight),
            "labour": d2(invoice.labour),
            "total": d2(invoice.total_amount),
            "advance": d2(invoice.advance),
            "balance": d2(invoice.balance),
        }
        lines.append(
            {
                "no": 1,
                "date": invoice.invoice_date,
                "invoice_no": invoice.invoice_no,
                "lorry": invoice.truck.registration_no if invoice.truck_id else "",
                "from_location": invoice.from_location or "",
                "destination": invoice.destination or "",
                "taluka": invoice.taluka or "",
                "district": invoice.district or "",
                "weight": invoice.weight,
                "rent": invoice.freight,
                "labour": invoice.labour,
                "total": invoice.total_amount,
                "advance": invoice.advance,
                "balance": invoice.balance,
            }
        )
    return {"obj": invoice, "lines": lines, "totals": totals, "bill_no": invoice.invoice_no}
