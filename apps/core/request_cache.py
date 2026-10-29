"""
Per-request memo for small lookups that one page repeats many times (statuses, enabled modules,
product ids): rendering a product dashboard asked for them ~150 times. Live while a request runs,
emptied when the request ends and whenever one of the cached tables is saved or deleted.
Outside a request (shell, tests calling functions directly, import jobs) nothing is cached.
"""
import threading

from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save

_local = threading.local()

CACHED_MODELS = {"core.StatusOption", "products.ProductModuleConfiguration", "products.Product"}


def memo(key, compute):
    store = getattr(_local, "store", None)
    if store is None:
        return compute()
    if key not in store:
        store[key] = compute()
    return store[key]


def _start(**kwargs):
    _local.store = {}


def _end(**kwargs):
    _local.store = None


def _invalidate(sender, **kwargs):
    if sender._meta.label in CACHED_MODELS and getattr(_local, "store", None) is not None:
        _local.store = {}


request_started.connect(_start)
request_finished.connect(_end)
post_save.connect(_invalidate)
post_delete.connect(_invalidate)
