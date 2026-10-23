from django.db.models import Sum

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import CommunityPost


def kpis(qs, ctx):
    agg = qs.aggregate(up=Sum("upvotes"), com=Sum("comments_count"), views=Sum("views"))
    activity = (agg["up"] or 0) + (agg["com"] or 0)
    return [
        m.kpi("Questions", qs.count(), "bi-question-circle", link={}),
        m.kpi("Answered", qs.exclude(answer_summary="").count(), "bi-chat-left-text", "info",
              link={"preset": "answered"}),
        m.kpi("Published", qs.filter(m.completed_q("community")).count(), "bi-send-check", "success",
              link={"state": "completed"}),
        m.kpi("Upvotes", agg["up"] or 0, "bi-hand-thumbs-up", "primary", link={"sort": "-upvotes"}),
        m.kpi("Comments", agg["com"] or 0, "bi-chat-dots", "purple", link={"sort": "-comments_count"}),
        m.kpi("Views", agg["views"] or 0, "bi-eye", "teal", link={"sort": "-views"}),
        m.kpi("Total activity", activity, "bi-activity", "warning", hint="Upvotes + comments",
              link={"sort": "-upvotes"}),
    ]


def charts(qs, ctx):
    return [
        m.choice_breakdown(qs, "platform", CommunityPost.Platform.choices, "community_platform", "Questions by platform",
                           kind="doughnut"),
        m.choice_breakdown(qs, "platform", CommunityPost.Platform.choices, "community_engagement",
                           "Upvotes by platform", value="upvotes", value_label="Upvotes"),
        m.status_breakdown_chart(qs, registry.get("community"), "community_status", "Status", kind="bar"),
    ]


registry.register(Resource(
    key="community",
    module="community",
    model_path="community_marketing.CommunityPost",
    label="Question & answer",
    label_plural="Reddit, Quora & Q&A",
    icon="bi-chat-square-text",
    primary=True,
    card_view=True,
    form_fields=["product", "platform", "community", "topic", "answer_summary", "status", "published_url",
                 "publication_date", "upvotes", "comments_count", "views", "assigned_to", "notes"],
    list_columns=["topic", "answer_summary", "platform", "product", "status", "upvotes", "comments_count", "views"],
    search_fields=["topic", "community", "answer_summary", "published_url"],
    sort_fields=["topic", "platform", "publication_date", "upvotes", "comments_count", "views", "created_at"],
    filter_fields=["platform"],
    default_statuses=[
        ("idea", "Idea", "open", "secondary"),
        ("drafting", "Drafting", "open", "info"),
        ("pending_approval", "Pending Approval", "open", "warning"),
        ("published", "Published", "completed", "success"),
        ("follow_up", "Needs Follow-up", "open", "orange"),
        ("rejected", "Rejected / Removed", "closed", "danger"),
    ],
    date_field="created_at",
    kpis=kpis,
    charts=charts,
    presets={"answered": ("Questions with an answer", lambda qs: qs.exclude(answer_summary=""))},
    column_labels={"topic": "Question", "answer_summary": "Answer", "comments_count": "Comments",
                   "community": "Community / subreddit"},
    description="Add the question and your answer; record upvotes, comments and views to see activity. "
                "Use the Q&A view to read questions with their answers.",
))
