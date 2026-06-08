"""Company-wide GC note number allocation (dispatch-date order within each invoice)."""

from __future__ import annotations

from datetime import date


def sort_dispatches_for_gc_notes(dispatches):
    """Order dispatches by dispatch date, then challan, then id."""

    def sort_key(d):
        dep = d.dep_date if getattr(d, "dep_date", None) else date.min
        challan = str(getattr(d, "challan_no", "") or "")
        return (dep, challan, d.id)

    return sorted(dispatches, key=sort_key)


def next_gc_no_for_company(company_id, *, exclude_bill_id=None) -> int:
    """
    Next available GC number for **new** notes on this transport company.

    Existing GC notes are never changed. Uses the highest ``gc_no`` already
    stored for the company (one sequence across all contracts).
    """
    from transport.models import GC_Note

    qs = GC_Note.objects.filter(company_id_id=company_id)
    if exclude_bill_id is not None:
        qs = qs.exclude(bill_id_id=exclude_bill_id)

    last = qs.order_by("-gc_no").first()
    if last:
        return int(last.gc_no) + 1
    return 1


def create_gc_notes_for_dispatches(
    company_id,
    contract,
    invoice,
    dispatches,
    bill_no,
    bill_date,
    *,
    preserved_gc_by_dispatch=None,
):
    """
    Create GC notes for dispatches on an invoice.

    - One running sequence per transport company (all contracts share it).
    - Within this invoice, dispatches are numbered in dispatch-date order.
    - ``preserved_gc_by_dispatch`` keeps existing numbers when updating an
      invoice (grandfather rule — old GC notes are not renumbered).
    """
    from transport.models import GC_Note

    preserved = preserved_gc_by_dispatch or {}
    ordered = sort_dispatches_for_gc_notes(dispatches)
    next_new = next_gc_no_for_company(company_id)
    if preserved:
        next_new = max(next_new, max(preserved.values()) + 1)

    for d in ordered:
        if d.id in preserved:
            gc_no = preserved[d.id]
        else:
            gc_no = next_new
            next_new += 1

        gc_note = GC_Note.objects.create(
            gc_no=gc_no,
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
            bill_no=bill_no,
            bill_id=invoice,
            dispatch_id=d,
            contract_id=contract,
            company_id_id=company_id,
        )
        d.gc_note_no = gc_note.gc_no
        d.save(update_fields=["gc_note_no"])
