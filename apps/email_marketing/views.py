import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.permissions import accessible_products, has_level, is_org_admin
from apps.audit.models import AuditLog
from apps.audit.services import log_action

from .access import MODULE, can_open, email_product_name, is_configured, make_token

SUMMARY_CACHE_KEY = "email_marketing:summary"
SUMMARY_CACHE_SECONDS = 60
_VIEW_NAME = re.compile(r"^[A-Za-z0-9 ]{1,40}$")


@login_required
def open_email_dashboard(request):
    """Sign the user in to the email system and open a product's page (or its overview)."""
    if not is_configured():
        raise Http404("The email marketing link is not configured.")
    product, view = None, ""
    if slug := request.GET.get("product"):
        product = get_object_or_404(accessible_products(request.user), slug=slug)
        view = email_product_name(product)
    elif (name := request.GET.get("view", "")) and is_org_admin(request.user) and _VIEW_NAME.match(name):
        view = name  # an email-only product such as Horticulture; the email app checks the name too
    if not can_open(request.user, product):
        raise PermissionDenied("You need write access to Cold Email to open the email system.")
    log_action(AuditLog.Action.LOGIN, None, request.user, product=product, resource=MODULE,
               message=f"Opened the email system ({view or 'overview'})")
    token = make_token("login", request.user, view)
    return redirect(f"{settings.EMAIL_MARKETING_URL}/sso?token={quote(token)}")


def open_url(product=None, view=""):
    url = reverse("email_marketing:open")
    if product is not None:
        return f"{url}?product={product.slug}"
    return f"{url}?view={quote(view)}" if view else url


def _fetch_summary(user):
    data = cache.get(SUMMARY_CACHE_KEY)
    if data is None:
        req = urllib.request.Request(
            f"{settings.EMAIL_MARKETING_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {make_token('api', user)}", "Accept": "application/json",
                     "User-Agent": "BizDevHub-Dashboard"})
        with urllib.request.urlopen(req, timeout=settings.EMAIL_MARKETING_TIMEOUT) as response:
            data = json.load(response)
        cache.set(SUMMARY_CACHE_KEY, data, SUMMARY_CACHE_SECONDS)
    return data


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else 0


def _summary_rows(user, data):
    """Rows the user may see: email products matching a dashboard product they can read Cold Email for;
    organization administrators also see email-only products (e.g. Horticulture)."""
    admin = is_org_admin(user)
    products = {email_product_name(p).lower(): p for p in accessible_products(user)
                if admin or has_level(user, p, MODULE, "read")}
    rows = []
    for item in data.get("products", []):
        product = products.get(str(item.get("product", "")).lower())
        if product is None and not admin:
            continue
        sent, mailed = item.get("sent", 0), item.get("mailed", 0)
        rows.append({
            "name": product.name if product else item.get("product", ""),
            "product": product,
            "sent": sent, "sent_today": item.get("sentToday", 0), "opened": item.get("opened", 0),
            "clicked": item.get("clicked", 0), "replied": item.get("replied", 0), "mailed": mailed,
            "contacts": item.get("contacts", 0),
            "open_rate": _pct(item.get("opened", 0), sent), "click_rate": _pct(item.get("clicked", 0), sent),
            "reply_rate": _pct(item.get("replied", 0), mailed),
            "url": (open_url(product) if can_open(user, product) else None) if product else open_url(view=item.get("product", "")),
        })
    return sorted(rows, key=lambda r: (-r["sent"], r["name"]))


@login_required
def summary(request):
    """The main dashboard's "Email marketing" box (loaded with htmx after the page)."""
    if not can_open(request.user):
        raise PermissionDenied
    ctx = {"email_open_url": open_url(), "error": None}
    try:
        data = _fetch_summary(request.user)
    except urllib.error.HTTPError as exc:
        ctx["error"] = ("auth" if exc.code in (401, 403) else "unavailable")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        ctx["error"] = "unavailable"
    else:
        rows = _summary_rows(request.user, data)
        totals = {key: sum(r[key] for r in rows) for key in
                  ("sent", "sent_today", "opened", "clicked", "replied", "mailed", "contacts")}
        totals.update(open_rate=_pct(totals["opened"], totals["sent"]),
                      click_rate=_pct(totals["clicked"], totals["sent"]),
                      reply_rate=_pct(totals["replied"], totals["mailed"]))
        ctx.update(rows=rows, totals=totals, generated_at=data.get("generatedAt"))
    return render(request, "email_marketing/_summary.html", ctx)
