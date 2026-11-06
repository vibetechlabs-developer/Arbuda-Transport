import json
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from erp.utils.decorators import session_required
from transport.models import T_Contract
from truckmaster.models import (
    Booking,
    DieselEntry,
    Driver,
    DriverAdvance,
    DriverAttendance,
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
    TripLeg,
    Truck,
    TruckDocument,
    TruckLoan,
    UnloadingEntry,
    Voucher,
)
from truckmaster.paper import (
    invoice_print_context,
    invoice_statement_context,
    month_bounds,
    pnl_paper_context,
    vakara_context,
    voucher_month_context,
)
from truckmaster.paper_pdf import invoice_statement_pdf, pnl_pdf, vakara_pdf, voucher_month_pdf
from truckmaster.reports import company_header, export_rows, voucher_pdf
from truckmaster.services import (
    actor,
    apply_payment_to_income,
    apply_payment_to_invoice,
    build_voucher_from_trip,
    calculate_freight,
    can_delete_driver,
    can_delete_truck,
    cid,
    create_trip_from_booking,
    d2,
    dashboard_data,
    date_range_filter,
    ensure_expense_categories,
    finalize_voucher_totals,
    find_overlap,
    import_fastag_csv,
    money_hash,
    month_start,
    next_number,
    parse_date,
    pnl_matrix,
    recompute_diesel,
    recompute_invoice_totals,
    recompute_maintenance,
    recompute_round_trip,
    recompute_salary,
    recompute_trip_km,
    trip_expense_breakdown,
    upsert_income_from_trip,
)

ZERO = Decimal("0.00")


def _company(request):
    return cid(request)


def _base_ctx(request, **extra):
    company_id = _company(request)
    name, gst, address = company_header(company_id)
    ctx = {
        "tm_trucks": Truck.objects.for_company(company_id),
        "tm_drivers": Driver.objects.for_company(company_id),
        "tm_parties": Party.objects.for_company(company_id),
        "tm_path": request.path,
        "company_name": name,
        "company_gst": gst,
        "company_address": address,
    }
    ctx.update(extra)
    return ctx


def _paper_urls(request, back_url):
    path = request.get_full_path()
    sep = "&" if "?" in path else "?"
    pdf_url = path if "download=" in path else f"{path}{sep}download=1"
    return {"back_url": back_url, "pdf_url": pdf_url}


def _paginate(request, qs, per_page=20):
    paginator = Paginator(qs, per_page)
    return paginator.get_page(request.GET.get("page") or 1)


def _parse_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed)
        return parsed
    except (TypeError, ValueError):
        return None


def _dec(value, default="0"):
    try:
        if value in (None, ""):
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _filters(request, qs, search_fields, date_field=None):
    q = (request.GET.get("q") or "").strip()
    start = parse_date(request.GET.get("start_date"))
    end = parse_date(request.GET.get("end_date"))
    truck_id = request.GET.get("truck")
    driver_id = request.GET.get("driver")
    party_id = request.GET.get("party")
    status = request.GET.get("status")
    if q and search_fields:
        query = Q()
        for field in search_fields:
            query |= Q(**{f"{field}__icontains": q})
        qs = qs.filter(query)
    if date_field:
        qs = date_range_filter(qs, date_field, start, end)
    if truck_id and any(f.name == "truck" for f in qs.model._meta.fields):
        qs = qs.filter(truck_id=truck_id)
    if driver_id and any(f.name == "driver" for f in qs.model._meta.fields):
        qs = qs.filter(driver_id=driver_id)
    if party_id and any(f.name == "party" for f in qs.model._meta.fields):
        qs = qs.filter(party_id=party_id)
    if status and any(f.name == "status" for f in qs.model._meta.fields):
        qs = qs.filter(status=status)
    return qs, start, end


def _export_if_requested(request, qs, filename, columns):
    fmt = (request.GET.get("export") or "").lower()
    if fmt not in ("csv", "pdf", "xls", "xlsx", "excel"):
        return None
    rows = []
    for obj in qs[:5000]:
        row = []
        for col in columns:
            val = obj
            for part in col[0].split("."):
                val = getattr(val, part, "") if val is not None else ""
            if hasattr(val, "strftime"):
                val = val.strftime("%d-%m-%Y")
            row.append(val)
        rows.append(row)
    return export_rows(request, filename, [c[1] for c in columns], rows)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@session_required
def truck_dashboard(request):
    company_id = _company(request)
    ensure_expense_categories(company_id)
    start = parse_date(request.GET.get("start_date"))
    end = parse_date(request.GET.get("end_date"))
    data = dashboard_data(
        company_id,
        start=start,
        end=end,
        truck_id=request.GET.get("truck") or None,
        driver_id=request.GET.get("driver") or None,
        party_id=request.GET.get("party") or None,
    )
    today = timezone.localdate()
    labels = []
    for i in range(5, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        labels.append(date(y, m, 1).strftime("%b %Y"))
    data["chart_labels"] = json.dumps(labels)
    data["chart_income"] = json.dumps(data["chart_income"])
    data["chart_expense"] = json.dumps(data["chart_expense"])
    status_labels = dict(Trip.STATUS_CHOICES)
    for row in data.get("status_overview") or []:
        row["label"] = status_labels.get(row.get("status"), row.get("status"))
    return render(request, "truckmaster/dashboard.html", _base_ctx(request, **data, start_date=start, end_date=end))


# ---------------------------------------------------------------------------
# Generic list/form helpers used by most masters
# ---------------------------------------------------------------------------

def _list_view(request, model, template, title, columns, search_fields, date_field, create_url, extra=None, entity=""):
    company_id = _company(request)
    qs = model.objects.for_company(company_id)
    qs, start, end = _filters(request, qs, search_fields, date_field)
    exported = _export_if_requested(request, qs, title.lower().replace(" ", "_"), columns)
    if exported:
        return exported
    ctx = _base_ctx(
        request,
        title=title,
        page_obj=_paginate(request, qs),
        columns=columns,
        create_url=create_url,
        entity=entity,
        edit_name=f"tm-{entity}-edit" if entity and entity != "payment" else "",
        detail_name=f"tm-{entity}-detail" if entity else "",
        delete_name=f"tm-{entity}-delete" if entity else "",
        start_date=request.GET.get("start_date", ""),
        end_date=request.GET.get("end_date", ""),
        q=request.GET.get("q", ""),
        status=request.GET.get("status", ""),
        statuses=getattr(model, "STATUS_CHOICES", None),
        has_detail=entity in {"truck", "driver", "booking", "trip", "round", "invoice", "voucher"},
        has_delete=entity in {"truck", "driver", "party", "booking", "trip"},
    )
    if extra:
        ctx.update(extra)
    return render(request, template, ctx)


def _assign_common(obj, request, company_id):
    obj.company_id_id = company_id
    obj.created_by = actor(request)
    if "is_deleted" in [f.name for f in obj._meta.fields]:
        obj.is_deleted = False


# ---------------------------------------------------------------------------
# Truck
# ---------------------------------------------------------------------------

@session_required
def truck_list(request):
    columns = [
        ("registration_no", "Reg. No"),
        ("name_model", "Model"),
        ("vehicle_type", "Type"),
        ("capacity_ton", "Capacity"),
        ("ownership_type", "Ownership"),
        ("status", "Status"),
        ("assigned_driver.name", "Driver"),
        ("odometer", "Odometer"),
        ("insurance_expiry", "Insurance Exp."),
    ]
    return _list_view(
        request,
        Truck,
        "truckmaster/crud_list.html",
        "Truck Master",
        columns,
        ["registration_no", "name_model", "vehicle_type", "chassis_no"],
        None,
        reverse("tm-truck-form"),
        entity="truck",
    )


@session_required
def truck_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Truck.objects.for_company(company_id), pk=pk) if pk else Truck(company_id_id=company_id)
    if request.method == "POST":
        obj.registration_no = (request.POST.get("registration_no") or "").strip().upper()
        obj.name_model = request.POST.get("name_model")
        obj.vehicle_type = request.POST.get("vehicle_type")
        obj.category = request.POST.get("category")
        obj.capacity_ton = _dec(request.POST.get("capacity_ton"))
        obj.axles = _int(request.POST.get("axles"))
        obj.chassis_no = request.POST.get("chassis_no")
        obj.engine_no = request.POST.get("engine_no")
        obj.fuel_type = request.POST.get("fuel_type") or "diesel"
        obj.purchase_date = parse_date(request.POST.get("purchase_date"))
        obj.purchase_price = _dec(request.POST.get("purchase_price"))
        obj.ownership_type = request.POST.get("ownership_type") or "owned"
        obj.insurance_provider = request.POST.get("insurance_provider")
        obj.insurance_policy_no = request.POST.get("insurance_policy_no")
        obj.insurance_expiry = parse_date(request.POST.get("insurance_expiry"))
        obj.fitness_expiry = parse_date(request.POST.get("fitness_expiry"))
        obj.puc_expiry = parse_date(request.POST.get("puc_expiry"))
        obj.permit_expiry = parse_date(request.POST.get("permit_expiry"))
        obj.rc_number = request.POST.get("rc_number")
        obj.odometer = _int(request.POST.get("odometer"))
        driver_id = request.POST.get("assigned_driver")
        obj.assigned_driver_id = driver_id or None
        obj.status = request.POST.get("status") or "available"
        obj.notes = request.POST.get("notes")
        if request.FILES.get("rc_attachment"):
            obj.rc_attachment = request.FILES["rc_attachment"]
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, "Truck saved.")
            return redirect("tm-truck-list")
        except IntegrityError:
            messages.error(request, "A truck with this registration number already exists.")
    return render(
        request,
        "truckmaster/truck_form.html",
        _base_ctx(request, obj=obj, drivers=Driver.objects.for_company(company_id)),
    )


