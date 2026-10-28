"""Configurable dashboard sections and KPI cards (persisted in core.DashboardItem)."""
from apps.core.models import DashboardItem

ORG_SECTIONS = [
    ("kpis", "KPI cards"),
    ("email", "Email marketing (live from the email system)"),
    ("charts", "Charts"),
    ("comparison", "Product-wise comparison"),
    ("deadlines", "Upcoming deadlines"),
    ("workload", "Team workload"),
    ("activity", "Recent activity"),
]

PRODUCT_SECTIONS = [
    ("kpis", "KPI cards"),
    ("modules", "Nine module cards"),
    ("charts", "Charts"),
    ("targets", "Targets vs actual"),
    ("deadlines", "Pending tasks & deadlines"),
    ("meetings", "Upcoming meetings"),
    ("activity", "Recent activity"),
]

KPI_CARDS = [
    ("products", "Total products"),
    ("activities", "Tracked activities"),
    ("completed", "Completed activities"),
    ("pending", "Pending activities"),
    ("overdue", "Overdue tasks & follow-ups"),
    ("listings", "Listings (approved / total)"),
    ("seo", "SEO / GEO updates"),
    ("ad_spend", "Advertising spend"),
    ("leads", "Leads generated"),
    ("meetings", "Customer meetings"),
    ("events", "Upcoming demo events"),
    ("consultants", "Consultant engagements"),
    ("investors", "Investor outreach progress"),
    ("social", "Digital marketing posts"),
    ("calls", "Cold calls & messages"),
]


# KPI cards hidden unless an administrator turns them on (Admin panel -> Dashboard layout).
DEFAULT_HIDDEN = {"products", "overdue", "listings"}


def _ordered(product, item_type, defaults):
    rows = {r.key: r for r in DashboardItem.objects.filter(product=product, item_type=item_type)}
    if product is not None and not rows:
        rows = {r.key: r for r in DashboardItem.objects.filter(product__isnull=True, item_type=item_type)}
    items = []
    for i, (key, label) in enumerate(defaults):
        row = rows.get(key)
        items.append({"key": key, "label": label, "order": row.order if row else i,
                      "visible": row.is_visible if row else key not in DEFAULT_HIDDEN})
    return sorted(items, key=lambda x: x["order"])


def sections(product=None):
    return _ordered(product, DashboardItem.SECTION, PRODUCT_SECTIONS if product else ORG_SECTIONS)


def kpi_cards(product=None):
    return _ordered(product, DashboardItem.KPI, KPI_CARDS)


def visible_keys(items):
    return [i["key"] for i in items if i["visible"]]
