from django.db.models import F

from apps.core import metrics as m
from apps.core.registry import ChildSpec, Resource, registry

from .models import SEOTrackingRecord


def measured(qs):
    return qs.exclude(measured_ranking=None)


def with_target(qs):
    return measured(qs).exclude(target_ranking=None)


def on_target(qs):
    return with_target(qs).filter(measured_ranking__lte=F("target_ranking"))


PRESETS = {
    "measured": ("Ranking recorded", measured),
    "with_target": ("Ranking and target recorded", with_target),
    "on_target": ("On target", on_target),
}


def kpis(qs, ctx):
    n_target = with_target(qs).count()
    n_on = on_target(qs).count()
    return [
        m.kpi("Tracked keywords", qs.count(), "bi-search", link={}),
        m.kpi("On target", n_on, "bi-bullseye", "success", hint=f"of {n_target} with a target",
              link={"preset": "on_target"}),
        m.kpi("Target completion", m.pct(n_on, n_target), "bi-flag", "success", fmt="percent",
              link={"preset": "with_target"}),
        m.kpi("Achieved", qs.filter(m.completed_q("seo")).count(), "bi-trophy", "purple", link={"state": "completed"}),
        m.kpi("SEO / GEO updates", ctx.get("seo_updates", 0), "bi-journal-text", "info",
              hint="Posted in the updates box below", url="#seo-updates"),
    ]


def charts(qs, ctx):
    top = list(qs.exclude(measured_ranking=None).order_by("measured_ranking")[:12])
    rank_chart = m.chart(
        "seo_rankings", "bar", "Current vs target ranking (lower is better)",
        [r.keyword[:30] for r in top],
        [m.dataset("Current ranking", [r.measured_ranking for r in top], m.SERIES_1),
         m.dataset("Target", [r.target_ranking or 0 for r in top], m.SERIES_2)],
        links=[r.get_absolute_url() for r in top],
        empty="No rankings recorded yet. Enter the current ranking on a keyword.",
    )
    return [
        rank_chart,
        m.choice_breakdown(qs, "optimization_type", SEOTrackingRecord.OptimizationType.choices,
                           "seo_types", "Keywords by type (SEO / GEO / AEO)", kind="doughnut"),
        m.status_breakdown_chart(qs, registry.get("seo"), "seo_status", "Progress", kind="bar"),
    ]


registry.register(Resource(
    key="seo",
    module="seo",
    model_path="seo_optimization.SEOTrackingRecord",
    label="Keyword",
    label_plural="SEO, GEO & AEO",
    icon="bi-graph-up-arrow",
    primary=True,
    form_fields=["product", "keyword", "optimization_type", "search_platform", "landing_page_url",
                 "measured_ranking", "target_ranking", "status", "assigned_to", "notes"],
    list_columns=["keyword", "optimization_type", "search_platform", "product", "measured_ranking",
                  "target_ranking", "status", "updated_at"],
    search_fields=["keyword", "landing_page_url", "notes"],
    sort_fields=["keyword", "measured_ranking", "target_ranking", "updated_at", "created_at"],
    filter_fields=["optimization_type", "search_platform"],
    default_statuses=[
        ("planned", "Planned", "open", "secondary"),
        ("in_progress", "In Progress", "open", "info"),
        ("monitoring", "Monitoring", "open", "warning"),
        ("achieved", "Target Achieved", "completed", "success"),
        ("paused", "Paused", "closed", "dark"),
    ],
    kpis=kpis,
    charts=charts,
    presets=PRESETS,
    column_labels={"measured_ranking": "Current ranking", "target_ranking": "Target ranking",
                   "updated_at": "Last updated"},
    description="Track keywords for search engines (SEO), AI assistants (GEO) and answer engines (AEO). "
                "Post quick progress notes in the SEO / GEO updates box.",
    children=[
        ChildSpec(key="updates", model_path="seo_optimization.SEOUpdate", fk_name="record",
                  fields=["text"], list_fields=["created_at", "text"], label="SEO / GEO updates"),
        ChildSpec(key="measurements", model_path="seo_optimization.SEOMeasurement", fk_name="record",
                  fields=["measured_on", "ranking", "source", "notes"],
                  list_fields=["measured_on", "ranking", "source", "notes"], label="Ranking history"),
    ],
))
