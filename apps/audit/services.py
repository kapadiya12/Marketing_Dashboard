import datetime
import decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from .middleware import client_ip, get_current_request
from .models import AuditLog

SENSITIVE_FIELDS = {"password", "secret", "token", "access_token", "refresh_token", "client_secret", "_secret_data", "secret_data"}


def _json_safe(value):
    if isinstance(value, Model):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "name") and hasattr(value, "url"):  # FieldFile
        return value.name or ""
    return value


def diff_instances(before: dict, after: dict):
    changes = {}
    for key in set(before) | set(after):
        if key in SENSITIVE_FIELDS:
            continue
        b, a = _json_safe(before.get(key)), _json_safe(after.get(key))
        if b != a:
            changes[key] = {"from": b, "to": a}
    return changes


def snapshot(instance, fields=None):
    data = {}
    for f in instance._meta.concrete_fields:
        if fields and f.name not in fields:
            continue
        if f.name in SENSITIVE_FIELDS:
            continue
        data[f.name] = getattr(instance, f.name)
    return data


def log_action(action, obj=None, user=None, changes=None, message="", product=None, resource=""):
    request = get_current_request()
    if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        user = request.user
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    ct = None
    object_id = ""
    object_repr = ""
    if obj is not None:
        ct = ContentType.objects.get_for_model(obj.__class__)
        object_id = str(obj.pk or "")
        object_repr = str(obj)[:255]
        if product is None:
            product = getattr(obj, "product", None) if hasattr(obj, "product_id") else None
        if not resource:
            resource = getattr(obj, "RESOURCE_KEY", "") or ""
    return AuditLog.objects.create(
        user=user,
        action=action,
        content_type=ct,
        object_id=object_id,
        object_repr=object_repr,
        resource=resource or "",
        product=product,
        changes={k: v for k, v in (changes or {}).items() if k not in SENSITIVE_FIELDS},
        message=message[:255],
        ip_address=client_ip(request),
    )
