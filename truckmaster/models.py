from decimal import Decimal

from django.db import models
from django.utils import timezone

from company.models import Company_user
from transport.models import T_Contract


def money():
    return models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))


def qty():
    return models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))


class CompanyScopedQuerySet(models.QuerySet):
    def live(self):
        return self.filter(is_deleted=False)

    def for_company(self, company_id):
        return self.filter(company_id_id=company_id, is_deleted=False)


class SoftDeleteMixin(models.Model):
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])


class AuditMixin(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        abstract = True


class Truck(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("available", "Available"),
        ("on_trip", "On Trip"),
        ("maintenance", "Maintenance"),
        ("inactive", "Inactive"),
    )
    OWNERSHIP_CHOICES = (
        ("owned", "Owned"),
        ("hired", "Hired"),
        ("attached", "Attached"),
    )
    FUEL_CHOICES = (
        ("diesel", "Diesel"),
        ("petrol", "Petrol"),
        ("cng", "CNG"),
        ("electric", "Electric"),
        ("other", "Other"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    registration_no = models.CharField(max_length=30)
    name_model = models.CharField(max_length=150, blank=True, null=True)
    vehicle_type = models.CharField(max_length=80, blank=True, null=True)
    category = models.CharField(max_length=80, blank=True, null=True)
    capacity_ton = qty()
    axles = models.PositiveIntegerField(default=0)
    chassis_no = models.CharField(max_length=80, blank=True, null=True)
    engine_no = models.CharField(max_length=80, blank=True, null=True)
    fuel_type = models.CharField(max_length=20, choices=FUEL_CHOICES, default="diesel")
    purchase_date = models.DateField(blank=True, null=True)
    purchase_price = money()
    ownership_type = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, default="owned")
    insurance_provider = models.CharField(max_length=150, blank=True, null=True)
    insurance_policy_no = models.CharField(max_length=80, blank=True, null=True)
    insurance_expiry = models.DateField(blank=True, null=True)
    fitness_expiry = models.DateField(blank=True, null=True)
    puc_expiry = models.DateField(blank=True, null=True)
    permit_expiry = models.DateField(blank=True, null=True)
    rc_number = models.CharField(max_length=80, blank=True, null=True)
    odometer = models.PositiveIntegerField(default=0)
    assigned_driver = models.ForeignKey(
        "Driver", on_delete=models.SET_NULL, blank=True, null=True, related_name="assigned_trucks"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="available")
    notes = models.TextField(blank=True, null=True)
    rc_attachment = models.FileField(upload_to="truckmaster/trucks/", blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "registration_no"),)
        ordering = ["registration_no"]

    def __str__(self):
        return self.registration_no


class Driver(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("active", "Active"),
        ("on_trip", "On Trip"),
        ("leave", "On Leave"),
        ("inactive", "Inactive"),
    )
    SALARY_TYPE_CHOICES = (
        ("monthly", "Monthly"),
        ("per_trip", "Per Trip"),
        ("per_km", "Per KM"),
        ("daily", "Daily Wages"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=15)
    alternate_mobile = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    joining_date = models.DateField(blank=True, null=True)
    license_no = models.CharField(max_length=50)
    license_type = models.CharField(max_length=50, blank=True, null=True)
    license_expiry = models.DateField(blank=True, null=True)
    aadhaar_no = models.CharField(max_length=20, blank=True, null=True)
    pan_no = models.CharField(max_length=20, blank=True, null=True)
    salary_type = models.CharField(max_length=20, choices=SALARY_TYPE_CHOICES, default="monthly")
    basic_salary = money()
    allowances = money()
    assigned_truck = models.ForeignKey(
        Truck, on_delete=models.SET_NULL, blank=True, null=True, related_name="drivers"
    )
    emergency_contact = models.CharField(max_length=150, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    document = models.FileField(upload_to="truckmaster/drivers/", blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "license_no"),)
        ordering = ["name"]

    def __str__(self):
        return self.name


class Party(SoftDeleteMixin, AuditMixin):
    """Independent party master. Can optionally link to an existing contract."""

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    gstin = models.CharField(max_length=24, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    state = models.CharField(max_length=80, blank=True, null=True)
    contract = models.ForeignKey(T_Contract, on_delete=models.SET_NULL, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "name"),)
        ordering = ["name"]
        verbose_name_plural = "Parties"

    def __str__(self):
        return self.name


class Booking(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("truck_assigned", "Truck Assigned"),
        ("loading_pending", "Loading Pending"),
        ("in_transit", "In Transit"),
        ("delivered", "Delivered"),
        ("payment_pending", "Payment Pending"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )
    RATE_TYPE_CHOICES = (
        ("per_ton", "Per Ton"),
        ("fixed", "Fixed"),
        ("per_km", "Per KM"),
    )
    PAYMENT_MODES = (
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("upi", "UPI"),
        ("cheque", "Cheque"),
        ("credit", "Credit"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    booking_no = models.CharField(max_length=30)
    booking_date = models.DateField()
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="bookings")
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    source_location = models.CharField(max_length=150)
    destination = models.CharField(max_length=150)
    loading_point = models.CharField(max_length=150, blank=True, null=True)
    unloading_point = models.CharField(max_length=150, blank=True, null=True)
    material_description = models.CharField(max_length=200, blank=True, null=True)
    material_category = models.CharField(max_length=80, blank=True, null=True)
    total_weight = qty()
    weight_unit = models.CharField(max_length=10, default="MT")
    freight_rate = money()
    rate_type = models.CharField(max_length=20, choices=RATE_TYPE_CHOICES, default="fixed")
    total_freight = money()
    advance_amount = money()
    balance_amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    expected_loading_date = models.DateField(blank=True, null=True)
    expected_delivery_date = models.DateField(blank=True, null=True)
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    remarks = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to="truckmaster/bookings/", blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "booking_no"),)
        ordering = ["-booking_date", "-id"]

    def __str__(self):
        return self.booking_no


class RoundTrip(SoftDeleteMixin, AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    round_trip_no = models.CharField(max_length=30)
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    starting_km = models.PositiveIntegerField(default=0)
    ending_km = models.PositiveIntegerField(default=0)
    outbound_route = models.CharField(max_length=255, blank=True, null=True)
    return_route = models.CharField(max_length=255, blank=True, null=True)
    outbound_weight = qty()
    return_weight = qty()
    outbound_freight = money()
    return_freight = money()
    outbound_diesel = money()
    return_diesel = money()
    outbound_expenses = money()
    return_expenses = money()
    total_income = money()
    total_expenses = money()
    total_km = models.PositiveIntegerField(default=0)
    net_profit = money()
    notes = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "round_trip_no"),)
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.round_trip_no


class Trip(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("created", "Created"),
        ("loading", "Loading"),
        ("in_transit", "In Transit"),
        ("delivered", "Delivered"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )
    DIRECTION_CHOICES = (
        ("outbound", "Outbound"),
        ("return", "Return"),
        ("single", "Single"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    trip_no = models.CharField(max_length=30)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, blank=True, null=True, related_name="trips")
    round_trip = models.ForeignKey(
        RoundTrip, on_delete=models.SET_NULL, blank=True, null=True, related_name="trips"
    )
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default="single")
    sequence = models.PositiveIntegerField(default=1)
    trip_date = models.DateField()
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    start_location = models.CharField(max_length=150)
    destination = models.CharField(max_length=150)
    actual_start = models.DateTimeField(blank=True, null=True)
    actual_delivery = models.DateTimeField(blank=True, null=True)
    start_odometer = models.PositiveIntegerField(default=0)
    end_odometer = models.PositiveIntegerField(default=0)
    total_km = models.PositiveIntegerField(default=0)
    material_name = models.CharField(max_length=150, blank=True, null=True)
    loaded_weight = qty()
    unloaded_weight = qty()
    freight_amount = money()
    advance_received = money()
    payment_received = money()
    pending_amount = money()
    is_empty_return = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="created")
    notes = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "trip_no"),)
        ordering = ["-trip_date", "-id"]

    def __str__(self):
        return self.trip_no


