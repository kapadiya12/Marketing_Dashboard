from django.utils import timezone

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import CustomerMeeting


def today_qs(qs):
    return qs.filter(start_at__date=timezone.localdate())


def upcoming(qs):
    return qs.filter(start_at__gte=timezone.now()).exclude(m.completed_q("meetings"))


def pipeline(qs):
    return qs.exclude(outcome__in=["lost", "negative"]).exclude(opportunity_value=None)


PRESETS = {
    "today": ("Meetings today", today_qs),
    "upcoming": ("Upcoming meetings", upcoming),
    "pipeline": ("Open opportunities with a value", pipeline),
}


def kpis(qs, ctx):
    return [
        m.kpi("Meetings", qs.count(), "bi-people", link={}),
        m.kpi("Today", today_qs(qs).count(), "bi-calendar-day", "info", link={"preset": "today"}),
        m.kpi("Upcoming", upcoming(qs).count(), "bi-calendar-event", "primary", link={"preset": "upcoming"}),
        m.kpi("Completed", qs.filter(m.completed_q("meetings")).count(), "bi-check2-circle", "success",
              link={"state": "completed"}),
        m.kpi("Follow-ups overdue", qs.filter(m.overdue_q(registry.get("meetings"))).count(), "bi-alarm", "danger",
              link={"overdue": "1"}),
        m.kpi("Pipeline value", m.total(pipeline(qs), "opportunity_value"), "bi-currency-exchange", "success",
              fmt="currency", link={"preset": "pipeline", "sort": "-opportunity_value"}),
    ]


def charts(qs, ctx):
    return [
        m.choice_breakdown(qs, "outcome", CustomerMeeting.Outcome.choices, "meetings_outcome", "Outcomes",
                           kind="doughnut"),
        m.monthly_trend(qs, "start_at", "meetings_trend", "Meetings per month"),
        m.choice_breakdown(qs, "meeting_type", CustomerMeeting.MeetingType.choices, "meetings_type",
                           "Meeting type"),
    ]


registry.register(Resource(
    key="meetings",
    module="meetings",
    model_path="meetings.CustomerMeeting",
    label="Meeting",
    label_plural="Customer Meetings",
    icon="bi-people",
    primary=True,
    form_fields=["product", "title", "customer_company", "contact_person", "meeting_type", "start_at", "meeting_link", "status", "outcome", "follow_up_date", "opportunity_value", "meeting_notes", "assigned_to"],
    list_columns=["title", "customer_company", "product", "meeting_type", "start_at", "status", "outcome", "follow_up_date", "opportunity_value"],
    search_fields=["title", "customer_company", "contact_person", "agenda", "meeting_notes", "requirements"],
    sort_fields=["title", "customer_company", "start_at", "follow_up_date", "opportunity_value", "created_at"],
    filter_fields=["meeting_type", "outcome"],
    default_statuses=[
        ("scheduled", "Scheduled", "open", "info"),
        ("rescheduled", "Rescheduled", "open", "warning"),
        ("completed", "Completed", "completed", "success"),
        ("cancelled", "Cancelled", "closed", "danger"),
        ("no_show", "No-show", "closed", "dark"),
    ],
    date_field="start_at",
    due_field="follow_up_date",
    calendar_field="start_at",
    presets=PRESETS,
    kpis=kpis,
    charts=charts,
))
