"""Small helpers used by resource KPI/chart definitions. All values come from ORM aggregation."""
import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .statuses import get_statuses, keys_in_state

# Status colours (reserved for state) and the validated categorical palette (fixed order, never cycled).
BOOTSTRAP_HEX = {
    "primary": "#2a78d6",
    "secondary": "#94a3b8",
    "success": "#0ca30c",
    "danger": "#d03b3b",
    "warning": "#fab219",
    "info": "#3987e5",
    "dark": "#475569",
    "light": "#cbd5e1",
    "indigo": "#6250d6",
    "purple": "#6250d6",
    "teal": "#1baf7a",
    "orange": "#ec835a",
    "pink": "#e87ba4",
}
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_1, SERIES_2, SERIES_3 = PALETTE[0], PALETTE[1], PALETTE[2]
CONTEXT_TINT = "#b7d3f6"  # light step of series 1, for "total" behind a highlighted subset
CONTEXT_GRAY = "#cbd5e1"  # neutral reference series (e.g. budget behind spend)
CRITICAL = "#d03b3b"

# Legacy hex values used in resource definitions -> palette roles.
_COLOR_MAP = {
    "#4F46E5": SERIES_1, "#0EA5E9": SERIES_2, "#D97706": SERIES_2, "#16A34A": SERIES_3,
    "#DC2626": CRITICAL, "#8B5CF6": PALETTE[6], "#C7D2FE": CONTEXT_TINT, "#CBD5E1": CONTEXT_GRAY,
}


def _map_color(c):
    if isinstance(c, list):
        return [_map_color(x) for x in c]
    return _COLOR_MAP.get(c.upper(), c) if isinstance(c, str) else c


def color_hex(name):
    if name and name.startswith("#"):
        return name
    return BOOTSTRAP_HEX.get(name or "secondary", "#94A3B8")


def kpi(label, value, icon="bi-bar-chart", tone="primary", hint="", fmt="number", key=None, link=None, url=None):
    """
    A KPI card. ``link`` is a dict of list-page filter parameters that shows the records behind
    the number (merged with the page's current filters); ``url`` is an absolute link instead.
    ``exact`` marks cards whose value equals the number of records on the linked page.
    """
    exact = fmt == "number" and isinstance(link, dict) and "sort" not in link
    return {"key": key or label.lower().replace(" ", "_"), "label": label, "value": value, "icon": icon,
            "tone": tone, "hint": hint, "fmt": fmt, "link": link, "url": url, "exact": exact}


def chart(chart_id, kind, title, labels, datasets, options=None, empty=None, links=None, filter=None):
    """
    ``links``: one URL per label (click navigates). ``filter``: {"param": name, "values": [...]} —
    clicking sets that query parameter on the current page (used on module list pages).
    """
    has_data = any(any((v or 0) for v in ds.get("data", [])) for ds in datasets)
    return {"id": chart_id, "type": kind, "title": title, "labels": [str(lab) for lab in labels],
            "datasets": datasets, "options": options or {}, "has_data": has_data,
            "empty": empty or "No data recorded yet.", "links": links, "filter": filter}


def with_query(url, **params):
    """Append query parameters (lists allowed) to a URL."""
    from urllib.parse import urlencode

    params = {k: v for k, v in params.items() if v not in (None, "", [])}
    if not params:
        return url
    return url + ("&" if "?" in url else "?") + urlencode(params, doseq=True)


def dataset(label, data, color=None, **extra):
    d = {"label": label, "data": [float(v) if isinstance(v, Decimal) else (v or 0) for v in data]}
    if color:
        color = _map_color(color)
        d["backgroundColor"] = color
        d["borderColor"] = color
    d.update(extra)
    return d


def total(qs, field):
    return qs.aggregate(v=Sum(field))["v"] or 0


def pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def completed_q(resource_key):
    return Q(status__in=keys_in_state(resource_key, "completed"))


def open_q(resource_key):
    return ~Q(status__in=keys_in_state(resource_key, "completed", "closed"))


def overdue_q(resource):
    if not resource.due_field:
        return Q(pk__in=[])
    return Q(**{f"{resource.due_field}__lt": timezone.localdate()}) & open_q(resource.key)


def status_breakdown_chart(qs, resource, chart_id="status", title="Status breakdown", kind="doughnut",
                           base_url=None, base_params=None):
    counts = dict(qs.order_by().values("status").annotate(c=Count("pk")).values_list("status", "c"))
    statuses = get_statuses(resource.key, include_inactive=True)
    labels, data, colors, keys = [], [], [], []
    for s in statuses:
        if counts.get(s.key):
            labels.append(s.label)
            data.append(counts[s.key])
            colors.append(color_hex(s.color))
            keys.append(s.key)
    known = {s.key for s in statuses}
    for key, c in counts.items():
        if key not in known:
            labels.append(key)
            data.append(c)
            colors.append("#94A3B8")
            keys.append(key)
    links = [with_query(base_url, **(base_params or {}), status=k) for k in keys] if base_url else None
    return chart(chart_id, kind, title, labels, [dataset("Records", data, colors)], links=links,
                 filter=None if base_url else {"param": "status", "values": keys})


def choice_breakdown(qs, field, choices, chart_id, title, kind="bar", value=None, value_label="Records",
                     clickable=True):
    agg = Sum(value) if value else Count("pk")
    rows = dict(qs.order_by().values(field).annotate(v=agg).values_list(field, "v"))
    labels = [label for key, label in choices if rows.get(key)]
    data = [rows[key] for key, _ in choices if rows.get(key)]
    keys = [key for key, _ in choices if rows.get(key)]
    colors = PALETTE[: len(labels)] if kind in ("doughnut", "pie") else PALETTE[0]
    return chart(chart_id, kind, title, labels, [dataset(value_label, data, colors)],
                 filter={"param": field, "values": keys} if clickable else None)


def monthly_trend(qs, date_field, chart_id, title, months=6, value=None, label="Records"):
    today = timezone.localdate()
    # First day of the month (months - 1) calendar months ago, so the window ends with the current month.
    total = today.year * 12 + (today.month - 1) - (months - 1)
    start = datetime.date(total // 12, total % 12 + 1, 1)
    is_datetime = qs.model._meta.get_field(date_field).get_internal_type() == "DateTimeField"
    filt = {f"{date_field}__date__gte" if is_datetime else f"{date_field}__gte": start}
    agg = Sum(value) if value else Count("pk")
    rows = (
        qs.filter(**filt).order_by().annotate(m=TruncMonth(date_field)).values("m").annotate(v=agg).order_by("m")
    )
    by_month = {}
    for r in rows:
        m = r["m"]
        if isinstance(m, datetime.datetime):
            m = m.date()
        if m:
            by_month[m.replace(day=1)] = r["v"] or 0
    labels, data = [], []
    cursor = start
    for _ in range(months):
        labels.append(cursor.strftime("%b %Y"))
        data.append(by_month.get(cursor, 0))
        cursor = (cursor + datetime.timedelta(days=32)).replace(day=1)
    return chart(chart_id, "line", title, labels, [dataset(label, data, "#4F46E5", tension=0.3, fill=False)])
