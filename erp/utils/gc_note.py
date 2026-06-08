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
