from django.contrib import admin
from company.models import Company_user, Company_profile

@admin.register(Company_user)
class CompanyUserAdmin(admin.ModelAdmin):
    list_display = ( 'company_name', 'email', 'mobile', 'gst_number', 'company_profile_status')
    search_fields = ('company_name', 'email', 'mobile', 'gst_number')
    list_filter = ('company_profile_status',)

# Register your models here.
