"""Minimal valid form data for every registered resource, used by CRUD and permission tests."""
from apps.core.registry import registry


def form_data(resource_key, product, platform=None, suffix="1"):
    base = {"product": str(product.pk)}
    data = {
        "listings": {"platform": platform.name if platform else "", "status": "not_started",
                     "verification_status": "unverified"},
        "community": {"platform": "reddit", "topic": f"Topic {suffix}", "status": "idea", "content_approval": "pending",
                      "upvotes": "0", "comments_count": "0", "views": "0"},
        "seo": {"keyword": f"keyword {suffix}", "optimization_type": "seo", "search_platform": "google",
                "status": "planned", "ai_mentioned": "unknown"},
        "advertising": {"name": f"Campaign {suffix}", "channel": "meta", "objective": "leads", "status": "draft",
                        "budget": "1000", "actual_spend": "400", "impressions": "1000", "reach": "800",
                        "clicks": "50", "leads": "5", "conversions": "1"},
        "events": {"name": f"Demo day {suffix}", "event_mode": "offline", "status": "researching",
                   "leads_collected": "0", "expenses": "0"},
        "outreach": {"company": "Example Co", "email": f"person{suffix}@example.com", "status": "planned",
                     "delivery_status": "not_sent", "reply_status": "no_reply"},
        "email_campaigns": {"name": f"Sequence {suffix}", "status": "draft"},
        "leads": {"company": "Example Co", "email": f"lead{suffix}@example.com", "status": "new"},
        "meetings": {"title": f"Meeting {suffix}", "customer_company": "Example Co", "meeting_type": "online",
                     "status": "scheduled", "start_at": "2026-11-01T10:00", "outcome": "pending"},
        "consultants": {"name": f"Advisor {suffix}", "status": "identified"},
        "investors": {"name": f"Fund {suffix}", "status": "researching", "funding_status": "not_discussed"},
        "tasks": {"title": f"Task {suffix}", "priority": "medium", "status": "todo"},
        "calls": {"channel": "phone", "contact_name": f"Contact {suffix}", "contact_date": "2026-10-28",
                  "outcome": "no_answer", "status": "to_contact"},
        "social": {"platform": "linkedin", "post_type": "post", "title": f"Post {suffix}", "status": "draft",
                   "likes": "0", "comments": "0", "shares": "0", "reach": "0"},
    }[resource_key]
    return {**base, **data}


def create_record(resource_key, product, platform=None, suffix="1", **overrides):
    """Create a record directly through the model (bypassing views)."""
    from django.utils import timezone

    resource = registry.get(resource_key)
    model = resource.model
    data = form_data(resource_key, product, platform, suffix)
    data.pop("product")
    kwargs = {"product": product}
    for k, v in data.items():
        field = model._meta.get_field(k)
        if field.is_relation:
            lookup = resource.creatable_fks.get(k, "pk")
            kwargs[k] = field.related_model.objects.get(**{lookup: v}) if v else None
        elif field.get_internal_type() in ("PositiveIntegerField", "PositiveBigIntegerField"):
            kwargs[k] = int(v)
        elif field.get_internal_type() == "DecimalField":
            kwargs[k] = v
        elif field.get_internal_type() == "DateTimeField":
            kwargs[k] = timezone.now()
        elif field.get_internal_type() == "BooleanField" and field.null:
            kwargs[k] = None
        else:
            kwargs[k] = v
    kwargs.update(overrides)
    return model.objects.create(**kwargs)


ALL_RESOURCES = ["listings", "community", "seo", "advertising", "events", "outreach", "email_campaigns", "leads",
                 "meetings", "consultants", "investors", "social", "calls", "tasks"]
