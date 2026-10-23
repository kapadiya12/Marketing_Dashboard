"""Simple cache-based login throttling keyed by username and client IP."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(username, ip):
    raw = f"{(username or '').lower()}|{ip or ''}"
    return "login-fail:" + hashlib.sha256(raw.encode()).hexdigest()


def is_locked(username, ip):
    return cache.get(_key(username, ip), 0) >= settings.LOGIN_MAX_ATTEMPTS


def register_failure(username, ip):
    key = _key(username, ip)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, settings.LOGIN_LOCKOUT_SECONDS)


def reset(username, ip):
    cache.delete(_key(username, ip))
