from apps.core import metrics as m
from apps.core.registry import ChildSpec, Resource, registry


def kpis(qs, ctx):
    return [
        m.kpi("Consultants", qs.count(), "bi-person-badge", link={}),
        m.kpi("Engaged", qs.filter(m.completed_q("consultants")).count(), "bi-person-check", "success",
              link={"state": "completed"}),
        m.kpi("In discussion", qs.filter(status__in=["contacted", "in_discussion"]).count(), "bi-chat", "info",
              link={"status": ["contacted", "in_discussion"]}),
        m.kpi("Follow-ups overdue", qs.filter(m.overdue_q(registry.get("consultants"))).count(), "bi-alarm",
              "danger", link={"overdue": "1"}),
    ]


def charts(qs, ctx):
    return [
        m.status_breakdown_chart(qs, registry.get("consultants"), "consultant_status", "Engagement status"),
        m.monthly_trend(qs.exclude(last_interaction_date=None), "last_interaction_date", "consultant_trend",
                        "Latest interactions by month"),
    ]


registry.register(Resource(
    key="consultants",
    module="consultants",
    model_path="consultants.Consultant",
    label="Consultant",
    label_plural="Expert Consultants",
    icon="bi-person-badge",
    primary=True,
    card_view=True,
    form_fields=["product", "name", "organization", "expertise", "email", "phone", "profile_url", "status", "follow_up_date", "assigned_to", "notes"],
    list_columns=["name", "organization", "expertise", "product", "status", "follow_up_date", "assigned_to"],
    search_fields=["name", "organization", "expertise", "industry", "email", "recommendations"],
    sort_fields=["name", "organization", "last_interaction_date", "follow_up_date", "created_at"],
    default_statuses=[
        ("identified", "Identified", "open", "secondary"),
        ("contacted", "Contacted", "open", "info"),
        ("in_discussion", "In Discussion", "open", "warning"),
        ("engaged", "Engaged", "completed", "success"),
        ("on_hold", "On Hold", "open", "dark"),
        ("inactive", "Inactive", "closed", "light"),
    ],
    due_field="follow_up_date",
    kpis=kpis,
    charts=charts,
    column_labels={"assigned_to": "Relationship owner"},
    children=[ChildSpec(
        key="interactions", model_path="consultants.ConsultantInteraction", fk_name="consultant",
        fields=["date", "interaction_type", "summary"], list_fields=["date", "interaction_type", "summary"],
        label="Meeting & interaction history",
    )],
))
