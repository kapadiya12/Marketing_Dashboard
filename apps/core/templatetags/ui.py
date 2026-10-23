import datetime
import json
from decimal import Decimal

from django import template
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from ..statuses import get_status

register = template.Library()


def money(value):
    if value in (None, ""):
        return "—"
    symbol = getattr(settings, "CURRENCY_SYMBOL", "₹")
    try:
        v = Decimal(value)
    except Exception:
        return value
    if abs(v) >= 10_000_000:
        return f"{symbol}{v / 10_000_000:.2f} Cr"
    if abs(v) >= 100_000:
        return f"{symbol}{v / 100_000:.2f} L"
    return f"{symbol}{intcomma(int(round(v)))}"


register.filter("money", money)


@register.filter
def kpi_value(card):
    v = card.get("value")
    fmt = card.get("fmt")
    if fmt == "currency":
        return money(v)
    if fmt == "percent":
        return f"{v}%"
    if isinstance(v, (int, Decimal, float)):
        return intcomma(int(v)) if float(v).is_integer() else intcomma(round(float(v), 2))
    return v


@register.simple_tag
def count_attrs(card):
    """data-count attributes so whole-number KPIs count up on load (currency is shown as-is)."""
    v = card.get("value")
    if card.get("fmt") not in ("number", "percent") or isinstance(v, bool):
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if not f.is_integer():
        return ""
    suffix = "%" if card.get("fmt") == "percent" else ""
    return format_html('data-count="{}" data-suffix="{}"', int(f), suffix)


def kpi_text(card):
    """Plain-text KPI value for exports."""
    return str(kpi_value(card))


@register.inclusion_tag("components/status_badge.html")
def status_badge(resource_key, key):
    return {"status": get_status(resource_key, key)}


@register.filter
def text_class(color):
    return "text-dark" if color in ("warning", "light", "info") else "text-white"


@register.simple_tag
def render_cell(obj, column, resource):
    """Render a table cell for a record column (fields, FKs, choices, money, URLs, status, custom fields)."""
    if column.startswith("cf:"):
        value = getattr(obj, "_cf_values", {}).get(column[3:])
        if isinstance(value, list):
            value = ", ".join(value)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return value if value not in (None, "") else mark_safe('<span class="text-muted">—</span>')
    if column == "status":
        s = get_status(resource.key, obj.status)
        if not s:
            return ""
        return format_html('<span class="badge rounded-pill bg-{} {}">{}</span>', s.color, text_class(s.color), s.label)
    try:
        field = obj._meta.get_field(column)
    except Exception:
        field = None
    value = getattr(obj, column, None)
    is_m2m = field is not None and field.many_to_many
    if callable(value) and not is_m2m:
        value = value()
    empty = mark_safe('<span class="text-muted">—</span>')
    if is_m2m:
        items = list(value.all())
        if not items:
            return empty
        return format_html_join(" ", '<span class="badge bg-light text-dark border">{}</span>',
                                ((str(i),) for i in items))
    if field is not None and field.choices:
        display = getattr(obj, f"get_{column}_display")()
        return display if value not in (None, "") else empty
    if value is None or value == "":
        return empty
    if column == "product":
        return format_html('<span class="text-nowrap"><span class="product-dot" style="background:{}"></span>{}</span>',
                           value.brand_color, value.name)
    if isinstance(value, models.Model):
        if hasattr(value, "get_full_name"):
            return value.get_full_name() or value.username
        return str(value)
    if isinstance(value, bool):
        return mark_safe('<i class="bi bi-check-circle-fill text-success"></i>') if value else \
            mark_safe('<i class="bi bi-dash-circle text-muted"></i>')
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).strftime("%d %b %Y, %H:%M")
    if isinstance(value, datetime.date):
        cls = ""
        if resource.due_field == column and value < timezone.localdate():
            from ..statuses import keys_in_state

            if obj.status not in keys_in_state(resource.key, "completed", "closed"):
                cls = "text-danger fw-semibold"
        return format_html('<span class="{}">{}</span>', cls, value.strftime("%d %b %Y"))
    if field is not None and isinstance(field, models.DecimalField) and field.decimal_places == 2 and \
            column not in ("ctr",):
        return money(value)
    if column in ("cpc", "cost_per_lead"):
        return money(value)
    if column == "ctr":
        return f"{value}%"
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        short = value.split("//", 1)[1][:40]
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', value, short)
    if isinstance(value, int):
        return intcomma(value)
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "…"


@register.simple_tag
def field_value(obj, name, resource):
    return render_cell(obj, name, resource)


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    query = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None or v == "":
            query.pop(k, None)
        else:
            query[k] = v
    if "page" not in kwargs:
        query.pop("page", None)
    return query.urlencode()


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def to_json(value):
    return mark_safe(json.dumps(value, default=str).replace("<", "\\u003c"))


@register.simple_tag
def record_create_url(resource, product=None):
    if product is not None:
        return reverse("products:record_create", kwargs={"slug": product.slug, "resource": resource.key})
    return reverse("records:create", kwargs={"resource": resource.key})


@register.filter
def initials(user):
    if not user:
        return "?"
    name = user.get_full_name() or user.username
    parts = name.split()
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


@register.filter
def display_name(user):
    if not user:
        return "—"
    return user.get_full_name() or user.username


@register.filter
def level_badge(level):
    colors = {"none": "light text-muted", "read": "info text-dark", "write": "primary", "manage": "success"}
    return format_html('<span class="badge bg-{}">{}</span>', colors.get(level, "secondary"), level.title())


@register.filter
def sort_icon(current, field):
    if current == field:
        return mark_safe('<i class="bi bi-sort-up"></i>')
    if current == f"-{field}":
        return mark_safe('<i class="bi bi-sort-down"></i>')
    return ""


@register.filter
def next_sort(current, field):
    return f"-{field}" if current == field else field
