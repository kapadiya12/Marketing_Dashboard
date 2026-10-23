from django.db.models import Sum

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import AdCampaign


def kpis(qs, ctx):
    agg = qs.aggregate(budget=Sum("budget"), spend=Sum("actual_spend"), impressions=Sum("impressions"),
                       clicks=Sum("clicks"), leads=Sum("leads"), conversions=Sum("conversions"))
    spend = agg["spend"] or 0
    clicks = agg["clicks"] or 0
    impressions = agg["impressions"] or 0
    leads = agg["leads"] or 0
    return [
        m.kpi("Campaigns", qs.count(), "bi-megaphone", link={}),
        m.kpi("Budget", agg["budget"] or 0, "bi-wallet2", "info", fmt="currency", link={"sort": "-budget"}),
        m.kpi("Actual spend", spend, "bi-cash-stack", "warning", fmt="currency", link={"sort": "-actual_spend"}),
        m.kpi("Impressions", impressions, "bi-eye", "primary", link={"sort": "-impressions"}),
        m.kpi("Clicks", clicks, "bi-cursor", "primary", link={"sort": "-clicks"},
              hint=f"CTR {round(clicks * 100 / impressions, 2)}%" if impressions else "CTR —"),
        m.kpi("Leads", leads, "bi-person-plus", "success", link={"preset": "with_leads", "sort": "-leads"},
              hint=f"Cost per lead {round(spend / leads, 2)}" if leads else "Cost per lead —"),
    ]


def charts(qs, ctx):
    top = list(qs.order_by("-actual_spend")[:10])
    budget_vs_spend = m.chart(
        "ads_budget_spend", "bar", "Budget vs actual spend",
        [c.name[:28] for c in top],
        [m.dataset("Budget", [c.budget for c in top], "#CBD5E1"),
         m.dataset("Spend", [c.actual_spend for c in top], "#4F46E5")],
        links=[c.get_absolute_url() for c in top],
    )
    channel_rows = {
        r["channel"]: r for r in qs.order_by().values("channel").annotate(
            leads=Sum("leads"), conversions=Sum("conversions"))
    }
    labels = [label for key, label in AdCampaign.Channel.choices]
    keys = [key for key, _ in AdCampaign.Channel.choices]
    channel_chart = m.chart(
        "ads_channels", "bar", "Leads by channel", labels,
        [m.dataset("Leads", [channel_rows.get(k, {}).get("leads") or 0 for k in keys], m.SERIES_1)],
        filter={"param": "channel", "values": keys},
    )
    return [budget_vs_spend, channel_chart,
            m.monthly_trend(qs.exclude(start_date=None), "start_date", "ads_trend", "Spend by start month",
                            value="actual_spend", label="Spend")]


registry.register(Resource(
    key="advertising",
    module="advertising",
    model_path="advertising.AdCampaign",
    label="Campaign",
    label_plural="Meta & LinkedIn Ads",
    icon="bi-megaphone",
    primary=True,
    form_fields=["product", "name", "channel", "status", "start_date", "end_date", "budget", "actual_spend", "impressions", "clicks", "leads", "assigned_to", "notes"],
    list_columns=["name", "channel", "product", "status", "start_date", "budget", "actual_spend", "clicks", "ctr", "leads", "cost_per_lead"],
    search_fields=["name", "landing_page_url", "external_campaign_id", "notes"],
    sort_fields=["name", "channel", "start_date", "end_date", "budget", "actual_spend", "clicks", "leads",
                 "conversions", "created_at"],
    filter_fields=["channel"],
    default_statuses=[
        ("draft", "Draft", "open", "secondary"),
        ("scheduled", "Scheduled", "open", "info"),
        ("active", "Active", "open", "primary"),
        ("paused", "Paused", "open", "warning"),
        ("completed", "Completed", "completed", "success"),
        ("cancelled", "Cancelled", "closed", "danger"),
    ],
    date_field="start_date",
    due_field="end_date",
    kpis=kpis,
    charts=charts,
    presets={"with_leads": ("Campaigns with leads", lambda qs: qs.filter(leads__gt=0))},
    column_labels={"ctr": "CTR %", "cpc": "CPC", "cost_per_lead": "Cost / lead", "budget_used_pct": "Budget used %"},
))