class TripLeg(SoftDeleteMixin, AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="legs")
    sequence = models.PositiveIntegerField(default=1)
    from_location = models.CharField(max_length=150)
    to_location = models.CharField(max_length=150)
    loading_point = models.CharField(max_length=150, blank=True, null=True)
    unloading_point = models.CharField(max_length=150, blank=True, null=True)
    distance_km = models.PositiveIntegerField(default=0)
    weight = qty()
    freight = money()

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["sequence", "id"]


class IncomeEntry(SoftDeleteMixin, AuditMixin):
    """Single source of truth for transportation income (used in P&L)."""

    CATEGORY_CHOICES = (
        ("freight", "Freight Income"),
        ("return_freight", "Return Freight"),
        ("extra_freight", "Extra Freight"),
        ("loading_recovered", "Loading Charges Recovered"),
        ("unloading_recovered", "Unloading Charges Recovered"),
        ("other", "Other Transportation Income"),
    )
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    entry_date = models.DateField()
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="freight")
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, blank=True, null=True)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, blank=True, null=True)
    party = models.ForeignKey(Party, on_delete=models.SET_NULL, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    amount = money()
    received_amount = money()
    pending_amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="credit")
    invoice_ref = models.CharField(max_length=50, blank=True, null=True)
    source_key = models.CharField(max_length=80, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "source_key"),)
        ordering = ["-entry_date", "-id"]


