from django.db.models import Count, Q

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import EmailActivity, Lead


def clean_activity(form, data):
    """Suppress unsubscribed contacts and flag duplicates within a campaign."""
    product = data.get("product")
    email = (data.get("email") or "").strip().lower()
    if not product or not email:
        return
    instance = form.instance
    suppressed = Lead.objects.filter(product=product, email=email, unsubscribed=True).exists()
    if suppressed and not (instance.pk and instance.unsubscribed):
        form.add_error("email", "This contact has unsubscribed for this product. Outreach is suppressed.")
    dupes = EmailActivity.objects.filter(product=product, email=email, campaign=data.get("campaign"),
                                         is_archived=False)
    if instance.pk:
        dupes = dupes.exclude(pk=instance.pk)
    if dupes.exists():
        form.add_error("email", "Duplicate: this contact already has an outreach record in this campaign.")


def clean_lead(form, data):
    product = data.get("product")
    email = (data.get("email") or "").strip().lower()
    if product and email:
        dupes = Lead.objects.filter(product=product, email=email)
        if form.instance.pk:
            dupes = dupes.exclude(pk=form.instance.pk)
        if dupes.exists():
            form.add_error("email", "Duplicate: a lead with this email already exists for this product.")


def sent_qs(qs):
    from django.db.models import Q

    return qs.filter(Q(sent_date__isnull=False) | ~Q(delivery_status="not_sent"))


def replied_qs(qs):
    return qs.filter(reply_status__in=["positive", "neutral", "negative"])


def activity_kpis(qs, ctx):
    sent = sent_qs(qs).count()
    replied = replied_qs(qs).count()
    return [
        m.kpi("Emails tracked", qs.count(), "bi-envelope", link={}),
        m.kpi("Sent", sent, "bi-send", "info", link={"preset": "sent"}),
        m.kpi("Replies", replied, "bi-reply", "success", hint=f"{m.pct(replied, sent)}% reply rate",
              link={"preset": "replied"}),
        m.kpi("Meetings booked", qs.filter(meeting_booked=True).count(), "bi-calendar-check", "success",
              link={"meeting_booked": "1"}),
        m.kpi("Follow-ups due", qs.filter(m.overdue_q(registry.get("outreach"))).count(), "bi-alarm", "danger",
              link={"overdue": "1"}),
    ]


def activity_charts(qs, ctx):
    from django.urls import reverse

    sent = sent_qs(qs).count()
    base = reverse("records:list", args=["outreach"])
    funnel_links = [base, m.with_query(base, preset="sent"), m.with_query(base, preset="replied"),
                    m.with_query(base, reply_status="positive"), m.with_query(base, meeting_booked="1")]
    funnel = m.chart(
        "outreach_funnel", "bar", "Outreach funnel",
        ["Tracked", "Sent", "Replied", "Positive", "Meeting booked"],
        [m.dataset("Contacts", [
            qs.count(), sent,
            qs.filter(reply_status__in=["positive", "neutral", "negative"]).count(),
            qs.filter(reply_status="positive").count(), qs.filter(meeting_booked=True).count(),
        ], "#4F46E5")],
        links=funnel_links,
    )
    by_campaign = list(
        qs.exclude(campaign=None).order_by().values("campaign__name").annotate(
            total=Count("pk"),
            replies=Count("pk", filter=Q(reply_status__in=["positive", "neutral", "negative"])),
            meetings=Count("pk", filter=Q(meeting_booked=True)),
        ).order_by("-total")[:8]
    )
    campaign_chart = m.chart(
        "outreach_campaigns", "bar", "Campaign performance", [r["campaign__name"][:28] for r in by_campaign],
        [m.dataset("Emails", [r["total"] for r in by_campaign], "#CBD5E1"),
         m.dataset("Replies", [r["replies"] for r in by_campaign], "#0EA5E9"),
         m.dataset("Meetings", [r["meetings"] for r in by_campaign], "#16A34A")],
    )
    return [funnel, campaign_chart,
            m.choice_breakdown(qs, "reply_status", EmailActivity.Reply.choices, "outreach_replies",
                               "Reply status", kind="doughnut")]


