from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import ColdCall

POSITIVE = ["interested", "meeting"]


def reached(qs):
    return qs.exclude(outcome="no_answer")


def positive(qs):
    return qs.filter(outcome__in=POSITIVE)


PRESETS = {
    "reached": ("Answered or replied", reached),
    "positive": ("Interested or meeting booked", positive),
}


def kpis(qs, ctx):
    total = qs.count()
    answered = reached(qs).count()
    return [
        m.kpi("Calls & messages", total, "bi-telephone-outbound", link={}),
        m.kpi("Reached", answered, "bi-telephone-inbound", "info", hint=f"{m.pct(answered, total)}% answered",
              link={"preset": "reached"}),
        m.kpi("Interested", positive(qs).count(), "bi-hand-thumbs-up", "success", link={"preset": "positive"}),
        m.kpi("Meetings booked", qs.filter(outcome="meeting").count(), "bi-calendar-check", "primary",
              link={"outcome": "meeting"}),
        m.kpi("Follow-ups overdue", qs.filter(m.overdue_q(registry.get("calls"))).count(), "bi-alarm", "danger",
              link={"overdue": "1"}),
    ]


def charts(qs, ctx):
    return [
        m.choice_breakdown(qs, "outcome", ColdCall.Outcome.choices, "calls_outcome", "Outcomes", kind="doughnut"),
        m.monthly_trend(qs, "contact_date", "calls_trend", "Calls & messages per month"),
        m.choice_breakdown(qs, "channel", ColdCall.Channel.choices, "calls_channel", "Channel"),
    ]


registry.register(Resource(
    key="calls",
    module="calls",
    model_path="cold_calls.ColdCall",
    label="Call / message",
    label_plural="Cold Calls & Messages",
    icon="bi-telephone-outbound",
    primary=True,
    form_fields=["product", "channel", "contact_name", "company", "phone", "contact_date", "outcome", "status",
                 "follow_up_date", "assigned_to", "notes"],
    list_columns=["contact_name", "company", "product", "channel", "contact_date", "outcome", "status",
                  "follow_up_date"],
    search_fields=["contact_name", "company", "phone", "notes"],
    sort_fields=["contact_name", "company", "contact_date", "follow_up_date", "created_at"],
    filter_fields=["channel", "outcome"],
    default_statuses=[
        ("to_contact", "To contact", "open", "info"),
        ("follow_up", "Follow-up due", "open", "warning"),
        ("done", "Done", "completed", "success"),
        ("dropped", "Dropped", "closed", "dark"),
    ],
    date_field="contact_date",
    due_field="follow_up_date",
    calendar_field="follow_up_date",
    presets=PRESETS,
    kpis=kpis,
    charts=charts,
))
