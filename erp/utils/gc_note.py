"""Helpers for GC note number allocation."""

from __future__ import annotations


def parse_gc_series_start(contract) -> int:
    """Return the configured starting GC number for a contract (0 if unset/invalid)."""
    try:
        return int(str(getattr(contract, "gc_series_from", "") or "0").strip() or 0)
    except (TypeError, ValueError):
        return 0


def next_gc_no_for_contract(contract, *, exclude_bill_id=None) -> int:
    """
    Next GC number for a contract.

    Never returns below ``gc_series_from``. Uses the highest existing ``gc_no``
    (not latest insert id) so numbering stays sequential and respects the
    configured series start when it is raised (e.g. 4220 -> 4250).
    """
    from transport.models import GC_Note

    series_start = parse_gc_series_start(contract)
    qs = GC_Note.objects.filter(contract_id=contract.id)
    if exclude_bill_id is not None:
        qs = qs.exclude(bill_id_id=exclude_bill_id)

    last = qs.order_by("-gc_no").first()
    if last:
        return max(series_start, int(last.gc_no) + 1)
    return series_start if series_start > 0 else 1


def gc_numbers_below_series_start(contract, gc_numbers: dict) -> bool:
    """True when every stored GC number is below the contract series start."""
    if not gc_numbers:
        return False
    series_start = parse_gc_series_start(contract)
    if series_start <= 0:
        return False
    return all(int(v) < series_start for v in gc_numbers.values())


def renumber_invoice_gc_notes_below_series_start(contract, company_id) -> None:
    """
    For each invoice on this contract, if every GC note number is below
    ``gc_series_from``, renumber that bill's GC notes from the series start.
    Called after the contract GC start is saved (e.g. 4220 -> 4250).
    """
    from transport.models import Dispatch, GC_Note, Invoice

    if not getattr(contract, "gc_note_required", False):
        return
    if parse_gc_series_start(contract) <= 0:
        return

    invoices = Invoice.objects.filter(
        contract_id=contract,
        company_id=company_id,
    ).prefetch_related("dispatch_list")

    for invoice in invoices:
        dispatches = list(invoice.dispatch_list.all().order_by("dep_date", "id"))
        if not dispatches:
            continue

        existing_gc_by_dispatch = {
            gc.dispatch_id_id: int(gc.gc_no)
            for gc in GC_Note.objects.filter(bill_id=invoice)
            if gc.dispatch_id_id
        }
        if not gc_numbers_below_series_start(contract, existing_gc_by_dispatch):
            continue

        bill_date = invoice.Bill_date
        GC_Note.objects.filter(bill_id=invoice).delete()

        next_no = next_gc_no_for_contract(contract, exclude_bill_id=invoice.id)
        for d in dispatches:
            gc_note = GC_Note.objects.create(
                gc_no=next_no,
                gc_date=(d.dep_date or bill_date),
                consignor=contract.company_name,
                consignee=d.party_name,
                dispatch_from=contract.from_center,
                dc_field=d.challan_no,
                destination=d.destination,
                product_name=d.product_name,
                weight=d.weight,
                truck_no=d.truck_no,
                district=d.district,
                bill_no=invoice.Bill_no,
                bill_id=invoice,
                dispatch_id=d,
                contract_id=contract,
                company_id_id=company_id,
            )
            d.gc_note_no = gc_note.gc_no
            d.save(update_fields=["gc_note_no"])
            next_no += 1
