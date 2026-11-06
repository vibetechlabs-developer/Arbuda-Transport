from django.contrib import admin

from truckmaster import models as m

for model in [
    m.Truck,
    m.Driver,
    m.Party,
    m.Booking,
    m.Trip,
    m.RoundTrip,
    m.IncomeEntry,
    m.DieselEntry,
    m.ExpenseEntry,
    m.TransportInvoice,
    m.Voucher,
]:
    admin.site.register(model)