@session_required
def truck_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Truck.objects.for_company(company_id), pk=pk)
    trips = Trip.objects.for_company(company_id).filter(truck=obj)
    income = IncomeEntry.objects.for_company(company_id).filter(truck=obj)
    expenses = ExpenseEntry.objects.for_company(company_id).filter(truck=obj)
    diesel = DieselEntry.objects.for_company(company_id).filter(truck=obj)
    maint = MaintenanceEntry.objects.for_company(company_id).filter(truck=obj)
    docs = TruckDocument.objects.for_company(company_id).filter(truck=obj)
    return render(
        request,
        "truckmaster/truck_detail.html",
        _base_ctx(
            request,
            obj=obj,
            trips=trips[:50],
            income=income[:50],
            expenses=expenses[:50],
            diesel=diesel[:50],
            maint=maint[:50],
            docs=docs,
            income_total=d2(income.aggregate(t=Sum("amount"))["t"]),
            expense_total=d2(expenses.aggregate(t=Sum("amount"))["t"]) + d2(diesel.aggregate(t=Sum("total_amount"))["t"]),
        ),
    )


@session_required
@require_POST
def truck_delete(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Truck.objects.for_company(company_id), pk=pk)
    ok, reason = can_delete_truck(obj)
    if not ok:
        messages.error(request, reason)
        return redirect("tm-truck-list")
    obj.soft_delete()
    messages.success(request, "Truck deleted.")
    return redirect("tm-truck-list")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@session_required
def driver_list(request):
    columns = [
        ("name", "Name"),
        ("mobile", "Mobile"),
        ("license_no", "License No"),
        ("license_expiry", "License Expiry"),
        ("salary_type", "Salary Type"),
        ("assigned_truck.registration_no", "Truck"),
        ("status", "Status"),
    ]
    return _list_view(
        request,
        Driver,
        "truckmaster/crud_list.html",
        "Driver Master",
        columns,
        ["name", "mobile", "license_no"],
        None,
        reverse("tm-driver-form"),
        entity="driver",
    )


@session_required
def driver_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Driver.objects.for_company(company_id), pk=pk) if pk else Driver(company_id_id=company_id)
    if request.method == "POST":
        obj.name = (request.POST.get("name") or "").strip()
        obj.mobile = request.POST.get("mobile")
        obj.alternate_mobile = request.POST.get("alternate_mobile")
        obj.address = request.POST.get("address")
        obj.date_of_birth = parse_date(request.POST.get("date_of_birth"))
        obj.joining_date = parse_date(request.POST.get("joining_date"))
        obj.license_no = (request.POST.get("license_no") or "").strip()
        obj.license_type = request.POST.get("license_type")
        obj.license_expiry = parse_date(request.POST.get("license_expiry"))
        obj.aadhaar_no = request.POST.get("aadhaar_no")
        obj.pan_no = request.POST.get("pan_no")
        obj.salary_type = request.POST.get("salary_type") or "monthly"
        obj.basic_salary = _dec(request.POST.get("basic_salary"))
        obj.allowances = _dec(request.POST.get("allowances"))
        obj.assigned_truck_id = request.POST.get("assigned_truck") or None
        obj.emergency_contact = request.POST.get("emergency_contact")
        obj.status = request.POST.get("status") or "active"
        if request.FILES.get("document"):
            obj.document = request.FILES["document"]
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, "Driver saved.")
            return redirect("tm-driver-list")
        except IntegrityError:
            messages.error(request, "A driver with this license number already exists.")
    return render(
        request,
        "truckmaster/driver_form.html",
        _base_ctx(request, obj=obj, trucks=Truck.objects.for_company(company_id)),
    )


@session_required
def driver_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Driver.objects.for_company(company_id), pk=pk)
    if request.method == "POST" and request.POST.get("attendance_date"):
        try:
            DriverAttendance.objects.create(
                company_id_id=company_id,
                driver=obj,
                attendance_date=parse_date(request.POST.get("attendance_date"), timezone.localdate()),
                status=request.POST.get("attendance_status") or "present",
                remarks=request.POST.get("attendance_remarks"),
                created_by=actor(request),
            )
            messages.success(request, "Attendance saved.")
        except IntegrityError:
            messages.error(request, "Attendance already exists for that date.")
        return redirect("tm-driver-detail", pk=obj.id)
    return render(
        request,
        "truckmaster/driver_detail.html",
        _base_ctx(
            request,
            obj=obj,
            trips=Trip.objects.for_company(company_id).filter(driver=obj)[:50],
            salaries=DriverSalary.objects.for_company(company_id).filter(driver=obj)[:24],
            advances=DriverAdvance.objects.for_company(company_id).filter(driver=obj)[:50],
            attendance=DriverAttendance.objects.for_company(company_id).filter(driver=obj)[:40],
            pending_salary=d2(
                DriverSalary.objects.for_company(company_id).filter(driver=obj).aggregate(t=Sum("pending_salary"))["t"]
            ),
        ),
    )


@session_required
@require_POST
def driver_delete(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Driver.objects.for_company(company_id), pk=pk)
    ok, reason = can_delete_driver(obj)
    if not ok:
        messages.error(request, reason)
        return redirect("tm-driver-list")
    obj.soft_delete()
    messages.success(request, "Driver deleted.")
    return redirect("tm-driver-list")


# ---------------------------------------------------------------------------
# Party
# ---------------------------------------------------------------------------

@session_required
def party_list(request):
    if request.GET.get("import_contracts") == "1":
        company_id = _company(request)
        created = 0
        for contract in T_Contract.objects.filter(company_id_id=company_id):
            _, was = Party.objects.get_or_create(
                company_id_id=company_id,
                name=contract.company_name,
                defaults={
                    "gstin": contract.gst_number,
                    "contact_number": contract.c_number,
                    "address": contract.billing_address,
                    "city": contract.billing_city,
                    "state": contract.billing_state,
                    "contract": contract,
                    "is_deleted": False,
                },
            )
            created += 1 if was else 0
        messages.success(request, f"Imported {created} parties from existing contracts.")
        return redirect("tm-party-list")
    columns = [
        ("name", "Party Name"),
        ("contact_number", "Contact"),
        ("gstin", "GSTIN"),
        ("city", "City"),
        ("contract.contract_no", "Linked Contract"),
    ]
    return _list_view(
        request,
        Party,
        "truckmaster/party_list.html",
        "Party / Customer Management",
        columns,
        ["name", "gstin", "contact_number"],
        None,
        reverse("tm-party-form"),
        entity="party",
    )


@session_required
def party_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Party.objects.for_company(company_id), pk=pk) if pk else Party(company_id_id=company_id)
    if request.method == "POST":
        obj.name = (request.POST.get("name") or "").strip()
        obj.contact_number = request.POST.get("contact_number")
        obj.gstin = request.POST.get("gstin")
        obj.address = request.POST.get("address")
        obj.city = request.POST.get("city")
        obj.state = request.POST.get("state")
        obj.contract_id = request.POST.get("contract") or None
        obj.notes = request.POST.get("notes")
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, "Party saved.")
            return redirect("tm-party-list")
        except IntegrityError:
            messages.error(request, "Party with this name already exists.")
    return render(
        request,
        "truckmaster/party_form.html",
        _base_ctx(request, obj=obj, contracts=T_Contract.objects.filter(company_id_id=company_id)),
    )


@session_required
@require_POST
def party_delete(request, pk):
    obj = get_object_or_404(Party.objects.for_company(_company(request)), pk=pk)
    if Booking.objects.filter(party=obj, is_deleted=False).exists():
        messages.error(request, "Party has bookings and cannot be deleted.")
        return redirect("tm-party-list")
    obj.soft_delete()
    messages.success(request, "Party deleted.")
    return redirect("tm-party-list")


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

@session_required
def booking_list(request):
    columns = [
        ("booking_no", "Booking No"),
        ("booking_date", "Date"),
        ("party.name", "Party"),
        ("source_location", "From"),
        ("destination", "To"),
        ("truck.registration_no", "Truck"),
        ("total_freight", "Freight"),
        ("status", "Status"),
    ]
    return _list_view(
        request,
        Booking,
        "truckmaster/crud_list.html",
        "Truck Booking",
        columns,
        ["booking_no", "source_location", "destination", "party__name"],
        "booking_date",
        reverse("tm-booking-form"),
        entity="booking",
    )


