from django import template

from truckmaster.paper import money_txt

register = template.Library()


@register.filter
def tm_amt(value, blank="1"):
    return money_txt(value, blank_zero=str(blank) != "0")


@register.filter
def tm_attr(obj, path):
    val = obj
    for part in str(path).split("."):
        val = getattr(val, part, "") if val is not None else ""
        if callable(val):
            try:
                val = val()
            except TypeError:
                pass
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%d-%m-%Y")
        except Exception:
            return val
    return val if val not in (None, "") else "-"
