"""
Dashboard aggregation. Every figure is computed live from the database with ORM
aggregation over permission-scoped querysets (no cached KPI values).
"""
import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Sum
from django.urls import reverse
from django.utils import timezone

from apps.accounts.permissions import product_ids_for, scoped_queryset
from apps.audit.models import AuditLog
from apps.core import metrics as m
from apps.core.periods import apply_period
from apps.core.registry import registry
from apps.core.statuses import get_status

from . import layout

User = get_user_model()

PRIMARY_KEYS = ["listings", "community", "seo", "advertising", "events", "outreach", "meetings", "consultants",
                "social",
                "investors"]


class DashboardData:
    def __init__(self, user, products, period, product=None):
        self.user = user
        self.products = list(products)
        self.product_ids = [p.pk for p in self.products]
        self.period = period
        self.product = product
        self.today = timezone.localdate()
        self._cache = {}

    # -- querysets -------------------------------------------------------
    def qs(self, key):
        """All active (non-archived) records of a resource in scope, ignoring the period."""
        if key not in self._cache:
            resource = registry.get(key)
            qs = scoped_queryset(self.user, resource, "read", product=self.product).filter(is_archived=False)
            if self.product is None:
                qs = qs.filter(product_id__in=self.product_ids)
            self._cache[key] = qs
        return self._cache[key]

    def pqs(self, key):
        """Records within the selected period (on the resource's date field)."""
        resource = registry.get(key)
        return apply_period(self.qs(key), resource.date_field, self.period)

    # -- KPIs ------------------------------------------------------------
    def kpis(self):
        k = {}
        k["products"] = len(self.products)
        activities = completed = pending = overdue_followups = 0
        for key in PRIMARY_KEYS:
            res = registry.get(key)
            p = self.pqs(key)
            activities += p.count()
            completed += p.filter(m.completed_q(key)).count()
            pending += p.filter(m.open_q(key)).count()
            overdue_followups += self.qs(key).filter(m.overdue_q(res)).count()
        tasks = self.qs("tasks")
        overdue_tasks = tasks.filter(m.overdue_q(registry.get("tasks"))).count()
        k.update(activities=activities, completed=completed, pending=pending,
                 overdue_tasks=overdue_tasks, overdue_followups=overdue_followups,
                 overdue=overdue_tasks + overdue_followups,
                 completion_pct=m.pct(completed, activities))

        listings = self.pqs("listings")
        k["listings_total"] = listings.count()
        k["listings_approved"] = listings.filter(m.completed_q("listings")).count()

        seo = self.pqs("seo")
        with_target = seo.exclude(measured_ranking=None).exclude(target_ranking=None)
        k["seo_total"] = seo.count()
        k["seo_with_target"] = with_target.count()
        k["seo_on_target"] = with_target.filter(measured_ranking__lte=F("target_ranking")).count()
        k["seo_pct"] = m.pct(k["seo_on_target"], k["seo_with_target"])
        from apps.seo_optimization.models import SEOUpdate

        update_ids = [self.product.pk] if self.product else [
            pid for pid in self.product_ids if pid in set(product_ids_for(self.user, "seo", "read"))]
        k["seo_updates"] = apply_period(SEOUpdate.objects.filter(product_id__in=update_ids), "created_at",
                                        self.period).count()

        ads = self.pqs("advertising").aggregate(spend=Sum("actual_spend"), budget=Sum("budget"), leads=Sum("leads"))
        k["ad_spend"] = ads["spend"] or 0
        k["ad_budget"] = ads["budget"] or 0
        k["ad_leads"] = ads["leads"] or 0
        k["event_leads"] = self.pqs("events").aggregate(v=Sum("leads_collected"))["v"] or 0
        k["lead_records"] = apply_period(self.qs("leads"), "created_at", self.period).count()
        k["leads"] = k["ad_leads"] + k["event_leads"] + k["lead_records"]

        meetings = self.pqs("meetings")
        k["meetings"] = meetings.count()
        k["meetings_completed"] = meetings.filter(m.completed_q("meetings")).count()
        k["meetings_upcoming"] = self.qs("meetings").filter(
            start_at__gte=timezone.now()).filter(m.open_q("meetings")).count()

        k["events_upcoming"] = self.qs("events").filter(
            event_date__gte=self.today, event_date__lte=self.today + datetime.timedelta(days=60)
        ).filter(m.open_q("events")).count()

        cons = self.qs("consultants")
        k["consultants_total"] = cons.count()
        k["consultants_engaged"] = cons.filter(m.completed_q("consultants")).count()

        inv = self.qs("investors")
        k["investors_total"] = inv.count()
        k["investors_active"] = inv.exclude(status__in=["researching", "ready_for_intro", "closed_not_proceeding"]).count()
        k["investors_pct"] = m.pct(k["investors_active"], k["investors_total"])

        social = self.pqs("social").aggregate(likes=Sum("likes"), comments=Sum("comments"), shares=Sum("shares"),
                                              reach=Sum("reach"))
        k["social_posts"] = self.pqs("social").count()
        k["social_published"] = self.pqs("social").filter(m.completed_q("social")).count()
        k["social_engagement"] = sum((social[x] or 0) for x in ("likes", "comments", "shares"))
        k["social_reach"] = social["reach"] or 0
        return k

    # -- drill-down URLs ---------------------------------------------------
    def period_params(self):
        p = self.period or {}
        key = p.get("key") or "all"
        if key == "all" or (not p.get("start") and not p.get("end")):
            return {}
        if key in ("today", "7d", "30d", "quarter", "month"):
            return {"period": key}
        return {"period": "custom", "start": p["start"].isoformat() if p.get("start") else "",
                "end": p["end"].isoformat() if p.get("end") else ""}

    def list_url(self, key, period=False, product=None, **params):
        """Module list page for this dashboard's scope (optionally a specific product)."""
        product = product or self.product
        if product is not None:
            url = reverse("products:records", kwargs={"slug": product.slug, "resource": key})
        else:
            url = reverse("records:list", args=[key])
        if period:
            params = {**self.period_params(), **params}
        return m.with_query(url, **params)

    def drill_url(self, metric, product=None, **params):
        product = product or self.product
        scope = {"product": product.slug} if product is not None else {}
        return m.with_query(reverse("analytics:drilldown"), metric=metric, **scope, **self.period_params(), **params)

    def kpi_cards(self, k):
        cur = "currency"
        cards = {
            "products": m.kpi("Products", k["products"], "bi-boxes", "primary", key="products",
                              url=self.product.get_absolute_url() if self.product else reverse("products:list")),
            "activities": m.kpi("Tracked activities", k["activities"], "bi-activity", "primary",
                                hint=f"{k['completion_pct']}% completed", key="activities",
                                url=self.drill_url("activities")),
            "completed": m.kpi("Completed", k["completed"], "bi-check2-circle", "success", key="completed",
                               url=self.drill_url("completed")),
            "pending": m.kpi("Pending", k["pending"], "bi-hourglass-split", "warning", key="pending",
                             url=self.drill_url("pending")),
            "overdue": m.kpi("Overdue", k["overdue"], "bi-exclamation-triangle", "danger",
                             hint=f"{k['overdue_tasks']} tasks · {k['overdue_followups']} follow-ups", key="overdue",
                             url=self.drill_url("overdue")),
            "listings": m.kpi("Listings approved", k["listings_approved"], "bi-globe2", "info",
                              hint=f"of {k['listings_total']} tracked", key="listings",
                              url=self.list_url("listings", period=True, state="completed")),
            "seo": m.kpi("SEO / GEO updates", k["seo_updates"], "bi-journal-text", "purple",
                         hint=f"{k['seo_total']} keywords tracked · {k['seo_on_target']} on target", key="seo",
                         url=self.list_url("seo") + "#seo-updates"),
            "ad_spend": m.kpi("Ad spend", k["ad_spend"], "bi-cash-stack", "warning", fmt=cur,
                              hint=f"Budget {k['ad_budget']:,.0f}", key="ad_spend",
                              url=self.list_url("advertising", period=True, sort="-actual_spend")),
            "leads": m.kpi("Leads generated", k["leads"], "bi-person-plus", "success",
                           hint=f"Ads {k['ad_leads']} · Events {k['event_leads']} · Contacts {k['lead_records']}",
                           key="leads", url=self.drill_url("leads")),
            "meetings": m.kpi("Customer meetings", k["meetings"], "bi-people", "primary",
                              hint=f"{k['meetings_upcoming']} upcoming", key="meetings",
                              url=self.list_url("meetings", period=True)),
            "events": m.kpi("Upcoming demo events", k["events_upcoming"], "bi-easel2", "info",
                            hint="Next 60 days", key="events", url=self.list_url("events", preset="next_60")),
            "consultants": m.kpi("Consultants engaged", k["consultants_engaged"], "bi-person-badge", "teal",
                                 hint=f"of {k['consultants_total']} in directory", key="consultants",
                                 url=self.list_url("consultants", state="completed")),
            "investors": m.kpi("Investor outreach", k["investors_active"], "bi-bank", "indigo",
                               hint=f"{k['investors_pct']}% of {k['investors_total']} beyond research",
                               key="investors", url=self.list_url("investors", preset="beyond_research")),
            "social": m.kpi("Digital marketing posts", k["social_published"], "bi-share", "pink",
                            hint=f"Published of {k['social_posts']} · {k['social_engagement']:,} engagements · "
                                 f"{k['social_reach']:,} reach", key="social",
                            url=self.list_url("social", period=True, state="completed")),
        }
        visible = layout.visible_keys(layout.kpi_cards(self.product))
        return [cards[key] for key in visible if key in cards]

    # -- drill-down ---------------------------------------------------------
    DRILL_METRICS = {
        "activities": "Tracked activities",
        "completed": "Completed activities",
        "pending": "Pending activities",
        "overdue": "Overdue tasks & follow-ups",
        "leads": "Leads generated",
        "workload": "Open work assigned",
    }

    def drilldown(self, metric, user=None):
        """Sections of records behind a dashboard number: [{resource, queryset, count, url}]."""
        sections = []

        def add(key, qs, **params):
            sections.append({"resource": registry.get(key), "module": registry.module(registry.get(key).module),
                             "queryset": qs, "count": qs.count(), "url": self.list_url(key, **params)})

        if metric in ("activities", "completed", "pending"):
            for key in PRIMARY_KEYS:
                qs = self.pqs(key)
                params = dict(self.period_params())
                if metric == "completed":
                    qs, params["state"] = qs.filter(m.completed_q(key)), "completed"
                elif metric == "pending":
                    qs, params["state"] = qs.filter(m.open_q(key)), "open"
                add(key, qs, **params)
        elif metric == "overdue":
            for res in registry.resources():
                if res.due_field:
                    add(res.key, self.qs(res.key).filter(m.overdue_q(res)), overdue="1")
        elif metric == "leads":
            pp = self.period_params()
            add("advertising", self.pqs("advertising").filter(leads__gt=0), preset="with_leads", sort="-leads", **pp)
            add("events", self.pqs("events").filter(leads_collected__gt=0), preset="with_leads", **pp)
            add("leads", apply_period(self.qs("leads"), "created_at", self.period), **pp)
        elif metric == "workload" and user is not None:
            for res in registry.resources():
                add(res.key, self.qs(res.key).filter(m.open_q(res.key)).filter(assigned_to=user),
                    state="open", assigned=str(user.pk))
        return sections

    # -- module summaries --------------------------------------------------
    def module_cards(self):
        cards = []
        enabled = set(self.product.enabled_module_keys()) if self.product else None
        for module in registry.modules():
            if enabled is not None and module.key not in enabled:
                continue
            res = module.primary_resource
            if res is None:
                continue
            q = self.pqs(res.key)
            total = q.count()
            done = q.filter(m.completed_q(res.key)).count()
            cards.append({
                "module": module, "resource": res, "total": total, "completed": done,
                "pending": q.filter(m.open_q(res.key)).count(),
                "overdue": self.qs(res.key).filter(m.overdue_q(res)).count(),
                "pct": m.pct(done, total),
                "urls": {
                    "total": self.list_url(res.key, period=True),
                    "completed": self.list_url(res.key, period=True, state="completed"),
                    "pending": self.list_url(res.key, period=True, state="open"),
                    "overdue": self.list_url(res.key, overdue="1"),
                },
            })
        return cards

    # -- lists -----------------------------------------------------------------
    def upcoming_deadlines(self, days=14, limit=12):
        horizon = self.today + datetime.timedelta(days=days)
        items = []
        for res in registry.resources():
            if not res.due_field:
                continue
            q = self.qs(res.key).filter(m.open_q(res.key)).filter(
                **{f"{res.due_field}__lte": horizon}).exclude(**{f"{res.due_field}": None}).select_related(
                "product", "assigned_to").order_by(res.due_field)[:limit]
            for obj in q:
                due = getattr(obj, res.due_field)
                items.append({"object": obj, "resource": res, "due": due, "overdue": due < self.today,
                              "label": res.column_label(res.due_field)})
        items.sort(key=lambda x: x["due"])
        return items[:limit]

    def upcoming_meetings(self, limit=6):
        return self.qs("meetings").filter(start_at__gte=timezone.now()).filter(m.open_q("meetings")).select_related(
            "product").order_by("start_at")[:limit]

    def team_workload(self, limit=10):
        rows = {}
        for res in registry.resources():
            q = self.qs(res.key).filter(m.open_q(res.key)).exclude(assigned_to=None)
            annotations = {"open": Count("pk")}
            if res.due_field:
                annotations["overdue"] = Count("pk", filter=m.overdue_q(res))
            for r in q.order_by().values("assigned_to").annotate(**annotations):
                row = rows.setdefault(r["assigned_to"], {"open": 0, "overdue": 0, "tasks": 0})
                row["open"] += r["open"]
                row["overdue"] += r.get("overdue", 0)
                if res.key == "tasks":
                    row["tasks"] += r["open"]
        users = {u.pk: u for u in User.objects.filter(pk__in=rows.keys())}
        out = [{"user": users[uid], "url": self.drill_url("workload", user=uid), **vals}
               for uid, vals in rows.items() if uid in users]
        out.sort(key=lambda r: (-r["open"], -r["overdue"]))
        top = out[:limit]
        mx = max([r["open"] for r in top], default=0)
        for r in top:
            r["pct"] = m.pct(r["open"], mx)
        return top

    def recent_activity(self, limit=12):
        qs = AuditLog.objects.filter(product_id__in=self.product_ids).exclude(
            action__in=["login", "logout", "login_failed", "export"]).select_related("user", "product")
        if self.product is not None:
            qs = qs.filter(product=self.product)
        scope = set(self.product_ids)
        allowed = [r.key for r in registry.resources() if scope & set(product_ids_for(self.user, r.module))]
        return qs.filter(resource__in=allowed)[:limit]

    def product_comparison(self):
        rows = []
        for p in self.products:
            row = {"product": p, "activities": 0, "completed": 0, "overdue": 0}
            for key in PRIMARY_KEYS:
                res = registry.get(key)
                q = self.pqs(key).filter(product=p)
                row["activities"] += q.count()
                row["completed"] += q.filter(m.completed_q(key)).count()
                row["overdue"] += self.qs(key).filter(product=p).filter(m.overdue_q(res)).count()
            row["overdue"] += self.qs("tasks").filter(product=p).filter(m.overdue_q(registry.get("tasks"))).count()
            row["ad_spend"] = self.pqs("advertising").filter(product=p).aggregate(v=Sum("actual_spend"))["v"] or 0
            row["leads"] = (self.pqs("advertising").filter(product=p).aggregate(v=Sum("leads"))["v"] or 0) + \
                (self.pqs("events").filter(product=p).aggregate(v=Sum("leads_collected"))["v"] or 0)
            row["meetings"] = self.pqs("meetings").filter(product=p).count()
            row["investors"] = self.qs("investors").filter(product=p).count()
            row["pct"] = m.pct(row["completed"], row["activities"])
            row["urls"] = {
                "dashboard": p.get_absolute_url(),
                "activities": self.drill_url("activities", product=p),
                "completed": self.drill_url("completed", product=p),
                "overdue": self.drill_url("overdue", product=p),
                "ad_spend": self.list_url("advertising", period=True, product=p, sort="-actual_spend"),
                "leads": self.drill_url("leads", product=p),
                "meetings": self.list_url("meetings", period=True, product=p),
                "investors": self.list_url("investors", product=p),
            }
            rows.append(row)
        return rows

    # -- charts --------------------------------------------------------------
    def charts(self, comparison=None):
        charts = []
        mods = [registry.module(k) for k in PRIMARY_KEYS]
        totals = [self.pqs(k).count() for k in PRIMARY_KEYS]
        done = [self.pqs(k).filter(m.completed_q(k)).count() for k in PRIMARY_KEYS]
        charts.append(m.chart("activity_by_module", "bar", "Activities by module", [mm.short_label for mm in mods],
                              [m.dataset("Tracked", totals, "#C7D2FE"), m.dataset("Completed", done, "#16A34A")],
                              links=[self.list_url(k, period=True) for k in PRIMARY_KEYS]))
        if comparison is not None and len(comparison) > 1:
            charts.append(m.chart(
                "product_comparison", "bar", "Product comparison", [r["product"].name for r in comparison],
                [m.dataset("Activities", [r["activities"] for r in comparison], "#4F46E5"),
                 m.dataset("Completed", [r["completed"] for r in comparison], "#16A34A"),
                 m.dataset("Overdue", [r["overdue"] for r in comparison], "#DC2626")],
                links=[r["urls"]["dashboard"] for r in comparison]))
            charts.append(m.chart(
                "product_spend", "bar", "Ad spend by product", [r["product"].name for r in comparison],
                [m.dataset("Ad spend", [r["ad_spend"] for r in comparison], "#D97706")],
                links=[r["urls"]["ad_spend"] for r in comparison]))
        else:
            ads = list(self.pqs("advertising").order_by("-actual_spend")[:8])
            charts.append(m.chart("ads_budget", "bar", "Ad budget vs spend", [a.name[:24] for a in ads],
                                  [m.dataset("Budget", [a.budget for a in ads], "#CBD5E1"),
                                   m.dataset("Spend", [a.actual_spend for a in ads], "#4F46E5")],
                                  links=[a.get_absolute_url() for a in ads]))
        trend_labels, trend_data = None, [0] * 6
        for k in PRIMARY_KEYS:
            c = m.monthly_trend(self.qs(k), "created_at", "t", "t")
            trend_labels = c["labels"]
            trend_data = [a + b for a, b in zip(trend_data, c["datasets"][0]["data"])]
        charts.append(m.chart("activity_trend", "line", "New activities per month (last 6 months)", trend_labels,
                              [m.dataset("Activities", trend_data, "#4F46E5", tension=0.3, fill=False)]))
        inv_res = registry.get("investors")
        charts.append(m.status_breakdown_chart(self.qs("investors"), inv_res, "investor_pipeline",
                                               "Investor pipeline", kind="bar", base_url=self.list_url("investors")))
        charts.append(m.status_breakdown_chart(self.pqs("listings"), registry.get("listings"), "listing_status",
                                               "Listing approval status", base_url=self.list_url("listings"),
                                               base_params=self.period_params()))
        return charts


def status_label(resource_key, key):
    s = get_status(resource_key, key)
    return s.label if s else key
