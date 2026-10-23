"""Standalone, shareable HTML snapshot of the investor pipeline (no login or internet needed to view)."""
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.metrics import color_hex
from apps.core.statuses import get_statuses



def _d(value):
    return value.isoformat() if value else None


def build_snapshot(queryset, scope="All products", include_private=False, prepared_by="", filters_label=""):
    """Render the snapshot HTML for the given (already permission-scoped) investor queryset."""
    stages = get_statuses("investors", include_inactive=True)
    order = {s.key: i for i, s in enumerate(stages)}
    by_key = {s.key: s for s in stages}
    investors = []
    qs = queryset.select_related("product", "investor_category", "assigned_to").prefetch_related("interactions")
    for x in qs:
        stage = by_key.get(x.status)
        investors.append({
            "id": x.pk,
            "name": x.name,
            "category": x.investor_category.name if x.investor_category else "",
            "product": x.product.name,
            "product_color": x.product.brand_color,
            "stage": x.status,
            "stage_label": stage.label if stage else x.status,
            "stage_hex": color_hex(stage.color if stage else "secondary"),
            "stage_order": order.get(x.status, 99),
            "website": x.website,
            "thesis": x.investment_thesis,
            "industry_focus": x.industry_focus,
            "investment_stage": x.get_investment_stage_display() if x.investment_stage else "",
            "investment_range": x.investment_range,
            "contact_person": x.contact_person,
            "contact_email": x.contact_email if include_private else "",
            "introduction_source": x.introduction_source,
            "owner": (x.assigned_to.get_full_name() or x.assigned_to.username) if x.assigned_to else "",
            "meeting_date": _d(timezone.localtime(x.meeting_date) if x.meeting_date else None),
            "follow_up_date": _d(x.follow_up_date),
            "pitch_deck_url": x.pitch_deck_url,
            "meeting_notes": x.meeting_notes,
            "feedback": x.feedback,
            "notes": x.notes if include_private else "",
            "funding_target": float(x.funding_target) if x.funding_target is not None else None,
            "funding_discussed": float(x.funding_discussed) if x.funding_discussed is not None else None,
            "funding_status": x.get_funding_status_display(),
            "interactions": [{"date": _d(i.date), "type": i.get_interaction_type_display(), "summary": i.summary,
                              "next_step": i.next_step} for i in x.interactions.all()],
        })
    data = {
        "currency": getattr(settings, "CURRENCY_SYMBOL", "₹"),
        "include_private": include_private,
        "stages": [{"key": s.key, "label": s.label, "hex": color_hex(s.color)} for s in stages],
        "investors": investors,
    }
    return render_to_string("investors/snapshot.html", {
        "data": data, "scope": scope, "generated": timezone.localtime(), "include_private": include_private,
        "prepared_by": prepared_by, "filters_label": filters_label, "currency": data["currency"],
    })