@session_required
def booking_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Booking.objects.for_company(company_id), pk=pk) if pk else Booking(company_id_id=company_id)
    if request.method == "POST":
        obj.booking_date = parse_date(request.POST.get("booking_date"), timezone.localdate())
        obj.party_id = request.POST.get("party")
        obj.contact_number = request.POST.get("contact_number")
        obj.source_location = request.POST.get("source_location")
        obj.destination = request.POST.get("destination")
        obj.loading_point = request.POST.get("loading_point")
        obj.unloading_point = request.POST.get("unloading_point")
        obj.material_description = request.POST.get("material_description")
        obj.material_category = request.POST.get("material_category")
        obj.total_weight = _dec(request.POST.get("total_weight"))
        obj.weight_unit = request.POST.get("weight_unit") or "MT"
        obj.freight_rate = _dec(request.POST.get("freight_rate"))
        obj.rate_type = request.POST.get("rate_type") or "fixed"
        km = _int(request.POST.get("km"))
        obj.total_freight = calculate_freight(obj.rate_type, obj.freight_rate, obj.total_weight, km)
        obj.advance_amount = _dec(request.POST.get("advance_amount"))
        obj.balance_amount = d2(obj.total_freight - obj.advance_amount)
        obj.payment_mode = request.POST.get("payment_mode") or "cash"
        obj.expected_loading_date = parse_date(request.POST.get("expected_loading_date"))
        obj.expected_delivery_date = parse_date(request.POST.get("expected_delivery_date"))
        obj.truck_id = request.POST.get("truck") or None
        obj.driver_id = request.POST.get("driver") or None
        obj.remarks = request.POST.get("remarks")
        if request.FILES.get("attachment"):
            obj.attachment = request.FILES["attachment"]
        if not obj.booking_no:
            obj.booking_no = next_number(Booking, company_id, "booking_no", "BK")
        if not obj.status:
            obj.status = "draft"
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, f"Booking {obj.booking_no} saved. Freight {obj.total_freight}.")
            return redirect("tm-booking-detail", pk=obj.id)
        except IntegrityError:
            messages.error(request, "Could not save booking.")
    return render(request, "truckmaster/booking_form.html", _base_ctx(request, obj=obj))


@session_required
def booking_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Booking.objects.for_company(company_id), pk=pk)
    return render(
        request,
        "truckmaster/booking_detail.html",
        _base_ctx(request, obj=obj, trips=obj.trips.filter(is_deleted=False)),
    )


@session_required
@require_POST
def booking_action(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Booking.objects.for_company(company_id), pk=pk)
    action = request.POST.get("action")
    try:
        if action == "confirm":
            obj.status = "confirmed"
            obj.save(update_fields=["status", "updated_at"])
            messages.success(request, "Booking confirmed.")
        elif action == "assign":
            obj.truck_id = request.POST.get("truck") or obj.truck_id
            obj.driver_id = request.POST.get("driver") or obj.driver_id
            if not obj.truck_id:
                raise ValueError("Select a truck.")
            conflicts = find_overlap(
                company_id,
                obj.truck_id,
                obj.driver_id,
                obj.expected_loading_date or obj.booking_date,
                obj.expected_delivery_date or obj.booking_date,
            )
            if conflicts:
                raise ValueError(" ".join(conflicts))
            obj.status = "truck_assigned"
            obj.save()
            messages.success(request, "Truck and driver assigned.")
        elif action == "create_trip":
            trip = create_trip_from_booking(obj, actor(request))
            messages.success(request, f"Trip {trip.trip_no} created.")
            return redirect("tm-trip-detail", pk=trip.id)
        elif action == "cancel":
            obj.status = "cancelled"
            obj.save(update_fields=["status", "updated_at"])
            messages.success(request, "Booking cancelled.")
        else:
            messages.error(request, "Unknown action.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("tm-booking-detail", pk=obj.id)


@session_required
@require_POST
def booking_delete(request, pk):
    obj = get_object_or_404(Booking.objects.for_company(_company(request)), pk=pk)
    if obj.trips.filter(is_deleted=False).exists():
        messages.error(request, "Booking has trips. Cancel instead of deleting.")
        return redirect("tm-booking-list")
    obj.soft_delete()
    messages.success(request, "Booking deleted.")
    return redirect("tm-booking-list")


# ---------------------------------------------------------------------------
# Trip
# ---------------------------------------------------------------------------

@session_required
def trip_list(request):
    columns = [
        ("trip_no", "Trip ID"),
        ("trip_date", "Date"),
        ("truck.registration_no", "Truck"),
        ("driver.name", "Driver"),
        ("start_location", "From"),
        ("destination", "To"),
        ("freight_amount", "Freight"),
        ("status", "Status"),
    ]
    return _list_view(
        request,
        Trip,
        "truckmaster/crud_list.html",
        "Trip Management",
        columns,
        ["trip_no", "start_location", "destination", "truck__registration_no"],
        "trip_date",
        reverse("tm-trip-form"),
        entity="trip",
    )


@session_required
def trip_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Trip.objects.for_company(company_id), pk=pk) if pk else Trip(company_id_id=company_id)
    if request.method == "POST":
        obj.trip_date = parse_date(request.POST.get("trip_date"), timezone.localdate())
        obj.booking_id = request.POST.get("booking") or None
        obj.round_trip_id = request.POST.get("round_trip") or None
        obj.direction = request.POST.get("direction") or "single"
        obj.sequence = _int(request.POST.get("sequence"), 1)
        obj.truck_id = request.POST.get("truck")
        obj.driver_id = request.POST.get("driver") or None
        obj.start_location = request.POST.get("start_location")
        obj.destination = request.POST.get("destination")
        obj.actual_start = _parse_dt(request.POST.get("actual_start"))
        obj.actual_delivery = _parse_dt(request.POST.get("actual_delivery"))
        obj.start_odometer = _int(request.POST.get("start_odometer"))
        obj.end_odometer = _int(request.POST.get("end_odometer"))
        obj.material_name = request.POST.get("material_name")
        obj.loaded_weight = _dec(request.POST.get("loaded_weight"))
        obj.unloaded_weight = _dec(request.POST.get("unloaded_weight"))
        obj.freight_amount = _dec(request.POST.get("freight_amount"))
        obj.advance_received = _dec(request.POST.get("advance_received"))
        obj.payment_received = _dec(request.POST.get("payment_received"))
        obj.is_empty_return = request.POST.get("is_empty_return") == "on"
        obj.notes = request.POST.get("notes")
        obj.status = request.POST.get("status") or obj.status or "created"
        if not obj.trip_no:
            obj.trip_no = next_number(Trip, company_id, "trip_no", "TR")
        conflicts = find_overlap(
            company_id,
            obj.truck_id,
            obj.driver_id,
            obj.trip_date,
            parse_date(request.POST.get("end_date"), obj.trip_date),
            exclude_trip_id=obj.id if obj.id else None,
        )
        if conflicts:
            messages.error(request, " ".join(conflicts))
        else:
            _assign_common(obj, request, company_id)
            obj.save()
            recompute_trip_km(obj)
            upsert_income_from_trip(obj, actor(request))
            if obj.round_trip_id:
                recompute_round_trip(obj.round_trip)
            messages.success(request, f"Trip {obj.trip_no} saved.")
            return redirect("tm-trip-detail", pk=obj.id)
    return render(
        request,
        "truckmaster/trip_form.html",
        _base_ctx(
            request,
            obj=obj,
            bookings=Booking.objects.for_company(company_id).exclude(status="cancelled"),
            round_trips=RoundTrip.objects.for_company(company_id),
        ),
    )


@session_required
def trip_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Trip.objects.for_company(company_id), pk=pk)
    breakdown = trip_expense_breakdown(company_id, obj.id)
    return render(
        request,
        "truckmaster/trip_detail.html",
        _base_ctx(
            request,
            obj=obj,
            breakdown=breakdown,
            profit=d2(obj.freight_amount) - d2(breakdown["total"]),
            legs=obj.legs.filter(is_deleted=False),
            loadings=obj.loadings.filter(is_deleted=False),
            unloadings=obj.unloadings.filter(is_deleted=False),
            diesel=DieselEntry.objects.for_company(company_id).filter(trip=obj),
            expenses=ExpenseEntry.objects.for_company(company_id).filter(trip=obj),
            tolls=TollEntry.objects.for_company(company_id).filter(trip=obj),
        ),
    )


