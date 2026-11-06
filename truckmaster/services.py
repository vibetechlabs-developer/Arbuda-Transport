import csv
import hashlib
import io
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from truckmaster.models import (
    Booking,
    DieselEntry,
    Driver,
    DriverAdvance,
    DriverSalary,
    ExpenseCategory,
    ExpenseEntry,
    IncomeEntry,
    InvoiceTrip,
    LoadingEntry,
    LoanEmiPayment,
    MaintenanceEntry,
    Party,
    PaymentEntry,
    RoundTrip,
    TollEntry,
    TransportInvoice,
    Trip,
    Truck,
    TruckDocument,
    TruckLoan,
    UnloadingEntry,
    Voucher,
)

ZERO = Decimal("0.00")
MONEY = Decimal("0.01")

DEFAULT_CATEGORIES = [
    ("loading", "Loading", "voucher"),
    ("unloading", "Unloading", "voucher"),
    ("labour", "Labour", "voucher"),
    ("commission", "Commission", "voucher"),
    ("toll", "Toll Tax", "fastag"),
    ("parking", "Parking", "voucher"),
    ("driver_allowance", "Driver Allowance", "voucher"),
    ("food", "Food", "voucher"),
    ("night", "Night Expenses", "voucher"),
    ("challan", "Police / Challan", "other"),
    ("repairing", "Repairing", "repairing"),
    ("spare", "Spare Parts", "repairing"),
    ("tyre", "Tyre Expenses", "tyre"),
    ("insurance", "Insurance", "insurance"),
    ("loan_emi", "Loan EMI", "loan_emi"),
    ("rto", "RTO Tax", "rto"),
    ("fastag", "FASTag", "fastag"),
    ("phone", "Phone", "other"),
    ("other", "Other Expenses", "other"),
]


def d2(value):
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def cid(request):
    return request.session["company_info"]["company_id"]


def actor(request):
    info = request.session.get("company_info") or {}
    return str(info.get("company_name") or info.get("company_id") or "")


def parse_date(value, default=None):
    if not value:
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return default


def month_start(value):
    return date(value.year, value.month, 1)


