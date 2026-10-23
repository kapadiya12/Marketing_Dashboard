"""Target metrics: each computes an actual value for a product and date range using scoped querysets."""
from django.db.models import Sum

from apps.accounts.permissions import scoped_queryset
from apps.core import metrics as m
from apps.core.periods import apply_period
from apps.core.registry import registry


def _qs(user, key, product, start, end, field=None):
    resource = registry.get(key)
    qs = scoped_queryset(user, resource, "read", product=product).filter(is_archived=False)
    return apply_period(qs, field or resource.date_field, {"start": start, "end": end})


def _count(key, extra=None, field=None):
    def fn(user, product, start, end):
        qs = _qs(user, key, product, start, end, field)
        if extra is not None:
            qs = qs.filter(extra(key))
        return qs.count()
    return fn


def _sum(key, value_field, field=None):
    def fn(user, product, start, end):
        return _qs(user, key, product, start, end, field).aggregate(v=Sum(value_field))["v"] or 0
    return fn


METRICS = {
    "listings_approved": ("Listings approved", _count("listings", m.completed_q, "updated_at")),
    "community_published": ("Community posts published", _count("community", m.completed_q, "publication_date")),
    "seo_targets_achieved": ("SEO/GEO/AEO targets achieved", _count("seo", m.completed_q, "updated_at")),
    "ad_spend": ("Advertising spend", _sum("advertising", "actual_spend")),
    "ad_leads": ("Advertising leads", _sum("advertising", "leads")),
    "events_attended": ("Demo days attended", _count("events", m.completed_q)),
    "event_leads": ("Leads from demo days", _sum("events", "leads_collected")),
    "emails_sent": ("Cold emails sent", lambda u, p, s, e: _qs(u, "outreach", p, s, e).exclude(
        delivery_status="not_sent").count()),
    "email_meetings": ("Meetings booked from email", lambda u, p, s, e: _qs(u, "outreach", p, s, e).filter(
        meeting_booked=True).count()),
    "customer_meetings": ("Customer meetings held", _count("meetings", m.completed_q)),
    "consultants_engaged": ("Consultants engaged", _count("consultants", m.completed_q, "updated_at")),
    "investor_meetings": ("Investor meetings / pitches", lambda u, p, s, e: _qs(u, "investors", p, s, e, "meeting_date")
                          .exclude(meeting_date=None).count()),
    "tasks_completed": ("Tasks completed", lambda u, p, s, e: _qs(u, "tasks", p, s, e, "completed_at").count()),
}

METRIC_CHOICES = [(k, v[0]) for k, v in METRICS.items()]

# Where a target's "actual" records can be viewed: metric -> (resource, list filters)
METRIC_LINKS = {
    "listings_approved": ("listings", {"state": "completed"}),
    "community_published": ("community", {"state": "completed"}),
    "seo_targets_achieved": ("seo", {"state": "completed"}),
    "ad_spend": ("advertising", {"sort": "-actual_spend"}),
    "ad_leads": ("advertising", {"preset": "with_leads", "sort": "-leads"}),
    "events_attended": ("events", {"state": "completed"}),
    "event_leads": ("events", {"preset": "with_leads"}),
    "emails_sent": ("outreach", {"preset": "sent"}),
    "email_meetings": ("outreach", {"meeting_booked": "1"}),
    "customer_meetings": ("meetings", {"state": "completed"}),
    "consultants_engaged": ("consultants", {"state": "completed"}),
    "investor_meetings": ("investors", {"view": "calendar"}),
    "tasks_completed": ("tasks", {"state": "completed"}),
}


def target_progress(user, targets):
    out = []
    for t in targets:
        label, fn = METRICS.get(t.metric, (t.metric, None))
        actual = fn(user, t.product, t.period_start, t.period_end) if fn else 0
        target_value = float(t.target_value)
        out.append({
            "target": t,
            "label": t.label or label,
            "actual": actual,
            "target_value": t.target_value,
            "pct": min(round(float(actual) * 100 / target_value), 999) if target_value else 0,
            "is_money": t.metric == "ad_spend",
        })
    return out
