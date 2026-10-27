from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import accessible_products
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core import csvio
from apps.core.exporting import export_filename, export_tables, plain, requested_format
from apps.core.periods import PERIODS, resolve_period
from apps.core.statuses import get_status
from apps.core.templatetags.ui import kpi_text
from apps.email_marketing import access as email_marketing

from . import layout
from .reports import REPORT_PERIODS, REPORT_TYPES, build_report, csv_report, pdf_report, report_period, xlsx_report
from .services import DashboardData

User = get_user_model()


def dashboard_tables(data, k, comparison=None, deadlines=None, workload=None, activity=None, targets=None,
                     meetings=None):
    """Tables used by the dashboard CSV / Excel / PDF exports."""
    tables = [{"title": "Key metrics", "headers": ["Metric", "Value", "Detail"],
               "rows": [[c["label"], kpi_text(c), c["hint"]] for c in data.kpi_cards(k)]}]
    cards = data.module_cards()
    tables.append({"title": "Modules", "headers": ["Module", "Tracked", "Completed", "Pending", "Overdue",
                                                   "Completion %"],
                   "rows": [[c["module"].label, c["total"], c["completed"], c["pending"], c["overdue"], c["pct"]]
                            for c in cards]})
    if comparison and len(comparison) > 1:
        tables.append({"title": "Product comparison",
                       "headers": ["Product", "Activities", "Completed", "Completion %", "Overdue", "Ad spend",
                                   "Leads", "Meetings", "Investors"],
                       "rows": [[r["product"].name, r["activities"], r["completed"], r["pct"], r["overdue"],
                                 r["ad_spend"], r["leads"], r["meetings"], r["investors"]] for r in comparison]})
    if targets is not None:
        tables.append({"title": "Targets vs actual", "headers": ["Target", "From", "To", "Target value", "Actual",
                                                                 "Achieved %"],
                       "rows": [[t["label"], t["target"].period_start, t["target"].period_end, t["target_value"],
                                 t["actual"], t["pct"]] for t in targets]})
    if deadlines is not None:
        tables.append({"title": "Upcoming deadlines", "headers": ["Due", "Overdue", "Module", "Record", "Product",
                                                                  "Assigned to", "Status"],
                       "rows": [[d["due"], d["overdue"], d["resource"].label, str(d["object"]),
                                 d["object"].product.name, plain(d["object"].assigned_to),
                                 get_status(d["resource"].key, d["object"].status).label] for d in deadlines]})
    if meetings is not None:
        tables.append({"title": "Upcoming meetings", "headers": ["When", "Meeting", "Company", "Type"],
                       "rows": [[plain(mt.start_at), mt.title, mt.customer_company, mt.get_meeting_type_display()]
                                for mt in meetings]})
    if workload is not None:
        tables.append({"title": "Team workload", "headers": ["Team member", "Open items", "Open tasks", "Overdue"],
                       "rows": [[plain(w["user"]), w["open"], w["tasks"], w["overdue"]] for w in workload]})
    if activity is not None:
        tables.append({"title": "Recent activity", "headers": ["When", "User", "Action", "Record", "Product"],
                       "rows": [[plain(a.created_at), plain(a.user), a.get_action_display(), a.object_repr,
                                 a.product.name if a.product else ""] for a in activity]})
    return tables


def _dashboard_context(request):
    products = accessible_products(request.user).filter(is_active=True)
    selected = None
    slug = request.GET.get("product")
    if slug:
        selected = products.filter(slug=slug).first()
    scope = [selected] if selected else list(products)
    period = resolve_period(request.GET)
    data = DashboardData(request.user, scope, period, product=selected)
    k = data.kpis()
    comparison = data.product_comparison()
    sections = layout.sections()
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    hero_stats = [
        {"label": "overdue", "value": k["overdue"], "icon": "bi-exclamation-triangle", "url": data.drill_url("overdue")},
        {"label": "pending", "value": k["pending"], "icon": "bi-hourglass-split", "url": data.drill_url("pending")},
        {"label": "upcoming meetings", "value": k["meetings_upcoming"], "icon": "bi-people",
         "url": data.list_url("meetings", preset="upcoming")},
        {"label": "demo days ahead", "value": k["events_upcoming"], "icon": "bi-easel2",
         "url": data.list_url("events", preset="next_60")},
    ]
    return data, k, {
        "greeting": greeting,
        "hero_stats": hero_stats,
        "all_products": products,
        "selected_product": selected,
        "period": period,
        "periods": PERIODS,
        "kpi_cards": data.kpi_cards(k),
        "k": k,
        "comparison": comparison,
        "charts": data.charts(comparison),
        "deadlines": data.upcoming_deadlines(),
        "workload": data.team_workload(),
        "activity": data.recent_activity(),
        "sections": layout.visible_keys(sections),
        "email_marketing_enabled": email_marketing.can_open(request.user),
        "generated_at": timezone.now(),
    }