def next_number(model, company_id, field, prefix):
    year = timezone.localdate().year
    like = f"{prefix}{year}"
    last = (
        model.objects.filter(company_id_id=company_id, **{f"{field}__startswith": like})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(str(last)[len(like) :]) + 1
        except (TypeError, ValueError):
            seq = 1
    return f"{like}{seq:04d}"


def ensure_expense_categories(company_id):
    existing = set(
        ExpenseCategory.objects.filter(company_id_id=company_id).values_list("code", flat=True)
    )
    to_create = [
        ExpenseCategory(
            company_id_id=company_id,
            code=code,
            name=name,
            pnl_bucket=bucket,
            is_system=True,
        )
        for code, name, bucket in DEFAULT_CATEGORIES
        if code not in existing
    ]
    if to_create:
        ExpenseCategory.objects.bulk_create(to_create)


def money_hash(*parts):
    raw = "|".join("" if p is None else str(p).strip().lower() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_freight(rate_type, rate, weight, km=0):
    rate = d2(rate)
    weight = Decimal(str(weight or 0))
    km = Decimal(str(km or 0))
    if rate_type == "per_ton":
        return d2(rate * weight)
    if rate_type == "per_km":
        return d2(rate * km)
    return rate


def _busy_trips(company_id, start, end, truck_id=None, driver_id=None, exclude_trip_id=None):
    """Trips that actually occupy the truck/driver for the requested dates.

    - loading / in_transit: busy until delivered.
    - created (not started): busy only on that trip date, not forever.
    """
    qs = Trip.objects.for_company(company_id).exclude(status__in=["completed", "cancelled", "delivered"])
    if truck_id:
        qs = qs.filter(truck_id=truck_id)
    if driver_id:
        qs = qs.filter(driver_id=driver_id)
    if exclude_trip_id:
        qs = qs.exclude(id=exclude_trip_id)
    if not start:
        return qs.filter(status__in=["loading", "in_transit"])
    end = end or start
    if end < start:
        start, end = end, start
    created_same_day = Q(status="created", trip_date__gte=start, trip_date__lte=end)
    in_progress = Q(status__in=["loading", "in_transit"]) & Q(trip_date__lte=end) & (
        Q(actual_delivery__isnull=True) | Q(actual_delivery__date__gte=start)
    )
    return qs.filter(created_same_day | in_progress)


def find_overlap(company_id, truck_id, driver_id, start, end, exclude_trip_id=None):
    conflicts = []

    def describe(kind, qs):
        trips = list(qs.select_related("truck", "driver")[:3])
        if not trips:
            return
        parts = []
        for trip in trips:
            parts.append(f"{trip.trip_no} ({trip.get_status_display()}, {trip.trip_date.strftime('%d-%m-%Y')})")
        extra = " Complete or cancel that trip first." if any(t.status in ("loading", "in_transit", "created") for t in trips) else ""
        conflicts.append(f"{kind} already on trip {', '.join(parts)}.{extra}")

    if truck_id:
        describe("Truck is", _busy_trips(company_id, start, end, truck_id=truck_id, exclude_trip_id=exclude_trip_id))
    if driver_id:
        describe("Driver is", _busy_trips(company_id, start, end, driver_id=driver_id, exclude_trip_id=exclude_trip_id))
    return conflicts


def recompute_trip_km(trip):
    start = trip.start_odometer or 0
    end = trip.end_odometer or 0
    trip.total_km = max(end - start, 0)
    trip.pending_amount = d2(trip.freight_amount) - d2(trip.advance_received) - d2(trip.payment_received)
    if trip.pending_amount < 0:
        trip.pending_amount = ZERO
    trip.save(update_fields=["total_km", "pending_amount", "updated_at"])


def upsert_income_from_trip(trip, created_by=""):
    if not trip or d2(trip.freight_amount) <= 0:
        return None
    category = "return_freight" if trip.direction == "return" else "freight"
    source_key = f"trip:{trip.id}:freight"
    party = trip.booking.party if trip.booking_id else None
    defaults = {
        "entry_date": trip.trip_date,
        "category": category,
        "truck": trip.truck,
        "trip": trip,
        "booking": trip.booking,
        "party": party,
        "description": f"Freight for {trip.trip_no}",
        "amount": d2(trip.freight_amount),
        "received_amount": d2(trip.advance_received) + d2(trip.payment_received),
        "payment_mode": "credit",
        "created_by": created_by,
        "is_deleted": False,
    }
    defaults["pending_amount"] = d2(defaults["amount"] - defaults["received_amount"])
    obj, _ = IncomeEntry.objects.update_or_create(
        company_id=trip.company_id,
        source_key=source_key,
        defaults=defaults,
    )
    return obj


def apply_payment_to_income(income, amount):
    if not income:
        return
    income.received_amount = d2(income.received_amount) + d2(amount)
    income.pending_amount = max(d2(income.amount) - d2(income.received_amount), ZERO)
    income.save(update_fields=["received_amount", "pending_amount", "updated_at"])


def apply_payment_to_invoice(invoice, amount):
    if not invoice:
        return
    invoice.received_amount = d2(invoice.received_amount) + d2(amount)
    invoice.balance = max(d2(invoice.total_amount) - d2(invoice.advance) - d2(invoice.received_amount), ZERO)
    if invoice.received_amount <= 0 and d2(invoice.advance) <= 0:
        invoice.status = "unpaid"
    elif invoice.balance <= 0:
        invoice.status = "paid"
    else:
        invoice.status = "partial"
    invoice.save(update_fields=["received_amount", "balance", "status", "updated_at"])


def recompute_invoice_totals(invoice):
    invoice.total_amount = d2(invoice.freight) + d2(invoice.labour) + d2(invoice.other_charges)
    invoice.balance = max(d2(invoice.total_amount) - d2(invoice.advance) - d2(invoice.received_amount), ZERO)
    invoice.save(update_fields=["total_amount", "balance", "updated_at"])


def recompute_salary(salary):
    salary.net_salary = (
        d2(salary.basic_salary)
        + d2(salary.trip_incentive)
        + d2(salary.km_incentive)
        + d2(salary.allowances)
        + d2(salary.other_adjustments)
        - d2(salary.deductions)
        - d2(salary.advance_paid)
    )
    salary.pending_salary = max(d2(salary.net_salary) - d2(salary.paid_amount), ZERO)
    salary.save(update_fields=["net_salary", "pending_salary", "updated_at"])


def recompute_maintenance(entry):
    entry.total_amount = d2(entry.labour_charges) + d2(entry.spare_parts_cost) + d2(entry.other_charges)
    entry.save(update_fields=["total_amount", "updated_at"])


def recompute_diesel(entry):
    entry.total_amount = d2(Decimal(str(entry.litres or 0)) * d2(entry.rate_per_litre))
    entry.save(update_fields=["total_amount", "updated_at"])


def recompute_round_trip(round_trip):
    trips = Trip.objects.for_company(round_trip.company_id_id).filter(round_trip=round_trip)
    outbound = trips.filter(direction="outbound")
    returning = trips.filter(direction="return")

    def trip_ids(qs):
        return list(qs.values_list("id", flat=True))

    def sum_field(qs, field):
        return d2(qs.aggregate(t=Sum(field))["t"])

    def diesel_for(ids):
        return d2(DieselEntry.objects.filter(trip_id__in=ids, is_deleted=False).aggregate(t=Sum("total_amount"))["t"])

    def expenses_for(ids):
        exp = d2(ExpenseEntry.objects.filter(trip_id__in=ids, is_deleted=False).aggregate(t=Sum("amount"))["t"])
        toll = d2(TollEntry.objects.filter(trip_id__in=ids, is_deleted=False).aggregate(t=Sum("amount"))["t"])
        maint = d2(MaintenanceEntry.objects.filter(is_deleted=False, truck=round_trip.truck, entry_date__gte=round_trip.start_date).aggregate(t=Sum("total_amount"))["t"])
        return exp + toll

    out_ids = trip_ids(outbound)
    ret_ids = trip_ids(returning)
    round_trip.outbound_weight = outbound.aggregate(t=Sum("loaded_weight"))["t"] or ZERO
    round_trip.return_weight = returning.aggregate(t=Sum("loaded_weight"))["t"] or ZERO
    round_trip.outbound_freight = sum_field(outbound, "freight_amount")
    round_trip.return_freight = sum_field(returning, "freight_amount")
    round_trip.outbound_diesel = diesel_for(out_ids)
    round_trip.return_diesel = diesel_for(ret_ids)
    round_trip.outbound_expenses = expenses_for(out_ids)
    round_trip.return_expenses = expenses_for(ret_ids)
    round_trip.total_income = d2(round_trip.outbound_freight + round_trip.return_freight)
    round_trip.total_expenses = d2(
        round_trip.outbound_diesel
        + round_trip.return_diesel
        + round_trip.outbound_expenses
        + round_trip.return_expenses
    )
    kms = trips.aggregate(t=Sum("total_km"))["t"] or 0
    round_trip.total_km = kms
    if not round_trip.outbound_route:
        first = outbound.order_by("sequence", "id").first()
        if first:
            round_trip.outbound_route = f"{first.start_location} → {first.destination}"
    if not round_trip.return_route:
        first = returning.order_by("sequence", "id").first()
        if first:
            round_trip.return_route = f"{first.start_location} → {first.destination}"
    round_trip.net_profit = d2(round_trip.total_income - round_trip.total_expenses)
    round_trip.save()
    return round_trip


def trip_expense_breakdown(company_id, trip_id):
    expenses = ExpenseEntry.objects.for_company(company_id).filter(trip_id=trip_id)
    diesel = DieselEntry.objects.for_company(company_id).filter(trip_id=trip_id)
    toll = TollEntry.objects.for_company(company_id).filter(trip_id=trip_id)
    loading = LoadingEntry.objects.for_company(company_id).filter(trip_id=trip_id)
    unloading = UnloadingEntry.objects.for_company(company_id).filter(trip_id=trip_id)
    buckets = {
        "diesel": d2(diesel.aggregate(t=Sum("total_amount"))["t"]),
        "loading": d2(loading.aggregate(t=Sum("loading_charges"))["t"]) + d2(expenses.filter(category__code="loading").aggregate(t=Sum("amount"))["t"]),
        "unloading": d2(unloading.aggregate(t=Sum("unloading_charges"))["t"]) + d2(expenses.filter(category__code="unloading").aggregate(t=Sum("amount"))["t"]),
        "labour": d2(loading.aggregate(t=Sum("labour_charges"))["t"]) + d2(unloading.aggregate(t=Sum("labour_charges"))["t"]) + d2(expenses.filter(category__code="labour").aggregate(t=Sum("amount"))["t"]),
        "toll": d2(toll.aggregate(t=Sum("amount"))["t"]),
        "fastag": d2(toll.filter(is_fastag=True).aggregate(t=Sum("amount"))["t"]),
        "commission": d2(expenses.filter(category__code="commission").aggregate(t=Sum("amount"))["t"]),
        "driver_allowance": d2(expenses.filter(category__code="driver_allowance").aggregate(t=Sum("amount"))["t"]),
        "repair": d2(expenses.filter(category__pnl_bucket="repairing").aggregate(t=Sum("amount"))["t"]),
        "parking": d2(expenses.filter(category__code="parking").aggregate(t=Sum("amount"))["t"]),
        "day": d2(expenses.filter(category__code="food").aggregate(t=Sum("amount"))["t"]),
        "night": d2(expenses.filter(category__code="night").aggregate(t=Sum("amount"))["t"]),
        "other": d2(expenses.filter(category__code="other").aggregate(t=Sum("amount"))["t"]),
    }
    buckets["total"] = d2(sum(buckets.values()) - buckets["fastag"])  # fastag already in toll
    return buckets


def build_voucher_from_trip(company_id, trip, voucher_type="trip"):
    b = trip_expense_breakdown(company_id, trip.id)
    maint = MaintenanceEntry.objects.for_company(company_id).filter(truck=trip.truck, entry_date=trip.trip_date)
    return {
        "voucher_type": voucher_type,
        "trip": trip,
        "truck": trip.truck,
        "driver": trip.driver,
        "weight": trip.loaded_weight,
        "loading": b["loading"],
        "unloading": b["unloading"],
        "labour": b["labour"],
        "commission": b["commission"],
        "toll_tax": b["toll"],
        "other_expenses": b["other"],
        "day_expenses": b["day"],
        "night_expenses": b["night"],
        "diesel_bills": b["diesel"],
        "repair_labour": d2(maint.aggregate(t=Sum("labour_charges"))["t"]),
        "repair_parts": d2(maint.aggregate(t=Sum("spare_parts_cost"))["t"]),
        "truck_expenses": d2(ExpenseEntry.objects.for_company(company_id).filter(truck=trip.truck, trip=trip).aggregate(t=Sum("amount"))["t"]),
        "fastag_amount": b["fastag"],
    }


def finalize_voucher_totals(data):
    keys = [
        "loading",
        "unloading",
        "labour",
        "commission",
        "toll_tax",
        "other_expenses",
        "day_expenses",
        "night_expenses",
        "diesel_bills",
        "repair_labour",
        "repair_parts",
        "truck_expenses",
        "fastag_amount",
    ]
    return d2(sum(d2(data.get(k)) for k in keys))


def date_range_filter(qs, field, start, end):
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if end:
        qs = qs.filter(**{f"{field}__lte": end})
    return qs


def dashboard_data(company_id, start=None, end=None, truck_id=None, driver_id=None, party_id=None):
    trucks = Truck.objects.for_company(company_id)
    drivers = Driver.objects.for_company(company_id)
    bookings = Booking.objects.for_company(company_id)
    trips = Trip.objects.for_company(company_id)
    income = IncomeEntry.objects.for_company(company_id)
    diesel = DieselEntry.objects.for_company(company_id)
    expenses = ExpenseEntry.objects.for_company(company_id)
    maint = MaintenanceEntry.objects.for_company(company_id)
    salary = DriverSalary.objects.for_company(company_id)
    invoices = TransportInvoice.objects.for_company(company_id)

    if truck_id:
        trips = trips.filter(truck_id=truck_id)
        bookings = bookings.filter(truck_id=truck_id)
        income = income.filter(truck_id=truck_id)
        diesel = diesel.filter(truck_id=truck_id)
        expenses = expenses.filter(truck_id=truck_id)
        maint = maint.filter(truck_id=truck_id)
        invoices = invoices.filter(truck_id=truck_id)
    if driver_id:
        trips = trips.filter(driver_id=driver_id)
        bookings = bookings.filter(driver_id=driver_id)
        diesel = diesel.filter(driver_id=driver_id)
        expenses = expenses.filter(driver_id=driver_id)
        salary = salary.filter(driver_id=driver_id)
    if party_id:
        bookings = bookings.filter(party_id=party_id)
        income = income.filter(party_id=party_id)
        invoices = invoices.filter(party_id=party_id)

    bookings_f = date_range_filter(bookings, "booking_date", start, end)
    trips_f = date_range_filter(trips, "trip_date", start, end)
    income_f = date_range_filter(income, "entry_date", start, end)
    diesel_f = date_range_filter(diesel, "entry_date", start, end)
    expenses_f = date_range_filter(expenses, "expense_date", start, end)
    maint_f = date_range_filter(maint, "entry_date", start, end)
    salary_f = date_range_filter(salary, "salary_month", start, end)

    today = timezone.localdate()
    month_from = date(today.year, today.month, 1)
    monthly_income = d2(date_range_filter(income, "entry_date", month_from, today).aggregate(t=Sum("amount"))["t"])
    monthly_diesel = d2(date_range_filter(diesel, "entry_date", month_from, today).aggregate(t=Sum("total_amount"))["t"])
    monthly_exp = d2(date_range_filter(expenses, "expense_date", month_from, today).aggregate(t=Sum("amount"))["t"])
    monthly_maint = d2(date_range_filter(maint, "entry_date", month_from, today).aggregate(t=Sum("total_amount"))["t"])
    monthly_salary = d2(date_range_filter(salary, "salary_month", month_from, today).aggregate(t=Sum("net_salary"))["t"])
    monthly_expenses = monthly_diesel + monthly_exp + monthly_maint + monthly_salary

    counts = trucks.aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status="available")),
        on_trip=Count("id", filter=Q(status="on_trip")),
        maintenance=Count("id", filter=Q(status="maintenance")),
        active=Count("id", filter=~Q(status="inactive")),
    )
    outstanding = d2(invoices.exclude(status="paid").aggregate(t=Sum("balance"))["t"]) + d2(
        income.filter(pending_amount__gt=0).aggregate(t=Sum("pending_amount"))["t"]
    )
    total_income = d2(income_f.aggregate(t=Sum("amount"))["t"])
    total_expenses = (
        d2(diesel_f.aggregate(t=Sum("total_amount"))["t"])
        + d2(expenses_f.aggregate(t=Sum("amount"))["t"])
        + d2(maint_f.aggregate(t=Sum("total_amount"))["t"])
        + d2(salary_f.aggregate(t=Sum("net_salary"))["t"])
    )

    chart_income = []
    chart_expense = []
    for i in range(5, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        s = date(y, m, 1)
        e = date(y, m, monthrange(y, m)[1])
        chart_income.append(
            float(d2(IncomeEntry.objects.for_company(company_id).filter(entry_date__gte=s, entry_date__lte=e).aggregate(t=Sum("amount"))["t"]))
        )
        exp = d2(DieselEntry.objects.for_company(company_id).filter(entry_date__gte=s, entry_date__lte=e).aggregate(t=Sum("total_amount"))["t"])
        exp += d2(ExpenseEntry.objects.for_company(company_id).filter(expense_date__gte=s, expense_date__lte=e).aggregate(t=Sum("amount"))["t"])
        exp += d2(MaintenanceEntry.objects.for_company(company_id).filter(entry_date__gte=s, entry_date__lte=e).aggregate(t=Sum("total_amount"))["t"])
        chart_expense.append(float(exp))

    alerts = TruckDocument.objects.for_company(company_id).filter(
        expiry_date__isnull=False, expiry_date__lte=today.replace(year=today.year + 1) if False else today
    )
    # upcoming 30 days
    from datetime import timedelta

    soon = today + timedelta(days=30)
    doc_alerts = TruckDocument.objects.for_company(company_id).filter(expiry_date__gte=today, expiry_date__lte=soon)
    truck_alerts = trucks.filter(
        Q(insurance_expiry__gte=today, insurance_expiry__lte=soon)
        | Q(fitness_expiry__gte=today, fitness_expiry__lte=soon)
        | Q(puc_expiry__gte=today, puc_expiry__lte=soon)
        | Q(permit_expiry__gte=today, permit_expiry__lte=soon)
    )
    license_alerts = drivers.filter(license_expiry__gte=today, license_expiry__lte=soon)

    utilization = []
    for t in trucks:
        t_trips = trips.filter(truck=t).count()
        utilization.append({"truck": t.registration_no, "trips": t_trips})

    status_overview = list(trips_f.values("status").annotate(total=Count("id")))

    return {
        "total_trucks": counts["total"] or 0,
        "active_trucks": counts["active"] or 0,
        "available_trucks": counts["available"] or 0,
        "trucks_on_trip": counts["on_trip"] or 0,
        "trucks_maintenance": counts["maintenance"] or 0,
        "total_drivers": drivers.count(),
        "todays_bookings": bookings.filter(booking_date=today).count(),
        "todays_completed_trips": trips.filter(trip_date=today, status="completed").count(),
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "monthly_diesel": monthly_diesel,
        "monthly_maintenance": monthly_maint,
        "monthly_salary": monthly_salary,
        "outstanding": outstanding,
        "net_profit": d2(monthly_income - monthly_expenses),
        "period_income": total_income,
        "period_expenses": total_expenses,
        "period_profit": d2(total_income - total_expenses),
        "chart_income": chart_income,
        "chart_expense": chart_expense,
        "chart_labels": [],
        "utilization": utilization[:12],
        "status_overview": status_overview,
        "recent_bookings": bookings.order_by("-booking_date", "-id")[:8],
        "doc_alerts": doc_alerts[:10],
        "truck_alerts": truck_alerts[:10],
        "license_alerts": license_alerts[:10],
        "filtered_bookings": bookings_f.count(),
        "filtered_trips": trips_f.count(),
    }


def pnl_matrix(company_id, start, end, truck_ids=None):
    trucks = Truck.objects.for_company(company_id)
    if truck_ids:
        trucks = trucks.filter(id__in=truck_ids)
    trucks = list(trucks)
    rows = [
        ("gross_income", "Gross Income", "income"),
        ("diesel", "Diesel Expense", "diesel"),
        ("repairing", "Repairing Expense", "maint"),
        ("voucher", "Voucher Expense", "voucher"),
        ("insurance", "Insurance", "insurance"),
        ("loan_emi", "Loan EMI", "emi"),
        ("tyre", "Tyre Expense", "tyre"),
        ("rto", "RTO Tax", "rto"),
        ("fastag", "FASTag Statement", "fastag"),
        ("other", "Other Expenses", "other"),
    ]
    matrix = {key: {t.id: ZERO for t in trucks} for key, *_ in rows}
    totals = {key: ZERO for key, *_ in rows}

    def add(bucket, truck_id, amount):
        amount = d2(amount)
        if truck_id not in matrix[bucket]:
            return
        matrix[bucket][truck_id] += amount
        totals[bucket] += amount

    income = IncomeEntry.objects.for_company(company_id).filter(entry_date__gte=start, entry_date__lte=end)
    for row in income.values("truck_id").annotate(t=Sum("amount")):
        add("gross_income", row["truck_id"], row["t"])

    diesel = DieselEntry.objects.for_company(company_id).filter(entry_date__gte=start, entry_date__lte=end)
    for row in diesel.values("truck_id").annotate(t=Sum("total_amount")):
        add("diesel", row["truck_id"], row["t"])

    maint = MaintenanceEntry.objects.for_company(company_id).filter(entry_date__gte=start, entry_date__lte=end)
    for row in maint.values("truck_id").annotate(t=Sum("total_amount")):
        add("repairing", row["truck_id"], row["t"])

    emi = LoanEmiPayment.objects.for_company(company_id).filter(due_date__gte=start, due_date__lte=end)
    for row in emi.values("truck_id").annotate(t=Sum("amount")):
        add("loan_emi", row["truck_id"], row["t"])

    toll = TollEntry.objects.for_company(company_id).filter(entry_datetime__date__gte=start, entry_datetime__date__lte=end)
    for row in toll.values("truck_id").annotate(t=Sum("amount")):
        add("fastag", row["truck_id"], row["t"])

    loading = LoadingEntry.objects.for_company(company_id).filter(entry_date__gte=start, entry_date__lte=end)
    for row in loading.values("truck_id").annotate(
        t=Sum(F("loading_charges") + F("labour_charges"))
    ):
        add("voucher", row["truck_id"], row["t"])
    unloading = UnloadingEntry.objects.for_company(company_id).filter(entry_date__gte=start, entry_date__lte=end)
    for row in unloading.values("truck_id").annotate(
        t=Sum(F("unloading_charges") + F("labour_charges"))
    ):
        add("voucher", row["truck_id"], row["t"])

    salary_qs = DriverSalary.objects.for_company(company_id).filter(
        salary_month__gte=start, salary_month__lte=end
    ).select_related("driver")
    for sal in salary_qs:
        truck_id = sal.driver.assigned_truck_id if sal.driver_id else None
        if not truck_id:
            trip = (
                Trip.objects.for_company(company_id)
                .filter(driver_id=sal.driver_id, trip_date__gte=start, trip_date__lte=end)
                .first()
            )
            truck_id = trip.truck_id if trip else None
        add("other", truck_id, sal.net_salary)

    expenses = ExpenseEntry.objects.for_company(company_id).filter(expense_date__gte=start, expense_date__lte=end)
    for row in expenses.values("truck_id", "category__pnl_bucket").annotate(t=Sum("amount")):
        bucket = row["category__pnl_bucket"] or "other"
        if bucket == "repairing":
            add("repairing", row["truck_id"], row["t"])
        elif bucket == "tyre":
            add("tyre", row["truck_id"], row["t"])
        elif bucket == "rto":
            add("rto", row["truck_id"], row["t"])
        elif bucket == "insurance":
            add("insurance", row["truck_id"], row["t"])
        elif bucket == "loan_emi":
            add("loan_emi", row["truck_id"], row["t"])
        elif bucket == "fastag":
            add("fastag", row["truck_id"], row["t"])
        elif bucket == "voucher":
            add("voucher", row["truck_id"], row["t"])
        else:
            add("other", row["truck_id"], row["t"])

    docs = TruckDocument.objects.for_company(company_id).filter(
        doc_type="insurance", start_date__lte=end
    ).filter(Q(expiry_date__gte=start) | Q(expiry_date__isnull=True))
    for row in docs.values("truck_id").annotate(t=Sum("premium_amount")):
        add("insurance", row["truck_id"], row["t"])

    net = {t.id: ZERO for t in trucks}
    net_total = ZERO
    for t in trucks:
        expense_sum = (
            matrix["diesel"][t.id]
            + matrix["repairing"][t.id]
            + matrix["voucher"][t.id]
            + matrix["insurance"][t.id]
            + matrix["loan_emi"][t.id]
            + matrix["tyre"][t.id]
            + matrix["rto"][t.id]
            + matrix["fastag"][t.id]
            + matrix["other"][t.id]
        )
        net[t.id] = d2(matrix["gross_income"][t.id] - expense_sum)
        net_total += net[t.id]

    return {
        "trucks": trucks,
        "rows": rows,
        "matrix": matrix,
        "totals": totals,
        "net": net,
        "net_total": d2(net_total),
        "income_total": totals["gross_income"],
        "expense_total": d2(sum(totals[k] for k in totals if k != "gross_income")),
    }


def import_fastag_csv(company_id, created_by, uploaded_file, default_truck_id=None):
    content = uploaded_file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    skipped = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        txn = (row.get("transaction_id") or row.get("txn_id") or row.get("fastag_txn_id") or "").strip()
        amount = d2(row.get("amount") or 0)
        plaza = (row.get("plaza") or row.get("toll_plaza") or row.get("plaza_name") or "").strip() or "FASTag"
        dt_raw = row.get("datetime") or row.get("date") or ""
        truck_no = (row.get("truck") or row.get("vehicle") or row.get("truck_no") or "").strip()
        truck = None
        if truck_no:
            truck = Truck.objects.for_company(company_id).filter(registration_no__iexact=truck_no).first()
        if not truck and default_truck_id:
            truck = Truck.objects.for_company(company_id).filter(id=default_truck_id).first()
        if not truck:
            errors.append(f"Row {i}: truck not found")
            continue
        if txn and TollEntry.objects.filter(company_id_id=company_id, fastag_txn_id=txn).exists():
            skipped += 1
            continue
        when = parse_date(dt_raw)
        when_dt = timezone.now()
        if when:
            when_dt = timezone.make_aware(datetime.combine(when, datetime.min.time()))
        if not txn:
            txn = money_hash(company_id, truck.id, plaza, amount, dt_raw, i)
        TollEntry.objects.create(
            company_id_id=company_id,
            truck=truck,
            plaza_name=plaza,
            entry_datetime=when_dt,
            amount=amount,
            fastag_txn_id=txn,
            is_fastag=True,
            created_by=created_by,
        )
        created += 1
    return created, skipped, errors


def can_delete_truck(truck):
    if Trip.objects.filter(truck=truck, is_deleted=False).exists():
        return False, "Truck has trips and cannot be deleted."
    if Booking.objects.filter(truck=truck, is_deleted=False).exclude(status="cancelled").exists():
        return False, "Truck is used in bookings."
    return True, ""


def can_delete_driver(driver):
    if Trip.objects.filter(driver=driver, is_deleted=False).exists():
        return False, "Driver has trips and cannot be deleted."
    return True, ""


@transaction.atomic
def create_trip_from_booking(booking, created_by=""):
    if not booking.truck_id:
        raise ValueError("Assign a truck before creating a trip.")
    conflicts = find_overlap(
        booking.company_id_id,
        booking.truck_id,
        booking.driver_id,
        booking.expected_loading_date or booking.booking_date,
        booking.expected_delivery_date or booking.booking_date,
    )
    if conflicts:
        raise ValueError(" ".join(conflicts))
    trip = Trip.objects.create(
        company_id=booking.company_id,
        trip_no=next_number(Trip, booking.company_id_id, "trip_no", "TR"),
        booking=booking,
        trip_date=booking.expected_loading_date or booking.booking_date,
        truck=booking.truck,
        driver=booking.driver,
        start_location=booking.source_location,
        destination=booking.destination,
        material_name=booking.material_description,
        loaded_weight=booking.total_weight,
        freight_amount=booking.total_freight,
        advance_received=booking.advance_amount,
        pending_amount=booking.balance_amount,
        status="created",
        created_by=created_by,
    )
    booking.truck.status = "on_trip"
    booking.truck.save(update_fields=["status"])
    if booking.driver:
        booking.driver.status = "on_trip"
        booking.driver.save(update_fields=["status"])
    booking.status = "loading_pending"
    booking.save(update_fields=["status", "updated_at"])
    upsert_income_from_trip(trip, created_by)
    return trip
