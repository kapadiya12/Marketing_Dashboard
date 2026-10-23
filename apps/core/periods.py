import datetime

from django.utils import timezone

PERIODS = [
    ("all", "All time"),
    ("today", "Today"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("quarter", "This quarter"),
    ("month", "This month"),
    ("custom", "Custom range"),
]


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def quarter_bounds(day):
    q_start_month = 3 * ((day.month - 1) // 3) + 1
    start = day.replace(month=q_start_month, day=1)
    end_month = q_start_month + 2
    next_month = datetime.date(day.year + (end_month // 12), (end_month % 12) + 1, 1)
    return start, next_month - datetime.timedelta(days=1)


def resolve_period(params):
    """Return dict(key, label, start, end) from GET params ``period``, ``start``, ``end``."""
    key = params.get("period") or "all"
    today = timezone.localdate()
    start = end = None
    if key == "today":
        start = end = today
    elif key == "7d":
        start, end = today - datetime.timedelta(days=6), today
    elif key == "30d":
        start, end = today - datetime.timedelta(days=29), today
    elif key == "quarter":
        start, end = quarter_bounds(today)
    elif key == "month":
        start = today.replace(day=1)
        end = (start + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    elif key == "custom":
        start, end = _parse_date(params.get("start")), _parse_date(params.get("end"))
        if start and end and end < start:
            start, end = end, start
    else:
        key = "all"
    label = dict(PERIODS).get(key, "All time")
    if key == "custom":
        label = f"{start or '…'} → {end or '…'}"
    return {"key": key, "label": label, "start": start, "end": end}


def apply_period(qs, field, period):
    """Filter a queryset on a Date or DateTime field by an inclusive date range."""
    if not period or (not period["start"] and not period["end"]):
        return qs
    model_field = qs.model._meta.get_field(field)
    is_datetime = model_field.get_internal_type() == "DateTimeField"
    lookup = f"{field}__date" if is_datetime else field
    if period["start"]:
        qs = qs.filter(**{f"{lookup}__gte": period["start"]})
    if period["end"]:
        qs = qs.filter(**{f"{lookup}__lte": period["end"]})
    return qs