@login_required
def dashboard(request):
    data, k, ctx = _dashboard_context(request)
    fmt = requested_format(request)
    if fmt:
        scope = ctx["selected_product"].name if ctx["selected_product"] else "All products"
        log_action(AuditLog.Action.EXPORT, None, request.user, product=ctx["selected_product"],
                   message=f"Organization dashboard export ({fmt})")
        tables = dashboard_tables(data, k, comparison=ctx["comparison"], deadlines=ctx["deadlines"],
                                  workload=ctx["workload"], activity=ctx["activity"])
        return export_tables(tables, fmt, export_filename("dashboard", scope), f"Dashboard — {scope}",
                             f"Period: {ctx['period']['label']} · Generated {timezone.localtime():%Y-%m-%d %H:%M}")
    if request.headers.get("HX-Request") == "true":
        return render(request, "dashboard/_org_content.html", ctx)
    return render(request, "dashboard/org.html", ctx)


@login_required
def drilldown(request):
    """The records behind a dashboard number, grouped by module, with links and exports."""
    metric = request.GET.get("metric", "activities")
    if metric not in DashboardData.DRILL_METRICS:
        raise Http404
    products = accessible_products(request.user).filter(is_active=True)
    slug = request.GET.get("product")
    product = products.filter(slug=slug).first() if slug else None
    if slug and product is None:
        raise Http404
    period = resolve_period(request.GET)
    data = DashboardData(request.user, [product] if product else list(products), period, product=product)
    user = None
    if metric == "workload":
        uid = request.GET.get("user", "")
        user = User.objects.filter(pk=uid).first() if uid.isdigit() else None
        if user is None:
            raise Http404
    sections = [s for s in data.drilldown(metric, user=user) if s["count"]]
    title = DashboardData.DRILL_METRICS[metric] + (f" — {plain(user)}" if user else "")
    scope = product.name if product else "All products"

    fmt = requested_format(request)
    if fmt:
        log_action(AuditLog.Action.EXPORT, None, request.user, product=product, message=f"Drill-down {title} ({fmt})")
        if fmt == "pdf":
            tables = [{"title": f"{s['module'].label} — {s['resource'].label_plural} ({s['count']})",
                       "headers": ["Record", "Product", "Status", "Assigned to", "Created"],
                       "rows": [[str(o), o.product.name, get_status(s["resource"].key, o.status).label,
                                 plain(o.assigned_to), plain(o.created_at)]
                                for o in s["queryset"].select_related("product", "assigned_to")[:2000]]}
                      for s in sections]
        else:
            tables = []
            for s in sections:
                rows = list(csvio.rows_for_export(s["resource"], s["queryset"].select_related("product",
                                                                                            "assigned_to")))
                tables.append({"title": s["resource"].label_plural, "headers": rows[0], "rows": rows[1:]})
        return export_tables(tables, fmt, export_filename(metric, scope), f"{title} — {scope}",
                             f"Period: {period['label']} · Generated {timezone.localtime():%Y-%m-%d %H:%M}")

    for s in sections:
        s["items"] = list(s["queryset"].select_related("product", "assigned_to")[:10])
        if s["resource"].due_field:
            s["due_label"] = s["resource"].column_label(s["resource"].due_field)
    return render(request, "dashboard/drilldown.html", {
        "metric": metric, "title": title, "sections": sections, "product": product, "period": period,
        "total": sum(s["count"] for s in sections), "periods": PERIODS, "metrics": DashboardData.DRILL_METRICS,
        "drill_user": user,
    })


@login_required
def reports(request):
    products = accessible_products(request.user).filter(is_active=True)
    slug = request.GET.get("product", "")
    product = products.filter(slug=slug).first() if slug else None
    report_type = request.GET.get("type", "performance")
    if report_type not in dict(REPORT_TYPES):
        report_type = "performance"
    period = report_period(request.GET)
    scope = [product] if product else list(products)
    tables = build_report(request.user, report_type, scope, period, product=product) if "type" in request.GET else []
    fmt = request.GET.get("format", "html")
    title = f"{dict(REPORT_TYPES)[report_type]} — {product.name if product else 'All products'}"
    subtitle = f"Period: {period['label']} · Generated {timezone.localtime():%Y-%m-%d %H:%M}"
    filename = f"report-{report_type}-{product.slug if product else 'all'}-{timezone.localdate():%Y%m%d}"
    if fmt in ("csv", "xlsx", "pdf") and tables:
        log_action(AuditLog.Action.EXPORT, None, request.user, product=product, message=f"Report {title} ({fmt})")
        if fmt == "csv":
            return csv_report(tables, filename)
        if fmt == "xlsx":
            return xlsx_report(tables, filename)
        return pdf_report(tables, filename, title, subtitle)
    query = request.GET.copy()
    query.pop("format", None)
    return render(request, "reports/index.html", {
        "products": products, "product": product, "report_type": report_type, "report_types": REPORT_TYPES,
        "report_periods": REPORT_PERIODS, "period": period, "tables": tables, "title": title,
        "subtitle": subtitle, "querystring": query.urlencode(),
    })