def campaign_kpis(qs, ctx):
    return [
        m.kpi("Campaigns", qs.count(), "bi-collection", link={}),
        m.kpi("Active", qs.filter(status="active").count(), "bi-play-circle", "primary", link={"status": "active"}),
        m.kpi("Completed", qs.filter(m.completed_q("email_campaigns")).count(), "bi-check2-circle", "success",
              link={"state": "completed"}),
    ]


def lead_kpis(qs, ctx):
    return [
        m.kpi("Leads", qs.count(), "bi-person-lines-fill", link={}),
        m.kpi("Qualified", qs.filter(status="qualified").count(), "bi-person-check", "success",
              link={"status": "qualified"}),
        m.kpi("Customers", qs.filter(status="customer").count(), "bi-trophy", "success", link={"status": "customer"}),
        m.kpi("Unsubscribed (suppressed)", qs.filter(unsubscribed=True).count(), "bi-slash-circle", "secondary",
              link={"unsubscribed": "1"}),
    ]


registry.register(Resource(
    key="outreach",
    module="outreach",
    model_path="outreach.EmailActivity",
    label="Outreach email",
    label_plural="Cold Email Outreach",
    icon="bi-envelope-paper",
    primary=True,
    form_fields=["product", "campaign", "company", "contact_name", "email", "subject", "status", "sent_date", "reply_status", "follow_up_date", "meeting_booked", "assigned_to", "notes"],
    list_columns=["email", "company", "contact_name", "campaign", "product", "sent_date", "reply_status", "follow_up_date", "meeting_booked", "status"],
    search_fields=["email", "company", "contact_name", "subject", "industry"],
    sort_fields=["email", "company", "sent_date", "follow_up_date", "created_at"],
    filter_fields=["campaign", "reply_status", "meeting_booked"],
    default_statuses=[
        ("planned", "Planned", "open", "secondary"),
        ("sent", "Sent", "open", "info"),
        ("follow_up", "Follow-up Due", "open", "warning"),
        ("replied", "Replied", "open", "primary"),
        ("meeting_booked", "Meeting Booked", "completed", "success"),
        ("closed_lost", "Closed — No Interest", "closed", "dark"),
        ("unsubscribed", "Unsubscribed", "closed", "danger"),
    ],
    date_field="sent_date",
    due_field="follow_up_date",
    kpis=activity_kpis,
    charts=activity_charts,
    import_lookups={"campaign": "name"},
    presets={"sent": ("Sent emails", sent_qs), "replied": ("Emails with replies", replied_qs)},
    clean=clean_activity,
    description="Outreach is suppressed automatically for contacts who have unsubscribed.",
))

registry.register(Resource(
    key="email_campaigns",
    module="outreach",
    model_path="outreach.EmailCampaign",
    label="Email campaign",
    label_plural="Email Campaigns",
    icon="bi-collection",
    form_fields=["product", "name", "status", "start_date", "end_date", "assigned_to", "notes"],
    list_columns=["name", "product", "status", "start_date", "end_date", "assigned_to"],
    search_fields=["name", "subject", "description"],
    sort_fields=["name", "start_date", "end_date", "created_at"],
    default_statuses=[
        ("draft", "Draft", "open", "secondary"),
        ("active", "Active", "open", "primary"),
        ("paused", "Paused", "open", "warning"),
        ("completed", "Completed", "completed", "success"),
    ],
    date_field="start_date",
    kpis=campaign_kpis,
))

registry.register(Resource(
    key="leads",
    module="outreach",
    model_path="outreach.Lead",
    label="Lead",
    label_plural="Leads & Contacts",
    icon="bi-person-lines-fill",
    form_fields=["product", "company", "contact_name", "email", "phone", "status", "unsubscribed", "assigned_to", "notes"],
    list_columns=["company", "contact_name", "email", "phone", "product", "status", "unsubscribed"],
    search_fields=["company", "contact_name", "email", "industry", "lead_source"],
    sort_fields=["company", "contact_name", "email", "created_at"],
    filter_fields=["unsubscribed"],
    default_statuses=[
        ("new", "New", "open", "secondary"),
        ("contacted", "Contacted", "open", "info"),
        ("engaged", "Engaged", "open", "primary"),
        ("qualified", "Qualified", "completed", "success"),
        ("customer", "Customer", "completed", "success"),
        ("unqualified", "Unqualified", "closed", "dark"),
    ],
    kpis=lead_kpis,
    clean=clean_lead,
))
