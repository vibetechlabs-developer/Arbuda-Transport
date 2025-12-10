from django.db import models
from django.contrib.auth.hashers import   make_password, check_password


class Company_user(models.Model):
    company_name = models.CharField(max_length=20)
    gst_number = models.CharField(max_length=24 ,unique=True)
    email = models.CharField(max_length=50 , unique=True)
    mobile = models.BigIntegerField(unique=True)
    password = models.CharField(max_length=3128)
    company_profile_status = models.BooleanField(default=False)

    def set_password(self, raw_password):
        """Encrypt and set the password."""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """Check if the password matches the hash."""
        return check_password(raw_password, self.password)
    
    def save(self, *args, **kwargs):
        """Ensure the password is always hashed before saving."""
        if not self.password.startswith('pbkdf2_sha256$'):  # Avoid rehashing an already hashed password
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.company_name
    

class Company_profile(models.Model):
    company_id = models.ForeignKey(Company_user, on_delete=models.CASCADE)
   
    pan_number = models.CharField(max_length=10, unique=True)
    
    address = models.CharField(max_length=100 ,blank=True, null=True)
    state = models.CharField(max_length=20,blank=True, null=True)
    city = models.CharField(max_length=50,blank=True, null=True)
    pincode = models.CharField(max_length=6,blank=True, null=True)  
    logo = models.FileField(upload_to='company_logos/', blank=True, null=True)
    
    def __str__(self):
        return self.company_id