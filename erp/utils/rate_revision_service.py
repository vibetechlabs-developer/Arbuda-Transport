"""Resolve contract slab rates with optional diesel / rate revisions by date."""

from datetime import date
from decimal import Decimal, InvalidOperation

from transport.models import RateSlabRevision


def _to_decimal(value, default=Decimal("0")):
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def get_applicable_revision(company_id, contract_id, rate_category, as_of_date, **slab_keys):
    """Latest revision for slab where effective_from <= as_of_date."""
    if not as_of_date:
        return None
    qs = RateSlabRevision.objects.filter(
        company_id=company_id,
        contract_id=contract_id,
        rate_category=rate_category,
        effective_from__lte=as_of_date,
    )
    from_km = slab_keys.get("from_km")
    to_km = slab_keys.get("to_km")
    if from_km is not None and to_km is not None:
        qs = qs.filter(from_km=from_km, to_km=to_km)
    district_name = slab_keys.get("district_name")
    if district_name is not None:
        qs = qs.filter(district_name=district_name)
    taluka_name = slab_keys.get("taluka_name")
    if taluka_name is not None:
        qs = qs.filter(taluka_name=taluka_name)
    return qs.order_by("-effective_from", "-created_at").first()


def resolve_slab_value(base_value, company_id, contract_id, rate_category, as_of_date, **slab_keys):
    """Return rate value for dispatch date; uses revision if one applies."""
    base = _to_decimal(base_value)
    revision = get_applicable_revision(
        company_id, contract_id, rate_category, as_of_date, **slab_keys
    )
    if revision:
        return _to_decimal(revision.updated_value, base)
    return base


def compute_updated_value(base_value, adjustment_type, adjustment_amount):
    base = _to_decimal(base_value)
    amount = _to_decimal(adjustment_amount)
    if adjustment_type == "decrease":
        return max(Decimal("0"), base - amount)
    return base + amount


def resolve_value_before_adjustment(company_id, contract_id, rate_category, effective_from, base_value, **slab_keys):
    """
    Rate to apply the next adjustment on top of.
    Uses the latest revision already effective on that date (same-day chaining),
    otherwise the contract base value.
    """
    effective_from = _parse_date(effective_from)
    if not effective_from:
        return _to_decimal(base_value)

    prior = get_applicable_revision(
        company_id, contract_id, rate_category, effective_from, **slab_keys
    )
    if prior:
        return _to_decimal(prior.updated_value)
    return _to_decimal(base_value)


def _revision_queryset(company_id, contract_id, rate_category, **slab_keys):
    qs = RateSlabRevision.objects.filter(
        company_id=company_id,
        contract_id=contract_id,
        rate_category=rate_category,
    )
    from_km = slab_keys.get("from_km")
    to_km = slab_keys.get("to_km")
    if from_km is not None and to_km is not None:
        qs = qs.filter(from_km=from_km, to_km=to_km)
    district_name = slab_keys.get("district_name")
    if district_name is not None:
        qs = qs.filter(district_name=district_name)
    taluka_name = slab_keys.get("taluka_name")
    if taluka_name is not None:
        qs = qs.filter(taluka_name=taluka_name)
    return qs


def recalculate_revision_chain_for_slab(
    company_id, contract_id, rate_category, contract_base_value, **slab_keys
):
    """Rebuild base_value/updated_value for every revision on a slab in date order."""
    revisions = _revision_queryset(
        company_id, contract_id, rate_category, **slab_keys
    ).order_by("effective_from", "created_at")

    running = _to_decimal(contract_base_value)
    for rev in revisions:
        rev.base_value = running
        rev.updated_value = compute_updated_value(
            running, rev.adjustment_type, rev.adjustment_amount
        )
        running = _to_decimal(rev.updated_value)
        rev.save(update_fields=["base_value", "updated_value"])


def save_diesel_revision(
    company_id,
    contract,
    rate_category,
    effective_from,
    adjustment_type,
    adjustment_amount,
    choice,
    base_value,
    from_km=None,
    to_km=None,
    district_name=None,
    taluka_name=None,
):
    effective_from = _parse_date(effective_from)
    if not effective_from or not adjustment_type or not adjustment_amount:
        return None

    amount = _to_decimal(adjustment_amount)
    if amount <= 0:
        return None

    slab_keys = {}
    if from_km is not None and to_km is not None:
        slab_keys = {"from_km": int(from_km), "to_km": int(to_km)}
    elif district_name and taluka_name:
        slab_keys = {"district_name": district_name, "taluka_name": taluka_name}
    elif district_name:
        slab_keys = {"district_name": district_name}

    starting_value = resolve_value_before_adjustment(
        company_id,
        contract.id,
        rate_category,
        effective_from,
        base_value,
        **slab_keys,
    )
    updated = compute_updated_value(starting_value, adjustment_type, amount)

    revision = RateSlabRevision.objects.create(
        company_id_id=company_id,
        contract=contract,
        rate_category=rate_category,
        from_km=slab_keys.get("from_km"),
        to_km=slab_keys.get("to_km"),
        district_name=slab_keys.get("district_name"),
        taluka_name=slab_keys.get("taluka_name"),
        choice=choice or "mt",
        base_value=_to_decimal(starting_value),
        adjustment_type=adjustment_type,
        adjustment_amount=amount,
        updated_value=updated,
        effective_from=effective_from,
    )

    # Keep full history chain consistent (fixes same-day and out-of-order saves)
    recalculate_revision_chain_for_slab(
        company_id,
        contract.id,
        rate_category,
        base_value,
        **slab_keys,
    )
    revision.refresh_from_db()
    return revision


def process_km_wise_diesel_revisions(
    request,
    contract,
    company_id,
    rate_category,
    from_km_list,
    to_km_list,
    value_list,
    choice_prefix="choice_",
):
    diesel_types = request.POST.getlist("diesel_adj_type[]")
    diesel_amounts = request.POST.getlist("diesel_adj_amount[]")
    diesel_dates = request.POST.getlist("diesel_effective_date[]")

    for i in range(len(from_km_list)):
        if i >= len(diesel_types):
            break
        adj_type = (diesel_types[i] or "").strip()
        if not adj_type:
            continue
        choice = request.POST.get(f"{choice_prefix}{i+1}", "mt")
        save_diesel_revision(
            company_id=company_id,
            contract=contract,
            rate_category=rate_category,
            effective_from=diesel_dates[i] if i < len(diesel_dates) else None,
            adjustment_type=adj_type,
            adjustment_amount=diesel_amounts[i] if i < len(diesel_amounts) else None,
            choice=choice,
            base_value=value_list[i],
            from_km=from_km_list[i],
            to_km=to_km_list[i],
        )


def revisions_for_contract(contract_id, company_id, rate_category=None):
    qs = RateSlabRevision.objects.filter(contract_id=contract_id, company_id=company_id)
    if rate_category:
        qs = qs.filter(rate_category=rate_category)
    return qs.order_by("-effective_from", "-created_at")
