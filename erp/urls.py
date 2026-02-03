from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from erp.views import *

urlpatterns = [
    path('admin/', admin.site.urls),

    # API endpoints
    path('api/', include('erp.api.urls')),

    # dashboard (home)
    path('', dashboard_views.dashboard, name='dashboard'),
    
    # login, logout, registraion, profile
    path('company-registraion', company_views.Company_registraion , name='company-registraion'),
    path('company-login', auth_views.Company_login , name='company-login'),
    path('company-logout', auth_views.Company_logout , name='company-logout'),
    path('company-profile', company_views.Company_profile_view , name='company-profile'),

    # contract 
    path('new-contract-view' , transport_views.new_contract_view_2, name='new-contract-view'),
    path('new-contract-form' , transport_views.add_contract, name='new-contract-form'),
    path('update-contract-form' , transport_views.update_contract, name='update-contract-form'),

    # dispatch
    path("dispatch-view", transport_views.dispatch_view, name="dispatch-view"),
    path('dispatch-form', transport_views.dispatch_form , name='dispatch-form'),
    path('dispatch-update' , transport_views.dispatch_update, name='dispatch-update'), # not in use


    path("client-report-view", report_view.client_report_view, name="client-report-view"),
    path("internal-report", report_view.internal_report, name="internal-report"),
    path("download-our-report", report_view.download_our_report, name="download-our-report"),

    # dispatch invoice and gc note
    path("view-dispatch-invoice", transport_views.view_dispatch_Invoice, name="view-dispatch-invoice"), # created view
    path("create-dispatch-invoice", transport_views.create_dispatch_Invoice, name="create-dispatch-invoice"), # create view
    path("update-dispatch-invoice", transport_views.update_dispatch_Invoice, name="update-dispatch-invoice"), # update view
    path("generate-invoice-pdf", download_views.generate_invoice_pdf, name="generate-invoice-pdf"),
    path("download-generate-invoice-pdf", download_views.download_generate_invoice_pdf, name="download-generate-invoice-pdf"),
    path("view-gc-note", transport_views.view_gc_note, name="view-gc-note"),
    path("download-gc-pdf", download_views.download_gc_pdf, name="download-gc-pdf"),

    path("download-report", report_view.download_report, name="download-report"),
    path("download-distance-master-pdf", report_view.download_distance_master_pdf, name="download-distance-master-pdf"),

    # others master
    path('rate-master-view' , transport_views.Rate_master_view, name='rate-master-view'),
    path('rout-view', transport_views.rout_view , name='rout-view'), # destination view
    path('rout-update', transport_views.rout_update, name='rout-update'), # route update
    path('product-master-view', transport_views.product_master_view , name='product-master-view'), # product list

    # summary
    path('summary-view', transport_views.summary_view, name='summary-view'),
    path('generate-summary-pdf', download_views.generate_summary_pdf, name='generate-summary-pdf'),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
