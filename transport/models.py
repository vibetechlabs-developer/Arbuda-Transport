from django.db import models
from client.models import Client_profile , Company_user

## Contract Model  ##

class T_Contract(models.Model):
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)

    # Company Information
    company_name = models.CharField(max_length=255)
    gst_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=20, blank=True, null=True)
    tan_number = models.CharField(max_length=20, blank=True, null=True)
    cin_number = models.CharField(max_length=50, blank=True, null=True)
    from_center = models.CharField(max_length=100, blank=True, null=True)

    # Contract Information
    contract_no = models.CharField(max_length=50, unique=True)
    bill_series_from = models.CharField(max_length=20, blank=True, null=True)
    bill_series_to = models.CharField(max_length=20, blank=True, null=True)
    c_start_date = models.DateField(blank=True, null=True)
    c_end_date = models.DateField(blank=True, null=True)
    dc_field = models.CharField(max_length=100, blank=True, null=True)
    gc_note_required = models.BooleanField(default=False)
    gc_series_from = models.CharField(max_length=20, blank=True, null=True)

    # Contact Person
    cp_name = models.CharField(max_length=100, blank=True, null=True)
    c_email = models.EmailField(blank=True, null=True)
    c_designation = models.CharField(max_length=100, blank=True, null=True)
    c_number = models.CharField(max_length=15, blank=True, null=True)

    # Billing Address
    billing_address = models.TextField(blank=True, null=True)
    billing_state = models.CharField(max_length=50, blank=True, null=True) 
    billing_city = models.CharField(max_length=50, blank=True, null=True)
    billing_pin = models.CharField(max_length=10, blank=True, null=True)
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Kilometer-Wise", "Kilometer-Wise"),
            ("Taluka-Wise", "Taluka-Wise"),
            ("Slab-Wise", "Slab-Wise"),
            ("Distric-Wise", "Distric-Wise"),
        ),
        blank=True,
        null=True
    )
    # Rate Information

    unloading_charge_1 = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
    unloading_charge_2 = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
    loading_charge = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)

    # Fields to include in invoice
    invoice_fields = models.JSONField(default=list, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):   
        return f"{self.contract_no}" 
    

    

##  Dispctch model ##
class Dispatch(models.Model):
    contract_id = models.ForeignKey(T_Contract, on_delete=models.CASCADE ,default=None)
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    dep_date = models.DateField(default=None)
    challan_no = models.CharField(max_length=100)
    truck_no = models.CharField(max_length=50)
    product_name = models.CharField(max_length=150)

    party_name = models.CharField(max_length=150 , default=0)
    from_center = models.CharField(max_length=150 , default=0)
    destination = models.CharField(max_length=150 , default=0)
    taluka = models.CharField(max_length=150 , default=0)
    district = models.CharField(max_length=150 , default=0)
    km = models.BigIntegerField()

    weight = models.DecimalField(max_digits=10, decimal_places=3)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    totalfreight = models.DecimalField(max_digits=12, decimal_places=2)
    unloading_charge_1 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    unloading_charge_2 = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
    loading_charge = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2)

    truck_booking_rate = models.DecimalField(max_digits=12, decimal_places=3 , default=0)
    total_paid_truck_onwer = models.DecimalField(max_digits=12, decimal_places=3 , default=0)
    advance_paid = models.DecimalField(max_digits=12, decimal_places=3 , default=0)
    panding_amount = models.DecimalField(max_digits=12, decimal_places=3 ,default=0)
    net_profit = models.DecimalField(max_digits=12, decimal_places=3 , default=0)

    inv_status = models.BooleanField(
        max_length=50, 
        default=False
    )

    gc_note_no = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dispatch {self.id}"


##  Route model  ##
class Destination(models.Model):
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract_id = models.ForeignKey(T_Contract, on_delete=models.CASCADE ,default=None)
    from_center = models.CharField(max_length=150)
    destination = models.CharField(max_length=150)
    district = models.CharField(max_length=150)
    taluka = models.CharField(max_length=150 , null=True , blank=True , default=None)
    km = models.BigIntegerField()

    def __str__(self):
        return f"{self.from_center} → {self.destination} ({self.km} km)"
    


########################
##### Rate Modules #####
########################

