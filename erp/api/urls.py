from django.urls import path
from . import views


urlpatterns = [

    # contract fecthing 
    path("get-contract-details", views.get_contract_details, name="get-contract-details"),

    # rate fecthing for dispatch
    path("get-rate-details", views.get_rate_details, name="get-rate-details"), # kilo-meter rate
    path("get-incometax-rate-details", views.get_incometax_rate_details, name="get-incometax-rate-details"),
    path("get-taluka-rate-details", views.get_taluka_rate_details, name="get-taluka-rate-details"),
    path('get-district-rate-details', views.get_district_rate_details , name='get-district-rate-details'),
    path('get-cumrate-details', views.get_cumrate_details , name='get-cumrate-details'),
    path("rates/<int:client_id>/", views.fetch_rates, name="fetch_rates"), # rate view

    # dispatch fecthing for invoice
    path("get-dispacth", views.get_dispacth, name="get-dispacth"), # from invoice
    path("get-ninv-dispacth", views.get_ninv_dispacth, name="get-dispacth"), # from invoice here ninv means not in invoice dispatch

    # invoice gc note fecthing
    path("get-gc", views.get_gc, name="get-gc"),
    path("get-invoice", views.get_invoice, name="get-invoice"), # from invoice


    path("get-dispacth-product", views.get_dispacth_product, name="get-dispacth-product"), # from invoice

     
    # others master
    path("get-destination-details", views.get_destination_details, name="get-destination-details"),

]