@session_required
@require_POST
def trip_action(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Trip.objects.for_company(company_id), pk=pk)
    action = request.POST.get("action")
    if action == "loading":
        obj.status = "loading"
        if obj.booking_id:
            obj.booking.status = "loading_pending"
            obj.booking.save(update_fields=["status"])
    elif action == "transit":
        obj.status = "in_transit"
        obj.actual_start = timezone.now()
        if obj.booking_id:
            obj.booking.status = "in_transit"
            obj.booking.save(update_fields=["status"])
    elif action == "deliver":
        obj.status = "delivered"
        obj.actual_delivery = timezone.now()
        if obj.booking_id:
            obj.booking.status = "delivered"
            obj.booking.save(update_fields=["status"])
    elif action == "complete":
        obj.status = "completed"
        recompute_trip_km(obj)
        upsert_income_from_trip(obj, actor(request))
        if obj.truck_id:
            obj.truck.status = "available"
            if obj.end_odometer:
                obj.truck.odometer = obj.end_odometer
            obj.truck.save()
        if obj.driver_id:
            obj.driver.status = "active"
            obj.driver.save(update_fields=["status"])
        if obj.booking_id:
            pending = d2(obj.pending_amount)
            obj.booking.status = "completed" if pending <= 0 else "payment_pending"
            obj.booking.save(update_fields=["status"])
        if obj.round_trip_id:
            recompute_round_trip(obj.round_trip)
        messages.success(request, "Trip completed.")
    obj.save()
    return redirect("tm-trip-detail", pk=obj.id)


@session_required
@require_POST
def trip_leg_add(request, pk):
    company_id = _company(request)
    trip = get_object_or_404(Trip.objects.for_company(company_id), pk=pk)
    seq = trip.legs.filter(is_deleted=False).count() + 1
    TripLeg.objects.create(
        company_id_id=company_id,
        trip=trip,
        sequence=seq,
        from_location=request.POST.get("from_location"),
        to_location=request.POST.get("to_location"),
        loading_point=request.POST.get("loading_point"),
        unloading_point=request.POST.get("unloading_point"),
        distance_km=_int(request.POST.get("distance_km")),
        weight=_dec(request.POST.get("weight")),
        freight=_dec(request.POST.get("freight")),
        created_by=actor(request),
    )
    messages.success(request, "Trip leg added.")
    return redirect("tm-trip-detail", pk=pk)


@session_required
@require_POST
def trip_delete(request, pk):
    obj = get_object_or_404(Trip.objects.for_company(_company(request)), pk=pk)
    if obj.status == "completed":
        messages.error(request, "Completed trips cannot be deleted.")
        return redirect("tm-trip-list")
    obj.soft_delete()
    messages.success(request, "Trip deleted.")
    return redirect("tm-trip-list")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

@session_required
def round_trip_list(request):
    columns = [
        ("round_trip_no", "Round Trip ID"),
        ("start_date", "Start"),
        ("truck.registration_no", "Truck"),
        ("outbound_route", "Outbound"),
        ("return_route", "Return"),
        ("total_income", "Income"),
        ("total_expenses", "Expenses"),
        ("net_profit", "Net"),
    ]
    return _list_view(
        request,
        RoundTrip,
        "truckmaster/crud_list.html",
        "Round Trip Management",
        columns,
        ["round_trip_no", "outbound_route", "return_route"],
        "start_date",
        reverse("tm-round-form"),
        entity="round",
    )


@session_required
def round_trip_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(RoundTrip.objects.for_company(company_id), pk=pk) if pk else RoundTrip(company_id_id=company_id)
    if request.method == "POST":
        obj.truck_id = request.POST.get("truck")
        obj.driver_id = request.POST.get("driver") or None
        obj.start_date = parse_date(request.POST.get("start_date"), timezone.localdate())
        obj.end_date = parse_date(request.POST.get("end_date"))
        obj.starting_km = _int(request.POST.get("starting_km"))
        obj.ending_km = _int(request.POST.get("ending_km"))
        obj.outbound_route = request.POST.get("outbound_route")
        obj.return_route = request.POST.get("return_route")
        obj.notes = request.POST.get("notes")
        if not obj.round_trip_no:
            obj.round_trip_no = next_number(RoundTrip, company_id, "round_trip_no", "RT")
        _assign_common(obj, request, company_id)
        obj.save()
        recompute_round_trip(obj)
        messages.success(request, f"Round trip {obj.round_trip_no} saved.")
        return redirect("tm-round-detail", pk=obj.id)
    return render(request, "truckmaster/round_trip_form.html", _base_ctx(request, obj=obj))


@session_required
def round_trip_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(RoundTrip.objects.for_company(company_id), pk=pk)
    recompute_round_trip(obj)
    return render(
        request,
        "truckmaster/round_trip_detail.html",
        _base_ctx(
            request,
            obj=obj,
            outbound=obj.trips.filter(is_deleted=False, direction="outbound"),
            returning=obj.trips.filter(is_deleted=False, direction="return"),
            linkable_trips=Trip.objects.for_company(company_id).filter(round_trip__isnull=True).exclude(status="cancelled"),
            bookings=Booking.objects.for_company(company_id).exclude(status__in=["cancelled", "completed"]),
        ),
    )


@session_required
@require_POST
def round_trip_link_trip(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(RoundTrip.objects.for_company(company_id), pk=pk)
    trip = get_object_or_404(Trip.objects.for_company(company_id), pk=request.POST.get("trip_id"))
    trip.round_trip = obj
    trip.direction = request.POST.get("direction") or "return"
    trip.sequence = obj.trips.filter(direction=trip.direction).count() + 1
    trip.save(update_fields=["round_trip", "direction", "sequence"])
    recompute_round_trip(obj)
    messages.success(request, f"{trip.trip_no} linked as {trip.direction}.")
    return redirect("tm-round-detail", pk=pk)


# ---------------------------------------------------------------------------
# Income / diesel / expenses / loading / toll
# ---------------------------------------------------------------------------

@session_required
def income_list(request):
    columns = [
        ("entry_date", "Date"),
        ("category", "Category"),
        ("party.name", "Party"),
        ("truck.registration_no", "Truck"),
        ("trip.trip_no", "Trip"),
        ("amount", "Amount"),
        ("received_amount", "Received"),
        ("pending_amount", "Pending"),
    ]
    return _list_view(request, IncomeEntry, "truckmaster/crud_list.html", "Freight & Income", columns, ["description", "invoice_ref"], "entry_date", reverse("tm-income-form"), entity="income")


@session_required
def income_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(IncomeEntry.objects.for_company(company_id), pk=pk) if pk else IncomeEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.entry_date = parse_date(request.POST.get("entry_date"), timezone.localdate())
        obj.category = request.POST.get("category") or "freight"
        obj.truck_id = request.POST.get("truck") or None
        obj.trip_id = request.POST.get("trip") or None
        obj.booking_id = request.POST.get("booking") or None
        obj.party_id = request.POST.get("party") or None
        obj.description = request.POST.get("description")
        obj.amount = _dec(request.POST.get("amount"))
        obj.received_amount = _dec(request.POST.get("received_amount"))
        obj.pending_amount = max(d2(obj.amount - obj.received_amount), ZERO)
        obj.payment_mode = request.POST.get("payment_mode") or "credit"
        obj.invoice_ref = request.POST.get("invoice_ref")
        if not obj.source_key:
            obj.source_key = f"manual:{timezone.now().timestamp()}"
        _assign_common(obj, request, company_id)
        obj.save()
        messages.success(request, "Income saved.")
        return redirect("tm-income-list")
    return render(
        request,
        "truckmaster/income_form.html",
        _base_ctx(request, obj=obj, trips=Trip.objects.for_company(company_id), bookings=Booking.objects.for_company(company_id)),
    )


@session_required
def diesel_list(request):
    columns = [
        ("entry_date", "Date"),
        ("truck.registration_no", "Truck"),
        ("driver.name", "Driver"),
        ("pump_name", "Pump"),
        ("litres", "Litres"),
        ("rate_per_litre", "Rate"),
        ("total_amount", "Amount"),
        ("odometer", "Odometer"),
    ]
    return _list_view(request, DieselEntry, "truckmaster/crud_list.html", "Diesel Management", columns, ["pump_name", "bill_number", "truck__registration_no"], "entry_date", reverse("tm-diesel-form"), entity="diesel")


@session_required
def diesel_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(DieselEntry.objects.for_company(company_id), pk=pk) if pk else DieselEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.entry_date = parse_date(request.POST.get("entry_date"), timezone.localdate())
        obj.truck_id = request.POST.get("truck")
        obj.driver_id = request.POST.get("driver") or None
        obj.trip_id = request.POST.get("trip") or None
        obj.pump_name = request.POST.get("pump_name")
        obj.location = request.POST.get("location")
        obj.fuel_type = request.POST.get("fuel_type") or "diesel"
        obj.litres = _dec(request.POST.get("litres"))
        obj.rate_per_litre = _dec(request.POST.get("rate_per_litre"))
        obj.odometer = _int(request.POST.get("odometer"))
        obj.payment_mode = request.POST.get("payment_mode") or "cash"
        obj.bill_number = request.POST.get("bill_number")
        if request.FILES.get("bill_attachment"):
            obj.bill_attachment = request.FILES["bill_attachment"]
        obj.duplicate_hash = money_hash(company_id, obj.truck_id, obj.entry_date, obj.bill_number or obj.litres, obj.pump_name, obj.odometer)
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            recompute_diesel(obj)
            messages.success(request, f"Diesel entry saved. Total {obj.total_amount}.")
            return redirect("tm-diesel-list")
        except IntegrityError:
            messages.error(request, "Duplicate diesel transaction detected.")
    return render(request, "truckmaster/diesel_form.html", _base_ctx(request, obj=obj, trips=Trip.objects.for_company(company_id)))


@session_required
def expense_list(request):
    ensure_expense_categories(_company(request))
    columns = [
        ("expense_date", "Date"),
        ("truck.registration_no", "Truck"),
        ("category.name", "Category"),
        ("amount", "Amount"),
        ("trip.trip_no", "Trip"),
        ("vendor_name", "Vendor"),
        ("bill_number", "Bill No"),
    ]
    return _list_view(request, ExpenseEntry, "truckmaster/crud_list.html", "Truck Expenses", columns, ["description", "vendor_name", "bill_number"], "expense_date", reverse("tm-expense-form"), entity="expense")


@session_required
def expense_form(request, pk=None):
    company_id = _company(request)
    ensure_expense_categories(company_id)
    obj = get_object_or_404(ExpenseEntry.objects.for_company(company_id), pk=pk) if pk else ExpenseEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.expense_date = parse_date(request.POST.get("expense_date"), timezone.localdate())
        obj.truck_id = request.POST.get("truck") or None
        obj.driver_id = request.POST.get("driver") or None
        obj.trip_id = request.POST.get("trip") or None
        obj.category_id = request.POST.get("category")
        obj.description = request.POST.get("description")
        obj.amount = _dec(request.POST.get("amount"))
        obj.payment_mode = request.POST.get("payment_mode") or "cash"
        obj.vendor_name = request.POST.get("vendor_name")
        obj.bill_number = request.POST.get("bill_number")
        obj.remarks = request.POST.get("remarks")
        if request.FILES.get("attachment"):
            obj.attachment = request.FILES["attachment"]
        obj.duplicate_hash = money_hash(company_id, obj.truck_id, obj.expense_date, obj.category_id, obj.amount, obj.bill_number)
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, "Expense saved.")
            return redirect("tm-expense-list")
        except IntegrityError:
            messages.error(request, "Duplicate expense entry detected.")
    return render(
        request,
        "truckmaster/expense_form.html",
        _base_ctx(
            request,
            obj=obj,
            categories=ExpenseCategory.objects.filter(company_id_id=company_id, is_active=True),
            trips=Trip.objects.for_company(company_id),
        ),
    )


