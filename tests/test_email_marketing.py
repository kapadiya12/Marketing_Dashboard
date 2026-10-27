import base64
import hashlib
import hmac
import io
import json
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from apps.email_marketing.access import make_token

URL = "https://mail.example.com"
SECRET = "s" * 40


@pytest.fixture
def linked(settings):
    settings.EMAIL_MARKETING_URL = URL
    settings.EMAIL_MARKETING_SECRET = SECRET


def _decode(token, secret=SECRET):
    """Verify like the email system does (lib/dashboardLink.js) and return the payload."""
    body, sig = token.rsplit(".", 1)
    assert hmac.compare_digest(sig, hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest())
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def _sso_payload(response):
    assert response.status_code == 302 and response["Location"].startswith(f"{URL}/sso?token=")
    return _decode(parse_qs(urlparse(response["Location"]).query)["token"][0])


def test_token_is_signed_short_lived_and_unique(linked, admin_user):
    a, b = make_token("login", admin_user, "RicRoot"), make_token("login", admin_user, "RicRoot")
    payload = _decode(a)
    assert payload["p"] == "login" and payload["u"] == "admin" and payload["v"] == "RicRoot"
    assert _decode(b)["n"] != payload["n"]
    with pytest.raises(AssertionError):
        _decode(a, secret="t" * 40)


def test_open_signs_in_to_the_product_page(linked, admin_user, products, login):
    resp = login(admin_user).get(reverse("email_marketing:open") + "?product=proceaze")
    payload = _sso_payload(resp)
    assert payload["p"] == "login" and payload["v"] == "ProcEaze"
    assert _sso_payload(login(admin_user).get(reverse("email_marketing:open")))["v"] == ""
    assert _sso_payload(login(admin_user).get(reverse("email_marketing:open") + "?view=Horticulture"))["v"] == "Horticulture"


def test_only_cold_email_writers_may_open(linked, users, products, login, client):
    url = reverse("email_marketing:open") + "?product=proceaze"
    assert login(users["member_a"]).get(url).status_code == 302
    assert login(users["viewer_a"]).get(url).status_code == 403
    assert login(users["member_b"]).get(url).status_code == 404  # not their product
    assert login(users["member_a"]).get(reverse("email_marketing:open") + "?view=Horticulture").status_code == 302
    assert _sso_payload(login(users["member_a"]).get(reverse("email_marketing:open") + "?view=Horticulture"))["v"] == ""


def test_link_is_off_until_configured(settings, admin_user, users, products, login):
    settings.EMAIL_MARKETING_URL = settings.EMAIL_MARKETING_SECRET = ""
    client = login(admin_user)
    assert client.get(reverse("email_marketing:open")).status_code == 404
    dash = client.get(reverse("analytics:dashboard")).content.decode()
    assert "Not connected yet" in dash and reverse("email_marketing:summary") not in dash  # setup card for admins
    page = client.get(reverse("products:dashboard", args=["proceaze"])).content.decode()
    assert reverse("email_marketing:open") not in page
    assert 'id="email-marketing-box"' not in login(users["member_a"]).get(reverse("analytics:dashboard")).content.decode()


def test_cold_email_links_open_the_email_dashboard(linked, admin_user, products, login):
    client = login(admin_user)
    tab_url = reverse("email_marketing:open") + "?product=proceaze"
    page = client.get(reverse("products:dashboard", args=["proceaze"])).content.decode()
    assert page.count(f'href="{tab_url}"') >= 2  # module card + sidebar, full page in the same tab
    assert 'target="_blank"' not in page
    records = client.get(reverse("products:records", args=["proceaze", "outreach"])).content.decode()
    assert f'href="{tab_url}"' in records and "Email dashboard" in records
    dash = client.get(reverse("analytics:dashboard")).content.decode()
    assert 'id="email-marketing-box"' in dash and reverse("email_marketing:summary") in dash
    assert "Not connected yet" not in dash


SUMMARY = {"generatedAt": "2026-10-27T10:00:00Z", "products": [
    {"product": "ProcEaze", "sent": 200, "opened": 50, "clicked": 10, "sentToday": 12, "contacts": 120,
     "replied": 6, "mailed": 100},
    {"product": "ShiftEaze", "sent": 100, "opened": 30, "clicked": 5, "sentToday": 0, "contacts": 80,
     "replied": 4, "mailed": 60},
    {"product": "Horticulture", "sent": 40, "opened": 8, "clicked": 2, "sentToday": 3, "contacts": 40,
     "replied": 1, "mailed": 40},
]}


def _respond(payload):
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return response


def test_summary_box_shows_live_figures(linked, admin_user, products, login):
    with mock.patch("urllib.request.urlopen", return_value=_respond(SUMMARY)) as urlopen:
        page = login(admin_user).get(reverse("email_marketing:summary")).content.decode()
        login(admin_user).get(reverse("email_marketing:summary"))  # cached: no second call
    request = urlopen.call_args.args[0]
    assert request.full_url == f"{URL}/api/dashboard/summary"
    assert _decode(request.get_header("Authorization").removeprefix("Bearer "))["p"] == "api"
    assert urlopen.call_count == 1
    assert ">340<" in page and "15 today" in page  # totals over all three products
    assert "Horticulture" in page and "?view=Horticulture" in page and "?product=proceaze" in page


def test_summary_only_shows_the_users_products(linked, users, products, login):
    with mock.patch("urllib.request.urlopen", return_value=_respond(SUMMARY)):
        page = login(users["member_a"]).get(reverse("email_marketing:summary")).content.decode()
    assert "ProcEaze" in page and "ShiftEaze" not in page and "Horticulture" not in page
    assert ">200<" in page


def test_summary_explains_failures(linked, admin_user, products, login):
    error = urllib.error.HTTPError(URL, 401, "Unauthorized", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=error):
        page = login(admin_user).get(reverse("email_marketing:summary")).content.decode()
    assert "refused the connection" in page
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
        page = login(admin_user).get(reverse("email_marketing:summary")).content.decode()
    assert "Waiting for the email system" in page and 'hx-trigger="load delay:20s"' in page


def test_summary_requires_access(linked, users, products, login):
    assert login(users["viewer_a"]).get(reverse("email_marketing:summary")).status_code == 403
