"""
Link to the email marketing system (the Outreach Console, a separate Node app).

Both apps share ``EMAIL_MARKETING_SECRET`` (``DASHBOARD_LINK_SECRET`` there). A token is
``base64url(JSON payload) + "." + hex HMAC-SHA256(secret, that base64url text)`` with payload
``{"p": purpose, "u": username, "v": view, "exp": unix seconds, "n": nonce}``:

* ``login``: a one-time sign-in link, valid a minute, that opens a product page (``GET /sso``);
* ``api``: a short-lived bearer token for the read-only summary (``GET /api/dashboard/summary``).

The email app has one shared administrator login and sends real email, so only organization
administrators and users with write access to Cold Email for a product may open it.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from django.conf import settings

from apps.accounts.permissions import has_level, is_org_admin, product_ids_for

MODULE = "outreach"
TOKEN_SECONDS = 60


def is_configured():
    return bool(settings.EMAIL_MARKETING_URL) and len(settings.EMAIL_MARKETING_SECRET) >= 32


def can_open(user, product=None):
    """May ``user`` open the email system (for ``product``, or its overview when None)?"""
    if not is_configured() or not user.is_authenticated:
        return False
    if is_org_admin(user):
        return True
    if product is not None:
        return has_level(user, product, MODULE, "write")
    return bool(product_ids_for(user, MODULE, "write"))


def email_product_name(product):
    """The email system's name for a dashboard product (they match by name, e.g. "RicRoot")."""
    return settings.EMAIL_MARKETING_PRODUCTS.get(product.slug, product.name)


def make_token(purpose, user, view=""):
    payload = {"p": purpose, "u": user.get_username(), "v": view, "exp": int(time.time()) + TOKEN_SECONDS,
               "n": secrets.token_urlsafe(16)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(settings.EMAIL_MARKETING_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"
