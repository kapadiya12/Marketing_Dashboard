from django.db.models import F, Sum

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import SocialPost


def kpis(qs, ctx):
    agg = qs.aggregate(likes=Sum("likes"), comments=Sum("comments"), shares=Sum("shares"), reach=Sum("reach"))
    engagement = (agg["likes"] or 0) + (agg["comments"] or 0) + (agg["shares"] or 0)
    return [
        m.kpi("Posts", qs.count(), "bi-megaphone", link={}),
        m.kpi("Published", qs.filter(m.completed_q("social")).count(), "bi-send-check", "success",
              link={"state": "completed"}),
        m.kpi("Scheduled", qs.filter(status="scheduled").count(), "bi-calendar-event", "info",
              link={"status": "scheduled"}),
        m.kpi("Reach / views", agg["reach"] or 0, "bi-eye", "primary", link={"sort": "-reach"}),
        m.kpi("Engagement", engagement, "bi-hand-thumbs-up", "purple",
              hint=f"{agg['likes'] or 0} likes · {agg['comments'] or 0} comments · {agg['shares'] or 0} shares",
              link={"sort": "-likes"}),
    ]


def charts(qs, ctx):
    rows = {r["platform"]: r for r in qs.order_by().values("platform").annotate(
        n=Sum(F("likes") + F("comments") + F("shares")))}
    keys = [k for k, _ in SocialPost.Platform.choices if rows.get(k)]
    labels = [lab for k, lab in SocialPost.Platform.choices if rows.get(k)]
    engagement = m.chart("social_engagement", "bar", "Engagement by platform", labels,
                         [m.dataset("Likes + comments + shares", [rows[k]["n"] or 0 for k in keys], m.SERIES_1)],
                         filter={"param": "platform", "values": keys})
    return [
        m.choice_breakdown(qs, "platform", SocialPost.Platform.choices, "social_platforms", "Posts by platform",
                           kind="doughnut"),
        engagement,
        m.monthly_trend(qs.exclude(post_date=None), "post_date", "social_trend", "Posts per month"),
    ]


registry.register(Resource(
    key="social",
    module="social",
    model_path="social_media.SocialPost",
    label="Post",
    label_plural="Digital Marketing Posts",
    icon="bi-share",
    primary=True,
    form_fields=["product", "platform", "post_type", "title", "status", "post_date", "post_url",
                 "likes", "comments", "shares", "reach", "assigned_to", "notes"],
    list_columns=["title", "platform", "post_type", "product", "status", "post_date", "likes", "comments",
                  "shares", "reach"],
    search_fields=["title", "post_url", "notes"],
    sort_fields=["title", "platform", "post_date", "likes", "comments", "shares", "reach", "created_at"],
    filter_fields=["platform", "post_type"],
    default_statuses=[
        ("idea", "Idea", "open", "secondary"),
        ("draft", "Draft", "open", "info"),
        ("scheduled", "Scheduled", "open", "warning"),
        ("published", "Published", "completed", "success"),
        ("cancelled", "Cancelled", "closed", "dark"),
    ],
    date_field="post_date",
    calendar_field="post_date",
    kpis=kpis,
    charts=charts,
    description="Track posts on LinkedIn, Instagram, X (Twitter), Facebook, YouTube and more, with their "
                "likes, comments, shares and reach.",
))
