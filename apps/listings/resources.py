from django.db.models import Count

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import ListingPlatform


def kpis(qs, ctx):
    approved = qs.filter(m.completed_q("listings")).count()
    platforms = ListingPlatform.objects.filter(is_active=True).count()
    slots = platforms * max(ctx.get("product_count", 1), 1)
    from django.urls import reverse

    return [
        m.kpi("Tracked listings", qs.count(), "bi-list-check", link={}),
        m.kpi("Approved", approved, "bi-patch-check", "success", link={"state": "completed"}),
        m.kpi("Submitted / in review", qs.filter(status__in=["submitted", "in_progress"]).count(),
              "bi-hourglass-split", "warning", link={"status": ["submitted", "in_progress"]}),
        m.kpi("Rejected / needs update", qs.filter(status__in=["rejected", "needs_update"]).count(),
              "bi-exclamation-octagon", "danger", link={"status": ["rejected", "needs_update"]}),
        m.kpi("Platform coverage", m.pct(approved, slots), "bi-pie-chart", "primary",
              hint=f"Approved of {slots} platform slots ({platforms} active platforms)", fmt="percent",
              url=reverse("listings:platform_report")),
    ]


def charts(qs, ctx):
    kind_rows = dict(
        qs.order_by().values("platform__kind").annotate(c=Count("pk")).values_list("platform__kind", "c")
    )
    labels = [label for key, label in ListingPlatform.Kind.choices if kind_rows.get(key)]
    data = [kind_rows[key] for key, _ in ListingPlatform.Kind.choices if kind_rows.get(key)]
    return [
        m.status_breakdown_chart(qs, registry.get("listings"), "listing_status", "Approval status"),
        m.chart("listing_kind", "bar", "Listings by platform type", labels, [m.dataset("Listings", data, "#4F46E5")]),
        m.monthly_trend(qs.exclude(submission_date=None), "submission_date", "listing_trend", "Submissions per month"),
    ]


registry.register(Resource(
    key="listings",
    module="listings",
    model_path="listings.ListingRecord",
    label="Listing",
    label_plural="Online Listings",
    icon="bi-globe2",
    primary=True,
    form_fields=["product", "platform", "status", "listing_url", "submission_date", "assigned_to", "notes"],
    list_columns=["platform", "product", "status", "submission_date", "listing_url", "assigned_to"],
    search_fields=["platform__name", "listing_url", "notes"],
    sort_fields=["platform__name", "status", "submission_date", "next_verification_date", "created_at", "updated_at"],
    filter_fields=["platform"],
    default_statuses=[
        ("not_started", "Not Started", "open", "secondary"),
        ("in_progress", "In Progress", "open", "info"),
        ("submitted", "Submitted", "open", "warning"),
        ("approved", "Approved", "completed", "success"),
        ("rejected", "Rejected", "closed", "danger"),
        ("needs_update", "Needs Update", "open", "orange"),
    ],
    date_field="created_at",
    due_field="next_verification_date",
    kpis=kpis,
    charts=charts,
    import_lookups={"platform": "name"},
    creatable_fks={"platform": "name"},
    column_labels={"website_url": "Website"},
    description="Each record is one product's listing on one platform. Type a new platform name to add it to the "
                "catalog; manage the catalog in the admin panel.",
))