@session_required
def loading_list(request):
    company_id = _company(request)
    loadings = LoadingEntry.objects.for_company(company_id)
    unloadings = UnloadingEntry.objects.for_company(company_id)
    loadings, start, end = _filters(request, loadings, ["location", "material"], "entry_date")
    return render(
        request,
        "truckmaster/loading_list.html",
        _base_ctx(request, loadings=_paginate(request, loadings), unloadings=unloadings[:100], trips=Trip.objects.for_company(company_id)),
    )


@session_required
def loading_form(request):
    company_id = _company(request)
    kind = request.GET.get("kind") or request.POST.get("kind") or "loading"
    if request.method == "POST":
        trip = get_object_or_404(Trip.objects.for_company(company_id), pk=request.POST.get("trip"))
        common = dict(
            company_id_id=company_id,
            trip=trip,
            truck=trip.truck,
            entry_date=parse_date(request.POST.get("entry_date"), timezone.localdate()),
            location=request.POST.get("location"),
            material=request.POST.get("material"),
            party_id=request.POST.get("party") or None,
            remarks=request.POST.get("remarks"),
            created_by=actor(request),
        )
        if kind == "unloading":
            UnloadingEntry.objects.create(
                **common,
                unloaded_weight=_dec(request.POST.get("weight")),
                labour_charges=_dec(request.POST.get("labour_charges")),
                unloading_charges=_dec(request.POST.get("charges")),
            )
            trip.unloaded_weight = _dec(request.POST.get("weight"))
            trip.save(update_fields=["unloaded_weight"])
        else:
            LoadingEntry.objects.create(
                **common,
                loaded_weight=_dec(request.POST.get("weight")),
                labour_charges=_dec(request.POST.get("labour_charges")),
                loading_charges=_dec(request.POST.get("charges")),
            )
            trip.loaded_weight = _dec(request.POST.get("weight"))
            trip.save(update_fields=["loaded_weight"])
        messages.success(request, f"{kind.title()} entry saved.")
        return redirect("tm-loading-list")
    return render(request, "truckmaster/loading_form.html", _base_ctx(request, kind=kind, trips=Trip.objects.for_company(company_id)))


@session_required
def toll_list(request):
    if request.method == "POST" and request.FILES.get("statement"):
        created, skipped, errors = import_fastag_csv(
            _company(request), actor(request), request.FILES["statement"], request.POST.get("truck") or None
        )
        messages.success(request, f"Imported {created} FASTag rows. Skipped duplicates: {skipped}.")
        for err in errors[:5]:
            messages.error(request, err)
        return redirect("tm-toll-list")
    columns = [
        ("entry_datetime", "Date / Time"),
        ("truck.registration_no", "Truck"),
        ("plaza_name", "Plaza"),
        ("amount", "Amount"),
        ("fastag_txn_id", "Txn ID"),
        ("trip.trip_no", "Trip"),
    ]
    return _list_view(request, TollEntry, "truckmaster/toll_list.html", "Toll & FASTag", columns, ["plaza_name", "fastag_txn_id"], None, reverse("tm-toll-form"), entity="toll")


@session_required
def toll_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(TollEntry.objects.for_company(company_id), pk=pk) if pk else TollEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.truck_id = request.POST.get("truck")
        obj.trip_id = request.POST.get("trip") or None
        obj.plaza_name = request.POST.get("plaza_name")
        dt = request.POST.get("entry_datetime")
        obj.entry_datetime = timezone.make_aware(datetime.fromisoformat(dt)) if dt else timezone.now()
        obj.location = request.POST.get("location")
        obj.amount = _dec(request.POST.get("amount"))
        obj.fastag_txn_id = request.POST.get("fastag_txn_id") or money_hash(company_id, obj.truck_id, obj.plaza_name, obj.amount, obj.entry_datetime)
        obj.payment_reference = request.POST.get("payment_reference")
        obj.is_fastag = request.POST.get("is_fastag") == "on"
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            messages.success(request, "Toll entry saved.")
            return redirect("tm-toll-list")
        except IntegrityError:
            messages.error(request, "Duplicate FASTag transaction ID.")
    return render(request, "truckmaster/toll_form.html", _base_ctx(request, obj=obj, trips=Trip.objects.for_company(company_id)))


# ---------------------------------------------------------------------------
# Maintenance / salary / documents / loan
# ---------------------------------------------------------------------------

@session_required
def maintenance_list(request):
    columns = [
        ("maintenance_no", "ID"),
        ("entry_date", "Date"),
        ("truck.registration_no", "Truck"),
        ("maintenance_type", "Type"),
        ("garage", "Garage"),
        ("total_amount", "Total"),
        ("next_service_date", "Next Service"),
    ]
    return _list_view(request, MaintenanceEntry, "truckmaster/crud_list.html", "Maintenance & Repairing", columns, ["maintenance_no", "garage", "description"], "entry_date", reverse("tm-maintenance-form"), entity="maintenance")


@session_required
def maintenance_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(MaintenanceEntry.objects.for_company(company_id), pk=pk) if pk else MaintenanceEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.truck_id = request.POST.get("truck")
        obj.entry_date = parse_date(request.POST.get("entry_date"), timezone.localdate())
        obj.odometer = _int(request.POST.get("odometer"))
        obj.maintenance_type = request.POST.get("maintenance_type") or "general"
        obj.description = request.POST.get("description")
        obj.garage = request.POST.get("garage")
        obj.labour_charges = _dec(request.POST.get("labour_charges"))
        obj.spare_parts_cost = _dec(request.POST.get("spare_parts_cost"))
        obj.other_charges = _dec(request.POST.get("other_charges"))
        obj.payment_mode = request.POST.get("payment_mode") or "cash"
        obj.next_service_date = parse_date(request.POST.get("next_service_date"))
        obj.next_service_km = _int(request.POST.get("next_service_km"))
        obj.remarks = request.POST.get("remarks")
        if request.FILES.get("bill_attachment"):
            obj.bill_attachment = request.FILES["bill_attachment"]
        if not obj.maintenance_no:
            obj.maintenance_no = next_number(MaintenanceEntry, company_id, "maintenance_no", "MN")
        _assign_common(obj, request, company_id)
        obj.save()
        recompute_maintenance(obj)
        messages.success(request, f"Maintenance saved. Total {obj.total_amount}.")
        return redirect("tm-maintenance-list")
    return render(request, "truckmaster/maintenance_form.html", _base_ctx(request, obj=obj))


@session_required
def salary_list(request):
    columns = [
        ("salary_month", "Month"),
        ("driver.name", "Driver"),
        ("basic_salary", "Basic"),
        ("net_salary", "Net"),
        ("paid_amount", "Paid"),
        ("pending_salary", "Pending"),
    ]
    return _list_view(request, DriverSalary, "truckmaster/salary_list.html", "Driver Salary & Advances", columns, ["driver__name"], "salary_month", reverse("tm-salary-form"), entity="salary")