class ExpenseCategory(models.Model):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=80)
    pnl_bucket = models.CharField(max_length=40, default="other")
    is_system = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = (("company_id", "code"),)
        ordering = ["name"]

    def __str__(self):
        return self.name


class ExpenseEntry(SoftDeleteMixin, AuditMixin):
    """General truck/trip expenses. Diesel/toll/maintenance/salary/EMI are stored in their own tables."""

    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    expense_date = models.DateField()
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, blank=True, null=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True, null=True)
    amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    vendor_name = models.CharField(max_length=150, blank=True, null=True)
    bill_number = models.CharField(max_length=80, blank=True, null=True)
    attachment = models.FileField(upload_to="truckmaster/expenses/", blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    duplicate_hash = models.CharField(max_length=64, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "duplicate_hash"),)
        ordering = ["-expense_date", "-id"]


class DieselEntry(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    entry_date = models.DateField()
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, blank=True, null=True)
    pump_name = models.CharField(max_length=150, blank=True, null=True)
    location = models.CharField(max_length=150, blank=True, null=True)
    fuel_type = models.CharField(max_length=20, default="diesel")
    litres = qty()
    rate_per_litre = money()
    total_amount = money()
    odometer = models.PositiveIntegerField(default=0)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    bill_number = models.CharField(max_length=80, blank=True, null=True)
    bill_attachment = models.FileField(upload_to="truckmaster/diesel/", blank=True, null=True)
    duplicate_hash = models.CharField(max_length=64, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "duplicate_hash"),)
        ordering = ["-entry_date", "-id"]


class LoadingEntry(SoftDeleteMixin, AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="loadings")
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    entry_date = models.DateField()
    location = models.CharField(max_length=150)
    material = models.CharField(max_length=150, blank=True, null=True)
    party = models.ForeignKey(Party, on_delete=models.SET_NULL, blank=True, null=True)
    loaded_weight = qty()
    labour_charges = money()
    loading_charges = money()
    remarks = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-entry_date", "-id"]


class UnloadingEntry(SoftDeleteMixin, AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="unloadings")
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    entry_date = models.DateField()
    location = models.CharField(max_length=150)
    material = models.CharField(max_length=150, blank=True, null=True)
    party = models.ForeignKey(Party, on_delete=models.SET_NULL, blank=True, null=True)
    unloaded_weight = qty()
    labour_charges = money()
    unloading_charges = money()
    remarks = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-entry_date", "-id"]


