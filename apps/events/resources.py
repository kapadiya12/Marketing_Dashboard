import datetime

from django.utils import timezone

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import DemoEvent


def upcoming(qs):
    return qs.filter(event_date__gte=timezone.localdate()).exclude(m.completed_q("events"))


def next_60(qs):
    today = timezone.localdate()
    return qs.filter(event_date__gte=today, event_date__lte=today + datetime.timedelta(days=60)).filter(
        m.open_q("events"))


def deadline_14(qs):
    today = timezone.localdate()
    return qs.filter(registration_deadline__gte=today, registration_deadline__lte=today + datetime.timedelta(days=14))


PRESETS = {
    "upcoming": ("Upcoming events", upcoming),
    "next_60": ("Upcoming in the next 60 days", next_60),
    "deadline_14": ("Registration deadline within 14 days", deadline_14),
    "with_leads": ("Events with leads", lambda qs: qs.filter(leads_collected__gt=0)),
}


def kpis(qs, ctx):
    return [
        m.kpi("Events tracked", qs.count(), "bi-easel2", link={}),
        m.kpi("Upcoming", upcoming(qs).count(), "bi-calendar-event", "info", link={"preset": "upcoming"}),
        m.kpi("Registration deadlines (14 days)", deadline_14(qs).count(), "bi-alarm", "warning",
              link={"preset": "deadline_14"}),
        m.kpi("Attended", qs.filter(m.completed_q("events")).count(), "bi-check2-circle", "success",
              link={"state": "completed"}),
        m.kpi("Leads collected", m.total(qs, "leads_collected"), "bi-person-plus", "primary",
              link={"preset": "with_leads", "sort": "-leads_collected"}),
    ]


def charts(qs, ctx):
    top = list(qs.filter(leads_collected__gt=0).order_by("-leads_collected")[:10])
    return [
        m.status_breakdown_chart(qs, registry.get("events"), "events_status", "Registration status"),
        m.chart("events_leads", "bar", "Leads collected per event", [e.name[:28] for e in top],
                [m.dataset("Leads", [e.leads_collected for e in top], "#16A34A")],
                links=[e.get_absolute_url() for e in top]),
        m.choice_breakdown(qs, "event_mode", DemoEvent.Mode.choices, "events_mode", "Online vs offline",
                           kind="doughnut"),
    ]


registry.register(Resource(
    key="events",
    module="events",
    model_path="events.DemoEvent",
    label="Event",
    label_plural="Demo Days",
    icon="bi-easel2",
    primary=True,
    form_fields=["product", "name", "organizer", "event_mode", "location", "event_date", "registration_deadline", "status", "leads_collected", "assigned_to", "notes"],
    list_columns=["name", "organizer", "product", "event_mode", "event_date", "registration_deadline", "status", "leads_collected"],
    search_fields=["name", "organizer", "location", "outcomes"],
    sort_fields=["name", "event_date", "registration_deadline", "leads_collected", "expenses", "created_at"],
    filter_fields=["event_mode"],
    default_statuses=[
        ("researching", "Researching", "open", "secondary"),
        ("applied", "Applied", "open", "info"),
        ("registered", "Registered", "open", "primary"),
        ("confirmed", "Confirmed / Selected", "open", "warning"),
        ("attended", "Attended", "completed", "success"),
        ("not_selected", "Not Selected", "closed", "dark"),
        ("cancelled", "Cancelled", "closed", "danger"),
    ],
    date_field="event_date",
    due_field="follow_up_date",
    calendar_field="event_date",
    presets=PRESETS,
    kpis=kpis,
    charts=charts,
))