@session_required
def salary_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(DriverSalary.objects.for_company(company_id), pk=pk) if pk else DriverSalary(company_id_id=company_id)
    if request.method == "POST":
        obj.driver_id = request.POST.get("driver")
        month = request.POST.get("salary_month")
        obj.salary_month = parse_date(f"{month}-01") if month and len(month) == 7 else parse_date(month, month_start(timezone.localdate()))
        obj.basic_salary = _dec(request.POST.get("basic_salary"))
        obj.trip_incentive = _dec(request.POST.get("trip_incentive"))
        obj.km_incentive = _dec(request.POST.get("km_incentive"))
        obj.allowances = _dec(request.POST.get("allowances"))
        obj.advance_paid = _dec(request.POST.get("advance_paid"))
        obj.deductions = _dec(request.POST.get("deductions"))
        obj.other_adjustments = _dec(request.POST.get("other_adjustments"))
        obj.paid_amount = _dec(request.POST.get("paid_amount"))
        obj.payment_date = parse_date(request.POST.get("payment_date"))
        obj.payment_mode = request.POST.get("payment_mode") or "bank"
        obj.remarks = request.POST.get("remarks")
        _assign_common(obj, request, company_id)
        try:
            obj.save()
            recompute_salary(obj)
            messages.success(request, f"Salary saved. Net {obj.net_salary}.")
            return redirect("tm-salary-list")
        except IntegrityError:
            messages.error(request, "Salary already generated for this driver and month.")
    return render(request, "truckmaster/salary_form.html", _base_ctx(request, obj=obj))


@session_required
def advance_form(request):
    company_id = _company(request)
    if request.method == "POST":
        DriverAdvance.objects.create(
            company_id_id=company_id,
            driver_id=request.POST.get("driver"),
            entry_date=parse_date(request.POST.get("entry_date"), timezone.localdate()),
            amount=_dec(request.POST.get("amount")),
            payment_mode=request.POST.get("payment_mode") or "cash",
            remarks=request.POST.get("remarks"),
            created_by=actor(request),
        )
        messages.success(request, "Advance recorded.")
        return redirect("tm-salary-list")
    return render(request, "truckmaster/advance_form.html", _base_ctx(request))


@session_required
def document_list(request):
    columns = [
        ("truck.registration_no", "Truck"),
        ("doc_type", "Document"),
        ("policy_no", "Policy / No"),
        ("premium_amount", "Premium"),
        ("start_date", "Start"),
        ("expiry_date", "Expiry"),
    ]
    return _list_view(request, TruckDocument, "truckmaster/crud_list.html", "Insurance & Documents", columns, ["policy_no", "provider"], None, reverse("tm-document-form"), entity="document")


@session_required
def document_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(TruckDocument.objects.for_company(company_id), pk=pk) if pk else TruckDocument(company_id_id=company_id)
    if request.method == "POST":
        obj.truck_id = request.POST.get("truck")
        obj.doc_type = request.POST.get("doc_type") or "insurance"
        obj.policy_no = request.POST.get("policy_no")
        obj.provider = request.POST.get("provider")
        obj.premium_amount = _dec(request.POST.get("premium_amount"))
        obj.start_date = parse_date(request.POST.get("start_date"))
        obj.expiry_date = parse_date(request.POST.get("expiry_date"))
        obj.remarks = request.POST.get("remarks")
        if request.FILES.get("attachment"):
            obj.attachment = request.FILES["attachment"]
        _assign_common(obj, request, company_id)
        obj.save()
        messages.success(request, "Document saved.")
        return redirect("tm-document-list")
    return render(request, "truckmaster/document_form.html", _base_ctx(request, obj=obj))


@session_required
def loan_list(request):
    columns = [
        ("truck.registration_no", "Truck"),
        ("finance_company", "Finance Company"),
        ("loan_amount", "Loan Amount"),
        ("emi_amount", "EMI"),
        ("paid_emi_count", "Paid EMI"),
        ("pending_emi_count", "Pending EMI"),
        ("outstanding", "Outstanding"),
    ]
    return _list_view(request, TruckLoan, "truckmaster/loan_list.html", "Loan & EMI", columns, ["finance_company", "truck__registration_no"], None, reverse("tm-loan-form"), entity="loan")


@session_required
def loan_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(TruckLoan.objects.for_company(company_id), pk=pk) if pk else TruckLoan(company_id_id=company_id)
    if request.method == "POST":
        obj.truck_id = request.POST.get("truck")
        obj.finance_company = request.POST.get("finance_company")
        obj.loan_amount = _dec(request.POST.get("loan_amount"))
        obj.start_date = parse_date(request.POST.get("start_date"), timezone.localdate())
        obj.emi_amount = _dec(request.POST.get("emi_amount"))
        obj.emi_due_day = _int(request.POST.get("emi_due_day"), 5)
        obj.tenure_months = _int(request.POST.get("tenure_months"))
        obj.paid_emi_count = _int(request.POST.get("paid_emi_count"))
        obj.pending_emi_count = max(obj.tenure_months - obj.paid_emi_count, 0)
        obj.outstanding = _dec(request.POST.get("outstanding"), str(d2(obj.emi_amount * obj.pending_emi_count)))
        obj.notes = request.POST.get("notes")
        _assign_common(obj, request, company_id)
        obj.save()
        messages.success(request, "Loan saved.")
        return redirect("tm-loan-list")
    return render(request, "truckmaster/loan_form.html", _base_ctx(request, obj=obj))


@session_required
def emi_form(request):
    company_id = _company(request)
    if request.method == "POST":
        loan = get_object_or_404(TruckLoan.objects.for_company(company_id), pk=request.POST.get("loan"))
        try:
            LoanEmiPayment.objects.create(
                company_id_id=company_id,
                loan=loan,
                truck=loan.truck,
                due_date=parse_date(request.POST.get("due_date"), timezone.localdate()),
                payment_date=parse_date(request.POST.get("payment_date"), timezone.localdate()),
                amount=_dec(request.POST.get("amount"), str(loan.emi_amount)),
                payment_mode=request.POST.get("payment_mode") or "bank",
                remarks=request.POST.get("remarks"),
                created_by=actor(request),
            )
            loan.paid_emi_count += 1
            loan.pending_emi_count = max(loan.tenure_months - loan.paid_emi_count, 0)
            loan.outstanding = max(d2(loan.outstanding) - d2(request.POST.get("amount") or loan.emi_amount), ZERO)
            loan.save()
            messages.success(request, "EMI payment recorded.")
            return redirect("tm-loan-list")
        except IntegrityError:
            messages.error(request, "EMI for this due date already exists.")
    return render(request, "truckmaster/emi_form.html", _base_ctx(request, loans=TruckLoan.objects.for_company(company_id)))


# ---------------------------------------------------------------------------
# Invoices / payments / vouchers
# ---------------------------------------------------------------------------

@session_required
def invoice_list(request):
    columns = [
        ("invoice_no", "Invoice No"),
        ("invoice_date", "Date"),
        ("party.name", "Customer"),
        ("truck.registration_no", "Vehicle"),
        ("total_amount", "Total"),
        ("advance", "Advance"),
        ("balance", "Balance"),
        ("status", "Status"),
    ]
    return _list_view(request, TransportInvoice, "truckmaster/crud_list.html", "Transport Invoices", columns, ["invoice_no", "party__name"], "invoice_date", reverse("tm-invoice-form"), entity="invoice")


@session_required
def invoice_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(TransportInvoice.objects.for_company(company_id), pk=pk) if pk else TransportInvoice(company_id_id=company_id)
    if request.method == "POST":
        obj.invoice_date = parse_date(request.POST.get("invoice_date"), timezone.localdate())
        obj.party_id = request.POST.get("party")
        obj.customer_address = request.POST.get("customer_address")
        obj.gstin = request.POST.get("gstin")
        obj.truck_id = request.POST.get("truck") or None
        obj.from_location = request.POST.get("from_location")
        obj.destination = request.POST.get("destination")
        obj.taluka = request.POST.get("taluka")
        obj.district = request.POST.get("district")
        obj.material = request.POST.get("material")
        obj.weight = _dec(request.POST.get("weight"))
        obj.rate = _dec(request.POST.get("rate"))
        obj.freight = _dec(request.POST.get("freight"))
        obj.labour = _dec(request.POST.get("labour"))
        obj.other_charges = _dec(request.POST.get("other_charges"))
        obj.advance = _dec(request.POST.get("advance"))
        obj.remarks = request.POST.get("remarks")
        if not obj.invoice_no:
            obj.invoice_no = next_number(TransportInvoice, company_id, "invoice_no", "TI")
        _assign_common(obj, request, company_id)
        obj.save()
        recompute_invoice_totals(obj)
        trip_ids = request.POST.getlist("trips")
        InvoiceTrip.objects.filter(invoice=obj).delete()
        for tid in trip_ids:
            InvoiceTrip.objects.get_or_create(invoice=obj, trip_id=tid)
            trip = Trip.objects.for_company(company_id).filter(id=tid).first()
            if trip:
                upsert_income_from_trip(trip, actor(request))
                income = IncomeEntry.objects.for_company(company_id).filter(source_key=f"trip:{trip.id}:freight").first()
                if income:
                    income.invoice_ref = obj.invoice_no
                    income.save(update_fields=["invoice_ref"])
        messages.success(request, f"Invoice {obj.invoice_no} saved. Total {obj.total_amount}.")
        return redirect("tm-invoice-detail", pk=obj.id)
    return render(
        request,
        "truckmaster/invoice_form.html",
        _base_ctx(request, obj=obj, trips=Trip.objects.for_company(company_id).filter(status__in=["delivered", "completed", "in_transit"])),
    )


