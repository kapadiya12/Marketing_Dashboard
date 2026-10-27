from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.permissions import accessible_products, can_manage_product, module_levels_for_user
from apps.analytics import layout
from apps.analytics.services import DashboardData
from apps.analytics.targets import METRIC_LINKS, target_progress
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.exporting import export_filename, export_tables, requested_format
from apps.core.models import Target
from apps.core.periods import PERIODS, resolve_period
from apps.core.registry import registry
from apps.email_marketing import access as email_marketing
from apps.email_marketing.views import open_url as email_open_url


@login_required
def product_list(request):
    products = accessible_products(request.user)
    cards = []
    period = resolve_period({})
    for p in products:
        data = DashboardData(request.user, [p], period, product=p)
        k = data.kpis()
        cards.append({"product": p, "k": k})
    return render(request, "products/list.html", {"cards": cards})


@login_required
def product_dashboard(request, slug):
    product = get_object_or_404(accessible_products(request.user), slug=slug)
    period = resolve_period(request.GET)
    data = DashboardData(request.user, [product], period, product=product)
    k = data.kpis()
    levels = module_levels_for_user(request.user, product)
    today = timezone.localdate()
    targets = Target.objects.filter(product=product, period_end__gte=today).order_by("period_end")[:8]
    target_rows = target_progress(request.user, targets)
    for t in target_rows:
        res_key, params = METRIC_LINKS.get(t["target"].metric, (None, {}))
        if res_key and levels.get(registry.get(res_key).module, "none") != "none":
            t["url"] = data.list_url(res_key, **params)
    module_cards = [c for c in data.module_cards() if levels.get(c["module"].key, "none") != "none"]
    for c in module_cards:
        c["can_write"] = levels.get(c["module"].key) in ("write", "manage")
        if c["module"].key == email_marketing.MODULE and email_marketing.can_open(request.user, product):
            c["external_url"] = email_open_url(product)
    ctx = {
        "product": product,
        "period": period,
        "periods": PERIODS,
        "k": k,
        "kpi_cards": data.kpi_cards(k),
        "module_cards": module_cards,
        "charts": data.charts(),
        "deadlines": data.upcoming_deadlines(),
        "meetings": data.upcoming_meetings(),
        "activity": data.recent_activity(),
        "targets": target_rows,
        "sections": layout.visible_keys(layout.sections(product)),
        "levels": levels,
        "can_manage": can_manage_product(request.user, product),
        "tasks_resource": registry.get("tasks"),
        "generated_at": timezone.now(),
    }
    fmt = requested_format(request)
    if fmt:
        from apps.analytics.views import dashboard_tables

        log_action(AuditLog.Action.EXPORT, None, request.user, product=product, message=f"Product dashboard ({fmt})")
        tables = dashboard_tables(data, k, deadlines=ctx["deadlines"], activity=ctx["activity"],
                                  targets=ctx["targets"], meetings=ctx["meetings"])
        return export_tables(tables, fmt, export_filename(product.slug, "dashboard"), f"{product.name} dashboard",
                             f"Period: {period['label']} · Generated {timezone.localtime():%Y-%m-%d %H:%M}")
    if request.headers.get("HX-Request") == "true":
        return render(request, "products/_dashboard_content.html", ctx)
    return render(request, "products/dashboard.html", ctx)
