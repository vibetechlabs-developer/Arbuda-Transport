from django.db import models
from company.models import Company_user


class Client_profile(models.Model):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    client_name = models.CharField(max_length=100)
    c_bussniess_type = models.CharField(max_length=50)
    c_industry_type = models.CharField(max_length=50)
    c_gst_number = models.CharField(max_length=24 ,unique=True , default=None)
    c_pan_number = models.CharField(max_length=10, unique=True)
    c_tan_number = models.CharField(max_length=10, unique=True)
    c_cin_number = models.CharField(max_length=21, unique=True)
    c_contact_person = models.CharField(max_length=100, blank=True, null=True)
    c_contact_designation = models.CharField(max_length=100, blank=True, null=True)
    c_contact_email = models.EmailField(max_length=100, blank=True, null=True)  
    c_contact_mobile = models.CharField(max_length=12,blank=True, null=True)
    c_office_address = models.CharField(max_length=100 ,blank=True, null=True)
    c_office_state = models.CharField(max_length=20,blank=True, null=True)
    c_office_city = models.CharField(max_length=50,blank=True, null=True)
    c_office_pincode = models.CharField(max_length=6,blank=True, null=True)  
    c_billing_address = models.CharField(max_length=100 ,blank=True, null=True)
    c_billing_state = models.CharField(max_length=20,blank=True, null=True)
    c_billing_city = models.CharField(max_length=50,blank=True, null=True)
    c_billing_pincode = models.CharField(max_length=6,blank=True, null=True)  
    
    def __str__(self):
        return self.client_name
    
class Contract(models.Model):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
    client_id = models.ForeignKey(Client_profile, on_delete=models.CASCADE)
    tender_id = models.BigIntegerField(unique=True)
    tender_title = models.CharField(max_length=200)
    contarct_number = models.CharField(max_length=50 , unique=True)
    tender_value = models.BigIntegerField()
    payment_terms = models.CharField(max_length=2000, default=None)
    scope_of_work = models.CharField(max_length=2000)
    project_type = models.CharField(max_length=500)
    dilivery_location = models.CharField(max_length=700)
    contract_start_date = models.DateField(blank=False, null=False ,default=None)
    contract_end_date = models.DateField(blank=False, null=False , default=None)
    contract_status = models.CharField(max_length=100, blank=False, default='Pending')
    
    def __str__(self):
        return self.id