@session_required
def invoice_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(TransportInvoice.objects.for_company(company_id), pk=pk)
    ctx = invoice_print_context(obj)
    shell = _base_ctx(request, **ctx, **_paper_urls(request, reverse("tm-invoice-list")))
    if request.GET.get("pdf") or request.GET.get("download"):
        return invoice_statement_pdf(shell, f"invoice_{obj.invoice_no}.pdf")
    return render(request, "truckmaster/paper_invoice.html", shell)


@session_required
def payment_list(request):
    columns = [
        ("payment_date", "Date"),
        ("party.name", "Party"),
        ("invoice.invoice_no", "Invoice"),
        ("amount", "Amount"),
        ("payment_mode", "Mode"),
        ("reference_no", "Reference"),
    ]
    return _list_view(request, PaymentEntry, "truckmaster/crud_list.html", "Payment & Outstanding", columns, ["reference_no", "party__name"], "payment_date", reverse("tm-payment-form"), entity="payment")


@session_required
def payment_form(request, pk=None):
    company_id = _company(request)
    obj = PaymentEntry(company_id_id=company_id)
    if request.method == "POST":
        obj.payment_date = parse_date(request.POST.get("payment_date"), timezone.localdate())
        obj.party_id = request.POST.get("party")
        obj.invoice_id = request.POST.get("invoice") or None
        obj.booking_id = request.POST.get("booking") or None
        obj.amount = _dec(request.POST.get("amount"))
        obj.payment_mode = request.POST.get("payment_mode") or "cash"
        obj.reference_no = request.POST.get("reference_no")
        obj.remarks = request.POST.get("remarks")
        _assign_common(obj, request, company_id)
        with transaction.atomic():
            obj.save()
            if obj.invoice_id:
                apply_payment_to_invoice(obj.invoice, obj.amount)
            if obj.booking_id and obj.booking:
                income = IncomeEntry.objects.for_company(company_id).filter(booking=obj.booking, is_deleted=False).first()
                apply_payment_to_income(income, obj.amount)
        messages.success(request, "Payment recorded.")
        return redirect("tm-payment-list")
    outstanding = TransportInvoice.objects.for_company(company_id).exclude(status="paid")
    return render(
        request,
        "truckmaster/payment_form.html",
        _base_ctx(request, obj=obj, invoices=outstanding, bookings=Booking.objects.for_company(company_id), outstanding=outstanding),
    )


@session_required
def voucher_list(request):
    columns = [
        ("voucher_no", "Voucher No"),
        ("voucher_date", "Date"),
        ("voucher_type", "Type"),
        ("truck.registration_no", "Truck"),
        ("trip.trip_no", "Trip"),
        ("total_amount", "Total"),
    ]
    return _list_view(request, Voucher, "truckmaster/crud_list.html", "Voucher Management", columns, ["voucher_no"], "voucher_date", reverse("tm-voucher-form"), entity="voucher")


@session_required
def voucher_form(request, pk=None):
    company_id = _company(request)
    obj = get_object_or_404(Voucher.objects.for_company(company_id), pk=pk) if pk else Voucher(company_id_id=company_id)
    if request.method == "POST":
        obj.voucher_date = parse_date(request.POST.get("voucher_date"), timezone.localdate())
        obj.voucher_type = request.POST.get("voucher_type") or "trip"
        obj.trip_id = request.POST.get("trip") or None
        obj.truck_id = request.POST.get("truck") or None
        obj.driver_id = request.POST.get("driver") or None
        obj.period_from = parse_date(request.POST.get("period_from"))
        obj.period_to = parse_date(request.POST.get("period_to"))
        obj.notes = request.POST.get("notes")
        if obj.trip_id:
            data = build_voucher_from_trip(company_id, obj.trip, obj.voucher_type)
            for k, v in data.items():
                if k in ("trip", "truck", "driver", "voucher_type"):
                    continue
                setattr(obj, k, v)
            obj.truck = obj.trip.truck
            obj.driver = obj.trip.driver
        obj.total_amount = finalize_voucher_totals(obj.__dict__)
        if not obj.voucher_no:
            obj.voucher_no = next_number(Voucher, company_id, "voucher_no", "VC")
        _assign_common(obj, request, company_id)
        obj.save()
        messages.success(request, f"Voucher {obj.voucher_no} generated. Total {obj.total_amount}.")
        return redirect("tm-voucher-detail", pk=obj.id)
    return render(request, "truckmaster/voucher_form.html", _base_ctx(request, obj=obj, trips=Trip.objects.for_company(company_id)))


@session_required
def voucher_detail(request, pk):
    company_id = _company(request)
    obj = get_object_or_404(Voucher.objects.for_company(company_id), pk=pk)
    if request.GET.get("pdf"):
        return voucher_pdf(obj, company_id)
    return render(request, "truckmaster/voucher_detail.html", _base_ctx(request, obj=obj))


# ---------------------------------------------------------------------------
# Reports / P&L
# ---------------------------------------------------------------------------

def _report_period(request):
    today = timezone.localdate()
    year = _int(request.GET.get("year"), today.year)
    month = _int(request.GET.get("month"), today.month)
    if month < 1 or month > 12:
        month = today.month
    start, end = month_bounds(year, month)
    return year, month, start, end


@session_required
def reports_home(request):
    today = timezone.localdate()
    year = _int(request.GET.get("year"), today.year)
    month = _int(request.GET.get("month"), today.month)
    month_names = [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (4, "April"),
        (5, "May"),
        (6, "June"),
        (7, "July"),
        (8, "August"),
        (9, "September"),
        (10, "October"),
        (11, "November"),
        (12, "December"),
    ]
    return render(
        request,
        "truckmaster/reports.html",
        _base_ctx(
            request,
            year=year,
            month=month,
            months=month_names,
            years=range(today.year, today.year - 6, -1),
        ),
    )


@session_required
def paper_pnl(request):
    company_id = _company(request)
    year, month, start, end = _report_period(request)
    ctx = pnl_paper_context(company_id, year, month)
    back = f"{reverse('tm-reports')}?year={year}&month={month}"
    shell = _base_ctx(request, **ctx, year=year, month=month, **_paper_urls(request, back))
    if request.GET.get("download"):
        return pnl_pdf(shell, f"pnl_{ctx['month_label']}.pdf")
    return render(request, "truckmaster/paper_pnl.html", shell)


@session_required
def paper_vakara(request):
    company_id = _company(request)
    year, month, start, end = _report_period(request)
    truck_id = request.GET.get("truck")
    if not truck_id:
        messages.error(request, "Vakara report mate truck select karo.")
        return redirect(f"{reverse('tm-reports')}?year={year}&month={month}")
    truck = get_object_or_404(Truck.objects.for_company(company_id), pk=truck_id)
    ctx = vakara_context(company_id, truck, start, end)
    back = f"{reverse('tm-reports')}?year={year}&month={month}&truck={truck.id}"
    shell = _base_ctx(request, **ctx, year=year, month=month, **_paper_urls(request, back))
    if request.GET.get("download"):
        return vakara_pdf(shell, f"vakara_{truck.registration_no}_{start}.pdf")
    return render(request, "truckmaster/paper_vakara.html", shell)


@session_required
def paper_voucher(request):
    company_id = _company(request)
    year, month, start, end = _report_period(request)
    truck_id = request.GET.get("truck")
    if not truck_id:
        messages.error(request, "Voucher report mate truck select karo.")
        return redirect(f"{reverse('tm-reports')}?year={year}&month={month}")
    truck = get_object_or_404(Truck.objects.for_company(company_id), pk=truck_id)
    ctx = voucher_month_context(company_id, truck, start, end)
    back = f"{reverse('tm-reports')}?year={year}&month={month}&truck={truck.id}"
    shell = _base_ctx(request, **ctx, year=year, month=month, **_paper_urls(request, back))
    if request.GET.get("download"):
        return voucher_month_pdf(shell, f"voucher_{truck.registration_no}_{start}.pdf")
    return render(request, "truckmaster/paper_voucher.html", shell)