##  Rate District Wise  ##
class Rate_District(models.Model): 
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract = models.ForeignKey(T_Contract, on_delete=models.CASCADE, related_name="District_rates")
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Distric-Wise", "Distric-Wise"),
        ),
        blank=True,
        null=True
    )
    distric_name = models.CharField(max_length=50)
    mt = models.DecimalField(max_digits=10, decimal_places=4)
    mt_per_km = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return f"{self.rate_type}: {self.distric_name} | {self.mt} MT"
    

##  Rate Per Kilometer Wise  ##

class Rate(models.Model): 
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract = models.ForeignKey(T_Contract, on_delete=models.CASCADE, related_name="rates")
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Kilometer-Wise", "Kilometer-Wise"),
        ),
        blank=True,
        null=True
    )
    from_km = models.BigIntegerField()
    to_km = models.BigIntegerField()
    mt = models.DecimalField(max_digits=10, decimal_places=4)
    mt_per_km = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return f"{self.rate_type}: {self.from_km} → {self.to_km} km | {self.mt} MT"
    

##  Rate Income Tax-Wise  ##

    
class Rate_IncomeTax(models.Model): 
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract = models.ForeignKey(T_Contract, on_delete=models.CASCADE, related_name="IncomeTax_rates")
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Kilometer-Wise", "Kilometer-Wise"),
        ),
        blank=True,
        null=True
    )
    from_km = models.BigIntegerField()
    to_km = models.BigIntegerField()
    mt = models.DecimalField(max_digits=10, decimal_places=4)
    mt_per_km = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return f"{self.rate_type}: {self.from_km} → {self.to_km} km | {self.mt} MT"

##  Rate Income Tax-Wise  ##
    
class Rate_Cumulative(models.Model): 
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract = models.ForeignKey(T_Contract, on_delete=models.CASCADE, related_name="cumulative_rates")
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Kilometer-Wise", "Kilometer-Wise"),
        ),
        blank=True,
        null=True
    )
    from_km = models.BigIntegerField()
    to_km = models.BigIntegerField()
    mt = models.DecimalField(max_digits=10, decimal_places=4)
    mt_per_km = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return f"{self.rate_type}: {self.from_km} → {self.to_km} km | {self.mt} MT"
    


##  Rate Per Taluka Wise  ##    

class Rate_taluka(models.Model):  #kilo-meter wise
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract = models.ForeignKey(T_Contract, on_delete=models.CASCADE, related_name="Taluka_rates")
    rate_type = models.CharField(
        max_length=50,
        choices=(
            ("Taluka-Wise", "Taluka-Wise"),
        ),
        blank=True,
        null=True
    )
    distric_name = models.CharField(max_length=50)
    taluka_name = models.CharField(max_length=50)
    mt = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return f"{self.rate_type}: {self.distric_name} → {self.taluka_name} km | {self.mt} MT"
    

class Invoice(models.Model):
    dispatch_list = models.ManyToManyField(Dispatch, related_name="invoices")
    Bill_no = models.CharField(max_length=50)
    Bill_date = models.DateField(null=True, blank=True)
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    contract_id = models.ForeignKey(T_Contract, on_delete=models.CASCADE ,default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice {self.Bill_no}"
    
class GC_Note(models.Model):
    gc_no = models.BigIntegerField()
    gc_date = models.DateField(null=True, blank=True)
    consignor = models.CharField(max_length=255)    
    consignee = models.CharField(max_length=255)
    dispatch_from = models.CharField(max_length=255)
    dc_field = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    product_name = models.CharField(max_length=255)
    weight = models.DecimalField(max_digits=10, decimal_places=4)
    truck_no = models.CharField(max_length=50)
    district = models.CharField(max_length=100)
    bill_no = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    bill_id = models.ForeignKey(Invoice, on_delete=models.CASCADE ,default=None)
    dispatch_id = models.ForeignKey(Dispatch, on_delete=models.CASCADE ,default=None)
    contract_id = models.ForeignKey(T_Contract, on_delete=models.CASCADE ,default=None)
    company_id = models.ForeignKey(Company_user , on_delete=models.CASCADE , default=None)
    def __str__(self):
        return f"GC Note {self.gc_no}"

