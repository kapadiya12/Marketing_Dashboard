"""Query building for module list pages, exports and the API (search, filters, sorting)."""
from django.db import models
from django.db.models import Q

from . import metrics
from .periods import apply_period, resolve_period


def search_q(resource, term):
    q = Q()
    for f in resource.search_fields:
        q |= Q(**{f"{f}__icontains": term})
    return q


def filter_field_choices(resource, field_name, user=None, base_qs=None):
    """Choices for an extra filter dropdown (choice, boolean or FK fields)."""
    model = resource.model
    field = model._meta.get_field(field_name)
    if field.choices:
        return list(field.choices)
    if isinstance(field, models.BooleanField):
        return [("1", "Yes"), ("0", "No")]
    if isinstance(field, models.ForeignKey):
        rel = field.related_model
        qs = rel.objects.all()
        if hasattr(rel, "RESOURCE_KEY") and base_qs is not None:
            ids = base_qs.exclude(**{f"{field_name}": None}).values_list(f"{field_name}_id", flat=True)
            qs = rel.objects.filter(pk__in=ids)
        return [(str(o.pk), str(o)) for o in qs[:500]]
    if field_name == "related_module":
        from .registry import registry

        return [(m.key, m.label) for m in registry.modules()]
    return []


def apply_filters(qs, resource, params, products_by_slug=None):
    """Apply GET-parameter filters. ``qs`` must already be permission-scoped."""
    archived = params.get("archived", "active")
    if archived == "archived":
        qs = qs.filter(is_archived=True)
    elif archived != "all":
        qs = qs.filter(is_archived=False)

    term = (params.get("q") or "").strip()
    if term:
        qs = qs.filter(search_q(resource, term))

    product = params.get("product")
    if product and products_by_slug is not None:
        p = products_by_slug.get(product)
        qs = qs.filter(product=p) if p else qs.none()

    status = params.getlist("status") if hasattr(params, "getlist") else [params.get("status")]
    status = [s for s in status if s]
    if status:
        qs = qs.filter(status__in=status)

    state = params.get("state")
    if state == "open":
        qs = qs.filter(metrics.open_q(resource.key))
    elif state == "completed":
        qs = qs.filter(metrics.completed_q(resource.key))
    preset = resource.presets.get(params.get("preset") or "")
    if preset:
        qs = preset[1](qs)
    if params.get("overdue") == "1":
        qs = qs.filter(metrics.overdue_q(resource))

    assigned = params.get("assigned")
    if assigned == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned and assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))

    for name in resource.filter_fields:
        value = params.get(name)
        if value in (None, ""):
            continue
        field = resource.model._meta.get_field(name)
        if isinstance(field, models.BooleanField):
            qs = qs.filter(**{name: value == "1"})
        elif isinstance(field, models.ForeignKey):
            if value.isdigit():
                qs = qs.filter(**{f"{name}_id": int(value)})
        else:
            qs = qs.filter(**{name: value})

    tag = params.get("tag")
    if tag and tag.isdigit():
        qs = qs.filter(tags__id=int(tag))

    period = resolve_period(params)
    qs = apply_period(qs, resource.date_field, period)
    return qs


def apply_sort(qs, resource, sort):
    allowed = set(resource.sort_fields) | {"created_at", "updated_at", "status"}
    if sort:
        field = sort.lstrip("-")
        if field in allowed:
            return qs.order_by(sort, "-pk")
    return qs
