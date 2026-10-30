"""
Status helpers. Statuses live in ``StatusOption`` rows (editable in the admin
panel). If none exist yet for a resource, the registry defaults are used, so
the application works on an empty database.
"""
from dataclasses import dataclass

from .registry import registry
from .request_cache import memo


@dataclass(frozen=True)
class StatusInfo:
    key: str
    label: str
    state: str
    color: str
    order: int = 0


DONE_WORDS = {"completed", "complete", "done", "finished", "live", "approved", "published", "posted", "achieved",
              "attended", "engaged", "committed", "won", "delivered", "listed"}
DROPPED_WORDS = {"rejected", "cancelled", "canceled", "lost", "declined", "dropped", "failed"}


def guess_state(label):
    """(state, color) for a status first seen in an import: "Completed" or "Done" counts as done, not open."""
    words = set(label.lower().replace("-", " ").replace("_", " ").split())
    if words & DONE_WORDS and "not" not in words:
        return "completed", "success"
    if words & DROPPED_WORDS:
        return "closed", "danger"
    return "open", "info"


def _defaults(resource_key):
    resource = registry.get(resource_key)
    if not resource:
        return []
    return [
        StatusInfo(key, label, state, color, i)
        for i, (key, label, state, color) in enumerate(resource.default_statuses)
    ]


def get_statuses(resource_key, include_inactive=False):
    rows = [info for info, active in memo("statuses", _load_all).get(resource_key, []) if include_inactive or active]
    return rows or _defaults(resource_key)


def _load_all():
    """{resource: [(StatusInfo, is_active), ...]} for every resource in one query (cached per request)."""
    from .models import StatusOption

    out = {}
    for s in StatusOption.objects.order_by("order", "label"):
        out.setdefault(s.resource, []).append((StatusInfo(s.key, s.label, s.state, s.color, s.order), s.is_active))
    return out


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
