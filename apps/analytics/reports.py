"""Report builders. Each returns a list of tables: {"title", "headers", "rows"} respecting user permissions."""
import datetime

from django.utils import timezone

from apps.core import metrics as m
from apps.core.exporting import export_tables
from apps.core.models import Target
from apps.core.periods import quarter_bounds, resolve_period
from apps.core.registry import registry
from apps.core.statuses import get_status

from .services import PRIMARY_KEYS, DashboardData
from .targets import target_progress

REPORT_TYPES = [
    ("performance", "Product-wise performance"),
    ("modules", "Module activity by product"),
    ("overdue", "Overdue tasks & follow-ups"),
    ("targets", "Targets vs actual"),
]

REPORT_PERIODS = [
    ("month", "This month"),
    ("last_month", "Last month"),
    ("quarter", "This quarter"),
    ("last_quarter", "Last quarter"),
    ("30d", "Last 30 days"),
    ("all", "All time"),
    ("custom", "Custom range"),
]


def report_period(params):
    key = params.get("period") or "month"
    today = timezone.localdate()
    if key == "last_month":
        end = today.replace(day=1) - datetime.timedelta(days=1)
        return {"key": key, "label": end.strftime("%B %Y"), "start": end.replace(day=1), "end": end}
    if key == "last_quarter":
        start, _ = quarter_bounds(today)
        prev_end = start - datetime.timedelta(days=1)
        ps, pe = quarter_bounds(prev_end)
        return {"key": key, "label": f"Q{(ps.month - 1) // 3 + 1} {ps.year}", "start": ps, "end": pe}
    period = resolve_period(params)
    if key == "month":
        period["label"] = today.strftime("%B %Y")
    if key == "quarter":
        period["label"] = f"Q{(today.month - 1) // 3 + 1} {today.year}"
    return period


def build_report(user, report_type, products, period, product=None):
    data = DashboardData(user, products, period, product=product)
    tables = []
    if report_type == "performance":
        k = data.kpis()
        tables.append({
            "title": "Summary",
            "headers": ["Metric", "Value"],
            "rows": [
                ["Products in scope", k["products"]], ["Tracked activities", k["activities"]],
                ["Completed", k["completed"]], ["Pending", k["pending"]],
                ["Overdue tasks", k["overdue_tasks"]], ["Overdue follow-ups", k["overdue_followups"]],
                ["Listings approved / tracked", f"{k['listings_approved']} / {k['listings_total']}"],
                ["SEO / GEO updates", k["seo_updates"]],
                ["SEO targets met", f"{k['seo_on_target']} / {k['seo_with_target']}"],
                ["Ad spend", k["ad_spend"]], ["Ad budget", k["ad_budget"]], ["Leads generated", k["leads"]],
                ["Customer meetings", k["meetings"]], ["Upcoming demo events", k["events_upcoming"]],
                ["Consultants engaged", k["consultants_engaged"]],
                ["Investors beyond research", k["investors_active"]],
            ],
        })
        comp = data.product_comparison()
        tables.append({
            "title": "By product",
            "headers": ["Product", "Activities", "Completed", "Completion %", "Overdue", "Ad spend", "Leads",
                        "Meetings", "Investors"],
            "rows": [[r["product"].name, r["activities"], r["completed"], r["pct"], r["overdue"], r["ad_spend"],
                      r["leads"], r["meetings"], r["investors"]] for r in comp],
        })
    elif report_type == "modules":
        headers = ["Module"] + [p.name for p in data.products] + ["Total"]
        rows = []
        for key in PRIMARY_KEYS:
            res = registry.get(key)
            counts = [data.pqs(key).filter(product=p).count() for p in data.products]
            rows.append([registry.module(res.module).label] + counts + [sum(counts)])
        tables.append({"title": "Records created / dated in period", "headers": headers, "rows": rows})
        rows = []
        for key in PRIMARY_KEYS:
            res = registry.get(key)
            counts = [data.pqs(key).filter(product=p).filter(m.completed_q(key)).count() for p in data.products]
            rows.append([registry.module(res.module).label] + counts + [sum(counts)])
        tables.append({"title": "Completed in period", "headers": headers, "rows": rows})
    elif report_type == "overdue":
        rows = []
        for res in registry.resources():
            if not res.due_field:
                continue
            for obj in data.qs(res.key).filter(m.overdue_q(res)).select_related("product", "assigned_to").order_by(
                    res.due_field)[:1000]:
                s = get_status(res.key, obj.status)
                assignee = obj.assigned_to.get_full_name() or obj.assigned_to.username if obj.assigned_to else ""
                due = getattr(obj, res.due_field)
                rows.append([registry.module(res.module).short_label, str(obj), obj.product.name,
                             res.column_label(res.due_field), due, (data.today - due).days,
                             s.label if s else obj.status, assignee])
        rows.sort(key=lambda r: r[4])
        tables.append({"title": "Overdue items", "headers": ["Module", "Record", "Product", "Due field", "Due date",
                                                              "Days overdue", "Status", "Assigned to"], "rows": rows})
    elif report_type == "targets":
        targets = Target.objects.filter(product__in=data.products).select_related("product")
        if period["start"]:
            targets = targets.filter(period_end__gte=period["start"])
        if period["end"]:
            targets = targets.filter(period_start__lte=period["end"])
        rows = [[p["target"].product.name, p["label"], p["target"].period_start, p["target"].period_end,
                 p["target_value"], p["actual"], f"{p['pct']}%"] for p in target_progress(user, targets)]
        tables.append({"title": "Targets vs actual", "headers": ["Product", "Target", "From", "To", "Target value",
                                                                  "Actual", "Achieved"], "rows": rows})
    return tables


def csv_report(tables, filename):
    return export_tables(tables, "csv", filename)


def xlsx_report(tables, filename):
    return export_tables(tables, "xlsx", filename)


def pdf_report(tables, filename, title, subtitle):
    return export_tables(tables, "pdf", filename, title, subtitle)
