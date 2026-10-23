import datetime
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.analytics.services import DashboardData
from apps.core.models import DashboardItem, Target
from apps.core.periods import resolve_period
from apps.products.models import Product

from .factories import create_record, form_data


def test_pages_work_on_empty_database(admin_user, login):
    client = login(admin_user)
    for url in [reverse("analytics:dashboard"), reverse("products:list"), reverse("tasks:overview"),
                reverse("reports:index"), reverse("search:global") + "?q=abc", reverse("notifications:list"),
                reverse("admin_panel:index"), reverse("integrations:list"), reverse("listings:platform_report"),
                reverse("accounts:profile")]:
        assert client.get(url).status_code == 200, url


def test_seed_creates_six_products_and_dashboards_load(admin_user, login):
    call_command("seed_initial")
    call_command("seed_initial")  # idempotent
    assert Product.objects.count() == 7
    from apps.listings.models import ListingPlatform

    assert ListingPlatform.objects.count() >= 70
    client = login(admin_user)
    for slug in ["proceaze", "shifteaze", "ricroot", "rcsl", "payeaze", "veracity", "nextedge"]:
        resp = client.get(reverse("products:dashboard", args=[slug]))
        assert resp.status_code == 200
        assert len(resp.context["module_cards"]) == 10


def test_kpis_reflect_database(admin_user, products, platform, login):
    a, b = products
    create_record("listings", a, platform, status="approved")
    create_record("advertising", a, actual_spend=Decimal("2500"), budget=Decimal("4000"), leads=7)
    create_record("advertising", b, suffix="2", actual_spend=Decimal("500"), budget=Decimal("1000"), leads=3)
    create_record("tasks", a, due_date=timezone.localdate() - datetime.timedelta(days=2))
    create_record("events", a, leads_collected=4)

    data = DashboardData(admin_user, [a, b], resolve_period({}))
    k = data.kpis()
    assert k["listings_approved"] == 1
    assert k["ad_spend"] == Decimal("3000")
    assert k["ad_leads"] == 10
    assert k["leads"] == 14
    assert k["overdue_tasks"] == 1

    only_a = DashboardData(admin_user, [a], resolve_period({}), product=a).kpis()
    assert only_a["ad_spend"] == Decimal("2500")


def test_adding_record_updates_dashboards(admin_user, products, login):
    a, _ = products
    client = login(admin_user)
    before = client.get(reverse("products:dashboard", args=[a.slug])).context["k"]["activities"]
    org_before = client.get(reverse("analytics:dashboard")).context["k"]["activities"]
    client.post(reverse("products:record_create", args=[a.slug, "meetings"]), form_data("meetings", a))
    after = client.get(reverse("products:dashboard", args=[a.slug])).context["k"]["activities"]
    org_after = client.get(reverse("analytics:dashboard")).context["k"]["activities"]
    assert after == before + 1
    assert org_after == org_before + 1


def test_period_and_product_filters(admin_user, products, login):
    a, b = products
    create_record("consultants", a)
    client = login(admin_user)
    assert client.get(reverse("analytics:dashboard") + "?product=shifteaze").context["k"]["activities"] == 0
    assert client.get(reverse("analytics:dashboard") + "?product=proceaze").context["k"]["activities"] == 1
    for p in ["today", "7d", "30d", "quarter", "custom&start=2020-01-01&end=2030-01-01"]:
        assert client.get(reverse("analytics:dashboard") + f"?period={p}").status_code == 200
    resp = client.get(reverse("analytics:dashboard") + "?period=30d", HTTP_HX_REQUEST="true")
    assert resp.templates[0].name == "dashboard/_org_content.html"


def test_dashboard_layout_configuration_persists(admin_user, products, login):
    client = login(admin_user)
    data = {f"kpi_visible_{k}": "on" for k in ["products", "activities"]}
    data.update({"section_visible_kpis": "on", "section_order_kpis": "0"})
    client.post(reverse("admin_panel:dashboard_layout"), data)
    assert DashboardItem.objects.filter(product=None, item_type="kpi", is_visible=True).count() == 2
    resp = client.get(reverse("analytics:dashboard"))
    assert [c["key"] for c in resp.context["kpi_cards"]] == ["products", "activities"]
    assert resp.context["sections"] == ["kpis"]


def test_targets_vs_actual(admin_user, products, login):
    a, _ = products
    today = timezone.localdate()
    Target.objects.create(product=a, metric="ad_leads", target_value=20, period_start=today.replace(day=1),
                          period_end=today + datetime.timedelta(days=30))
    create_record("advertising", a, leads=5, start_date=today)
    client = login(admin_user)
    targets = client.get(reverse("products:dashboard", args=[a.slug])).context["targets"]
    assert targets[0]["actual"] == 5 and targets[0]["pct"] == 25


def test_reports_all_formats(admin_user, products, login):
    a, _ = products
    create_record("tasks", a, due_date=timezone.localdate() - datetime.timedelta(days=1))
    client = login(admin_user)
    for t in ["performance", "modules", "overdue", "targets"]:
        resp = client.get(reverse("reports:index") + f"?type={t}&period=all")
        assert resp.status_code == 200 and resp.context["tables"]
        for fmt in ["csv", "xlsx", "pdf"]:
            assert client.get(reverse("reports:index") + f"?type={t}&period=all&format={fmt}").status_code == 200
    overdue = client.get(reverse("reports:index") + "?type=overdue&period=all").context["tables"][0]["rows"]
    assert len(overdue) == 1


def test_global_search_scoped(users, products, login):
    a, b = products
    create_record("investors", a, name="Alpha Capital")
    create_record("investors", b, name="Alpha Ventures")
    client = login(users["member_b"])
    groups = client.get(reverse("search:global") + "?q=Alpha").context["groups"]
    names = [str(o) for g in groups for o in g["items"]]
    assert names == ["Alpha Ventures"]


def test_demo_seed_and_clear(admin_user):
    call_command("seed_demo")
    from apps.tasks.models import Task

    assert Task.objects.filter(title__startswith="[DEMO]").exists()
    call_command("seed_demo", "--clear")
    assert not Task.objects.filter(title__startswith="[DEMO]").exists()


def test_reminders_command_creates_notifications(users, products):
    a, _ = products
    create_record("tasks", a, assigned_to=users["member_a"], due_date=timezone.localdate() - datetime.timedelta(days=1))
    call_command("send_reminders")
    call_command("send_reminders")  # deduplicated
    assert users["member_a"].notifications.count() == 1


def test_dashboard_seo_geo_updates_box(admin_user, products, login):
    from apps.seo_optimization.models import SEOUpdate

    a, _ = products
    SEOUpdate.objects.create(product=a, text="Ranking improved", created_by=admin_user)
    SEOUpdate.objects.create(product=a, text="Cited by ChatGPT", created_by=admin_user)
    client = login(admin_user)
    for url in (reverse("analytics:dashboard"), reverse("products:dashboard", args=[a.slug])):
        card = next(c for c in client.get(url).context["kpi_cards"] if c["key"] == "seo")
        assert card["label"] == "SEO / GEO updates" and card["value"] == 2 and card["url"].endswith("#seo-updates")
