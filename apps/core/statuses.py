"""
Status helpers. Statuses live in ``StatusOption`` rows (editable in the admin
panel). If none exist yet for a resource, the registry defaults are used, so
the application works on an empty database.
"""
from dataclasses import dataclass

from .registry import registry


@dataclass(frozen=True)
class StatusInfo:
    key: str
    label: str
    state: str
    color: str
    order: int = 0


def _defaults(resource_key):
    resource = registry.get(resource_key)
    if not resource:
        return []
    return [
        StatusInfo(key, label, state, color, i)
        for i, (key, label, state, color) in enumerate(resource.default_statuses)
    ]


def get_statuses(resource_key, include_inactive=False):
    from .models import StatusOption

    qs = StatusOption.objects.filter(resource=resource_key)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    rows = [StatusInfo(s.key, s.label, s.state, s.color, s.order) for s in qs.order_by("order", "label")]
    return rows or _defaults(resource_key)


def get_status(resource_key, key):
    for s in get_statuses(resource_key, include_inactive=True):
        if s.key == key:
            return s
    if key:
        return StatusInfo(key, key.replace("_", " ").title(), "open", "secondary")
    return None


def status_choices(resource_key):
    return [(s.key, s.label) for s in get_statuses(resource_key)]


def keys_in_state(resource_key, *states):
    return [s.key for s in get_statuses(resource_key, include_inactive=True) if s.state in states]


def default_status(resource_key):
    statuses = get_statuses(resource_key)
    return statuses[0].key if statuses else ""
