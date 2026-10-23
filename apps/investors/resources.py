from apps.core import metrics as m
from apps.core.registry import ChildSpec, Resource, registry
from apps.core.statuses import get_statuses

STAGE_ORDER = ["researching", "ready_for_intro", "contacted", "intro_requested", "meeting_scheduled",
               "pitch_delivered", "due_diligence", "negotiation", "committed", "closed_not_proceeding"]


def beyond_research(qs):
    return qs.exclude(status__in=["researching", "ready_for_intro", "closed_not_proceeding"])


PRESETS = {"beyond_research": ("Contacted or further along", beyond_research)}


def kpis(qs, ctx):
    return [
        m.kpi("Investors tracked", qs.count(), "bi-bank", link={}),
        m.kpi("Contacted or beyond", beyond_research(qs).count(), "bi-send", "info",
              link={"preset": "beyond_research"}),
        m.kpi("Meetings / pitches", qs.filter(status__in=["meeting_scheduled", "pitch_delivered"]).count(),
              "bi-easel", "primary", link={"status": ["meeting_scheduled", "pitch_delivered"]}),
        m.kpi("Due diligence / negotiation", qs.filter(status__in=["due_diligence", "negotiation"]).count(),
              "bi-search", "warning", link={"status": ["due_diligence", "negotiation"]}),
        m.kpi("Committed (recorded)", qs.filter(status="committed").count(), "bi-trophy", "success",
              hint="Only records explicitly marked committed", link={"status": "committed"}),
        m.kpi("Funding target", m.total(qs, "funding_target"), "bi-currency-exchange", "primary",
              fmt="currency", link={"sort": "-funding_target"}),
    ]


def charts(qs, ctx):
    statuses = get_statuses("investors", include_inactive=True)
    counts = {s.key: qs.filter(status=s.key).count() for s in statuses}
    pipeline = m.chart(
        "investor_pipeline", "bar", "Fundraising pipeline", [s.label for s in statuses],
        [m.dataset("Investors", [counts[s.key] for s in statuses], [m.color_hex(s.color) for s in statuses])],
        options={"indexAxis": "y"}, filter={"param": "status", "values": [s.key for s in statuses]},
    )
    by_category = list(
        qs.exclude(investor_category=None).order_by().values_list("investor_category_id", "investor_category__name")
        .annotate(c=m.Count("pk")).order_by("-c")
    )
    cat_chart = m.chart("investor_categories", "doughnut", "By investor category",
                        [r[1] for r in by_category],
                        [m.dataset("Investors", [r[2] for r in by_category], m.PALETTE[: len(by_category)])],
                        filter={"param": "investor_category", "values": [str(r[0]) for r in by_category]})
    return [pipeline, cat_chart]


registry.register(Resource(
    key="investors",
    module="investors",
    model_path="investors.Investor",
    label="Investor",
    label_plural="Investor Meetings",
    icon="bi-bank",
    primary=True,
    board=True,
    form_fields=["product", "name", "investor_category", "website", "contact_person", "status", "meeting_date", "follow_up_date", "funding_target", "assigned_to", "notes"],
    list_columns=["name", "investor_category", "product", "status", "meeting_date", "follow_up_date", "funding_target", "assigned_to"],
    search_fields=["name", "investment_thesis", "industry_focus", "contact_person", "introduction_source"],
    sort_fields=["name", "meeting_date", "follow_up_date", "funding_target", "funding_discussed", "created_at"],
    filter_fields=["investor_category"],
    default_statuses=[
        ("researching", "Researching", "open", "secondary"),
        ("ready_for_intro", "Ready for Introduction", "open", "light"),
        ("contacted", "Contacted", "open", "info"),
        ("intro_requested", "Introduction Requested", "open", "info"),
        ("meeting_scheduled", "Meeting Scheduled", "open", "primary"),
        ("pitch_delivered", "Pitch Delivered", "open", "indigo"),
        ("due_diligence", "Due Diligence", "open", "warning"),
        ("negotiation", "Negotiation", "open", "orange"),
        ("committed", "Committed", "completed", "success"),
        ("closed_not_proceeding", "Closed — Not Proceeding", "closed", "dark"),
    ],
    date_field="created_at",
    due_field="follow_up_date",
    calendar_field="meeting_date",
    presets=PRESETS,
    kpis=kpis,
    charts=charts,
    import_lookups={"investor_category": "name"},
    description="Investor categories are prospective targets only. Never record interest or commitments that "
                "have not been confirmed.",
    children=[ChildSpec(
        key="interactions", model_path="investors.InvestorInteraction", fk_name="investor",
        fields=["date", "interaction_type", "summary", "next_step"],
        list_fields=["date", "interaction_type", "summary", "next_step"],
        label="Interaction history",
    )],
))