class TollEntry(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT)
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, blank=True, null=True)
    plaza_name = models.CharField(max_length=150)
    entry_datetime = models.DateTimeField()
    location = models.CharField(max_length=150, blank=True, null=True)
    amount = money()
    fastag_txn_id = models.CharField(max_length=80, blank=True, null=True)
    payment_reference = models.CharField(max_length=80, blank=True, null=True)
    is_fastag = models.BooleanField(default=True)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="bank")
    statement_ref = models.CharField(max_length=80, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "fastag_txn_id"),)
        ordering = ["-entry_datetime"]


class MaintenanceEntry(SoftDeleteMixin, AuditMixin):
    TYPE_CHOICES = (
        ("engine", "Engine Repair"),
        ("tyre", "Tyre Replacement"),
        ("puncture", "Puncture"),
        ("battery", "Battery"),
        ("oil", "Oil Change"),
        ("servicing", "Servicing"),
        ("brake", "Brake Repair"),
        ("clutch", "Clutch Repair"),
        ("electrical", "Electrical Repair"),
        ("spare", "Spare Parts"),
        ("welding", "Welding"),
        ("general", "General Maintenance"),
    )
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    maintenance_no = models.CharField(max_length=30)
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT)
    entry_date = models.DateField()
    odometer = models.PositiveIntegerField(default=0)
    maintenance_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default="general")
    description = models.CharField(max_length=255, blank=True, null=True)
    garage = models.CharField(max_length=150, blank=True, null=True)
    labour_charges = money()
    spare_parts_cost = money()
    other_charges = money()
    total_amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    next_service_date = models.DateField(blank=True, null=True)
    next_service_km = models.PositiveIntegerField(default=0)
    bill_attachment = models.FileField(upload_to="truckmaster/maintenance/", blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "maintenance_no"),)
        ordering = ["-entry_date", "-id"]


class DriverSalary(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    salary_month = models.DateField(help_text="First day of the salary month")
    basic_salary = money()
    trip_incentive = money()
    km_incentive = money()
    allowances = money()
    advance_paid = money()
    deductions = money()
    other_adjustments = money()
    net_salary = money()
    paid_amount = money()
    pending_salary = money()
    payment_date = models.DateField(blank=True, null=True)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="bank")
    remarks = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "driver", "salary_month"),)
        ordering = ["-salary_month", "-id"]


class DriverAdvance(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name="advances")
    entry_date = models.DateField()
    amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    remarks = models.CharField(max_length=255, blank=True, null=True)
    settled = models.BooleanField(default=False)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-entry_date", "-id"]


class DriverAttendance(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("present", "Present"),
        ("absent", "Absent"),
        ("leave", "Leave"),
        ("half", "Half Day"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="attendance")
    attendance_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="present")
    remarks = models.CharField(max_length=255, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "driver", "attendance_date"),)
        ordering = ["-attendance_date"]