@session_required
def paper_invoice(request):
    company_id = _company(request)
    year, month, start, end = _report_period(request)
    party = None
    party_id = request.GET.get("party")
    if party_id:
        party = get_object_or_404(Party.objects.for_company(company_id), pk=party_id)
    ctx = invoice_statement_context(company_id, start, end, party)
    back = f"{reverse('tm-reports')}?year={year}&month={month}"
    if party_id:
        back += f"&party={party_id}"
    shell = _base_ctx(request, **ctx, year=year, month=month, **_paper_urls(request, back))
    if request.GET.get("download"):
        label = party.name.replace(" ", "_") if party else "all"
        return invoice_statement_pdf(shell, f"invoice_{label}_{start}.pdf")
    return render(request, "truckmaster/paper_invoice.html", shell)


@session_required
def report_run(request, report_key):
    company_id = _company(request)
    start = parse_date(request.GET.get("start_date"), date(timezone.localdate().year, timezone.localdate().month, 1))
    end = parse_date(request.GET.get("end_date"), timezone.localdate())
    truck_id = request.GET.get("truck")
    driver_id = request.GET.get("driver")
    party_id = request.GET.get("party")

    def qs_filter(qs, date_field):
        qs = date_range_filter(qs, date_field, start, end)
        if truck_id and any(f.name == "truck" for f in qs.model._meta.fields):
            qs = qs.filter(truck_id=truck_id)
        if driver_id and any(f.name == "driver" for f in qs.model._meta.fields):
            qs = qs.filter(driver_id=driver_id)
        if party_id and any(f.name == "party" for f in qs.model._meta.fields):
            qs = qs.filter(party_id=party_id)
        return qs

    catalog = {
        "daily_trip": (Trip, "trip_date", [("trip_no", "Trip"), ("trip_date", "Date"), ("truck.registration_no", "Truck"), ("start_location", "From"), ("destination", "To"), ("freight_amount", "Freight"), ("status", "Status")]),
        "monthly_trip": (Trip, "trip_date", [("trip_no", "Trip"), ("trip_date", "Date"), ("truck.registration_no", "Truck"), ("freight_amount", "Freight"), ("status", "Status")]),
        "truck_income": (IncomeEntry, "entry_date", [("entry_date", "Date"), ("truck.registration_no", "Truck"), ("category", "Category"), ("amount", "Amount")]),
        "truck_expense": (ExpenseEntry, "expense_date", [("expense_date", "Date"), ("truck.registration_no", "Truck"), ("category.name", "Category"), ("amount", "Amount")]),
        "driver": (Trip, "trip_date", [("trip_date", "Date"), ("driver.name", "Driver"), ("trip_no", "Trip"), ("total_km", "KM"), ("freight_amount", "Freight")]),
        "diesel": (DieselEntry, "entry_date", [("entry_date", "Date"), ("truck.registration_no", "Truck"), ("litres", "Litres"), ("total_amount", "Amount"), ("odometer", "Odo")]),
        "maintenance": (MaintenanceEntry, "entry_date", [("entry_date", "Date"), ("truck.registration_no", "Truck"), ("maintenance_type", "Type"), ("total_amount", "Amount")]),
        "salary": (DriverSalary, "salary_month", [("salary_month", "Month"), ("driver.name", "Driver"), ("net_salary", "Net"), ("pending_salary", "Pending")]),
        "loading": (LoadingEntry, "entry_date", [("entry_date", "Date"), ("trip.trip_no", "Trip"), ("location", "Location"), ("loaded_weight", "Weight"), ("loading_charges", "Charges")]),
        "fastag": (TollEntry, None, [("plaza_name", "Plaza"), ("amount", "Amount"), ("fastag_txn_id", "Txn"), ("truck.registration_no", "Truck")]),
        "toll": (TollEntry, None, [("plaza_name", "Plaza"), ("amount", "Amount"), ("truck.registration_no", "Truck")]),
        "booking": (Booking, "booking_date", [("booking_no", "Booking"), ("booking_date", "Date"), ("party.name", "Party"), ("total_freight", "Freight"), ("status", "Status")]),
        "freight": (IncomeEntry, "entry_date", [("entry_date", "Date"), ("category", "Category"), ("amount", "Amount"), ("pending_amount", "Pending")]),
        "collection": (PaymentEntry, "payment_date", [("payment_date", "Date"), ("party.name", "Party"), ("amount", "Amount"), ("payment_mode", "Mode")]),
        "outstanding": (TransportInvoice, "invoice_date", [("invoice_no", "Invoice"), ("party.name", "Party"), ("total_amount", "Total"), ("balance", "Balance")]),
        "round_trip": (RoundTrip, "start_date", [("round_trip_no", "ID"), ("truck.registration_no", "Truck"), ("total_income", "Income"), ("total_expenses", "Expense"), ("net_profit", "Net")]),
    }
    if report_key not in catalog:
        messages.error(request, "Unknown report.")
        return redirect("tm-reports")
    model, date_field, columns = catalog[report_key]
    qs = model.objects.for_company(company_id)
    if date_field:
        qs = qs_filter(qs, date_field)
    elif report_key in ("fastag", "toll"):
        qs = qs.filter(entry_datetime__date__gte=start, entry_datetime__date__lte=end)
        if truck_id:
            qs = qs.filter(truck_id=truck_id)
    if report_key == "outstanding":
        qs = qs.exclude(status="paid")
    exported = _export_if_requested(request, qs, report_key, columns)
    if exported:
        return exported
    return render(
        request,
        "truckmaster/report_result.html",
        _base_ctx(request, title=report_key.replace("_", " ").title(), page_obj=_paginate(request, qs), columns=columns, report_key=report_key, start_date=start, end_date=end),
    )


@session_required
def pnl_report(request):
    company_id = _company(request)
    today = timezone.localdate()
    year = _int(request.GET.get("year"), today.year)
    month = _int(request.GET.get("month"), today.month)
    yearly = request.GET.get("yearly") == "1"
    if yearly:
        start = date(year, 4, 1)
        end = date(year + 1, 3, 31)
        title = f"Yearly Profit & Loss {year}-{year+1}"
    else:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        title = f"Monthly Profit & Loss {start.strftime('%B %Y')}"
    data = pnl_matrix(company_id, start, end)
    display_rows = []
    for key, label, _bucket in data["rows"]:
        display_rows.append({
            "label": label,
            "values": [data["matrix"][key][t.id] for t in data["trucks"]],
            "total": data["totals"][key],
        })
    display_rows.append({
        "label": "Net Total (+/-)",
        "values": [data["net"][t.id] for t in data["trucks"]],
        "total": data["net_total"],
    })
    if request.GET.get("export"):
        headers = ["Particular"] + [t.registration_no for t in data["trucks"]] + ["Profit & Loss A/C"]
        rows = []
        for key, label, _bucket in data["rows"]:
            row = [label] + [data["matrix"][key][t.id] for t in data["trucks"]] + [data["totals"][key]]
            rows.append(row)
        rows.append(["Net Total (+/-)"] + [data["net"][t.id] for t in data["trucks"]] + [data["net_total"]])
        return export_rows(request, "monthly_profit_loss", headers, rows)
    return render(
        request,
        "truckmaster/pnl.html",
        _base_ctx(request, title=title, data=data, display_rows=display_rows, year=year, month=month, yearly=yearly),
    )


# ---------------------------------------------------------------------------
# JSON APIs (session auth, same as existing erp.api)
# ---------------------------------------------------------------------------

@session_required
def api_lookups(request):
    company_id = _company(request)
    return JsonResponse(
        {
            "trucks": list(Truck.objects.for_company(company_id).values("id", "registration_no", "status")),
            "drivers": list(Driver.objects.for_company(company_id).values("id", "name", "status")),
            "parties": list(Party.objects.for_company(company_id).values("id", "name", "contact_number")),
        }
    )


@session_required
def api_overlap(request):
    conflicts = find_overlap(
        _company(request),
        request.GET.get("truck"),
        request.GET.get("driver"),
        parse_date(request.GET.get("start")),
        parse_date(request.GET.get("end")),
        exclude_trip_id=request.GET.get("exclude") or None,
    )
    return JsonResponse({"ok": not conflicts, "conflicts": conflicts})


@session_required
def api_dashboard(request):
    data = dashboard_data(
        _company(request),
        start=parse_date(request.GET.get("start_date")),
        end=parse_date(request.GET.get("end_date")),
        truck_id=request.GET.get("truck") or None,
        driver_id=request.GET.get("driver") or None,
        party_id=request.GET.get("party") or None,
    )
    data.pop("recent_bookings", None)
    data.pop("doc_alerts", None)
    data.pop("truck_alerts", None)
    data.pop("license_alerts", None)
    data.pop("utilization", None)
    for key, val in list(data.items()):
        if isinstance(val, Decimal):
            data[key] = str(val)
    return JsonResponse(data)


@session_required
def api_freight(request):
    amount = calculate_freight(
        request.GET.get("rate_type") or "fixed",
        request.GET.get("rate") or 0,
        request.GET.get("weight") or 0,
        request.GET.get("km") or 0,
    )
    return JsonResponse({"total_freight": str(amount)})