class TruckDocument(SoftDeleteMixin, AuditMixin):
    DOC_TYPES = (
        ("insurance", "Insurance Policy"),
        ("fitness", "Fitness Certificate"),
        ("puc", "PUC"),
        ("permit", "Permit"),
        ("rc", "Registration Certificate"),
        ("other", "Other"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    truck = models.ForeignKey(Truck, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES)
    policy_no = models.CharField(max_length=80, blank=True, null=True)
    provider = models.CharField(max_length=150, blank=True, null=True)
    premium_amount = money()
    start_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    attachment = models.FileField(upload_to="truckmaster/documents/", blank=True, null=True)
    remarks = models.CharField(max_length=255, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["expiry_date"]


class TruckLoan(SoftDeleteMixin, AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="loans")
    finance_company = models.CharField(max_length=150)
    loan_amount = money()
    start_date = models.DateField()
    emi_amount = money()
    emi_due_day = models.PositiveIntegerField(default=5)
    tenure_months = models.PositiveIntegerField(default=0)
    paid_emi_count = models.PositiveIntegerField(default=0)
    pending_emi_count = models.PositiveIntegerField(default=0)
    outstanding = money()
    notes = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]


class LoanEmiPayment(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    loan = models.ForeignKey(TruckLoan, on_delete=models.CASCADE, related_name="payments")
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    due_date = models.DateField()
    payment_date = models.DateField(blank=True, null=True)
    amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="bank")
    remarks = models.CharField(max_length=255, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "loan", "due_date"),)
        ordering = ["-due_date"]


class TransportInvoice(SoftDeleteMixin, AuditMixin):
    STATUS_CHOICES = (
        ("unpaid", "Unpaid"),
        ("partial", "Partial"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    invoice_no = models.CharField(max_length=40)
    invoice_date = models.DateField()
    party = models.ForeignKey(Party, on_delete=models.PROTECT)
    customer_address = models.TextField(blank=True, null=True)
    gstin = models.CharField(max_length=24, blank=True, null=True)
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    from_location = models.CharField(max_length=150, blank=True, null=True)
    destination = models.CharField(max_length=150, blank=True, null=True)
    taluka = models.CharField(max_length=80, blank=True, null=True)
    district = models.CharField(max_length=80, blank=True, null=True)
    material = models.CharField(max_length=150, blank=True, null=True)
    weight = qty()
    rate = money()
    freight = money()
    labour = money()
    other_charges = money()
    total_amount = money()
    advance = money()
    balance = money()
    received_amount = money()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="unpaid")
    remarks = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "invoice_no"),)
        ordering = ["-invoice_date", "-id"]

    def __str__(self):
        return self.invoice_no


class InvoiceTrip(models.Model):
    invoice = models.ForeignKey(TransportInvoice, on_delete=models.CASCADE, related_name="invoice_trips")
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT)

    class Meta:
        unique_together = (("invoice", "trip"),)


class PaymentEntry(SoftDeleteMixin, AuditMixin):
    PAYMENT_MODES = Booking.PAYMENT_MODES

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    payment_date = models.DateField()
    party = models.ForeignKey(Party, on_delete=models.PROTECT)
    invoice = models.ForeignKey(TransportInvoice, on_delete=models.SET_NULL, blank=True, null=True)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, blank=True, null=True)
    income = models.ForeignKey(IncomeEntry, on_delete=models.SET_NULL, blank=True, null=True)
    amount = money()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="cash")
    reference_no = models.CharField(max_length=80, blank=True, null=True)
    remarks = models.CharField(max_length=255, blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-payment_date", "-id"]


class Voucher(SoftDeleteMixin, AuditMixin):
    VOUCHER_TYPES = (
        ("trip", "Trip Voucher"),
        ("truck", "Truck Voucher"),
        ("monthly", "Monthly Voucher"),
    )

    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    voucher_no = models.CharField(max_length=40)
    voucher_date = models.DateField()
    voucher_type = models.CharField(max_length=20, choices=VOUCHER_TYPES, default="trip")
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, blank=True, null=True)
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, blank=True, null=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    period_from = models.DateField(blank=True, null=True)
    period_to = models.DateField(blank=True, null=True)
    weight = qty()
    loading = money()
    unloading = money()
    labour = money()
    commission = money()
    toll_tax = money()
    other_expenses = money()
    day_expenses = money()
    night_expenses = money()
    diesel_bills = money()
    repair_labour = money()
    repair_parts = money()
    truck_expenses = money()
    fastag_amount = money()
    total_amount = money()
    notes = models.TextField(blank=True, null=True)

    objects = CompanyScopedQuerySet.as_manager()

    class Meta:
        unique_together = (("company_id", "voucher_no"),)
        ordering = ["-voucher_date", "-id"]


class Attachment(AuditMixin):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    module = models.CharField(max_length=40)
    record_id = models.PositiveIntegerField()
    file = models.FileField(upload_to="truckmaster/files/")
    original_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
