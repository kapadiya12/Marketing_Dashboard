from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import CustomFieldDefinition, CustomFieldValue, StatusOption
from apps.integrations.models import IntegrationConfiguration
from apps.outreach.models import EmailActivity, Lead
from apps.tasks.models import Task

from .conftest import PASSWORD
from .factories import create_record, form_data


def _csv(text):
    return SimpleUploadedFile("import.csv", text.encode("utf-8"), content_type="text/csv")


def test_csv_import_valid(admin_user, products, login):
    client = login(admin_user)
    csv = "product,title,priority,status,due_date\nproceaze,Call vendor,high,To Do,2026-12-01\nshifteaze,Send deck,low,todo,\n"
    resp = client.post(reverse("records:import", args=["tasks"]), {"file": _csv(csv)})
    assert resp.status_code == 302
    assert Task.objects.count() == 2
    assert Task.objects.get(title="Call vendor").product.slug == "proceaze"


def test_csv_import_reports_invalid_rows_and_saves_nothing(admin_user, products, login):
    client = login(admin_user)
    csv = "product,title,priority,status\nproceaze,Good row,high,todo\nproceaze,,high,todo\nnope,Bad product,high,todo\n"
    resp = client.post(reverse("records:import", args=["tasks"]), {"file": _csv(csv)})
    assert resp.status_code == 200
    rows = [r for r, _ in resp.context["result"]["errors"]]
    assert rows == [3, 4]
    assert Task.objects.count() == 0


def test_csv_import_unknown_columns_rejected(admin_user, products, login):
    client = login(admin_user)
    resp = client.post(reverse("records:import", args=["tasks"]), {"file": _csv("product,title,hack\nproceaze,x,y\n")})
    assert resp.context["result"]["errors"][0][0] == 1


def test_export_reimport_roundtrip(admin_user, products, login):
    client = login(admin_user)
    create_record("tasks", products[0], title="Roundtrip")
    content = client.get(reverse("records:export", args=["tasks"])).content.decode("utf-8-sig")
    resp = client.post(reverse("records:import", args=["tasks"]), {"file": _csv(content)})
    assert resp.status_code == 302
    assert Task.objects.filter(title="Roundtrip").count() == 2


def test_export_neutralises_formula_injection(admin_user, products, login):
    client = login(admin_user)
    create_record("tasks", products[0], title="=HYPERLINK(\"http://x\")")
    content = client.get(reverse("records:export", args=["tasks"])).content.decode("utf-8-sig")
    assert "'=HYPERLINK" in content


def test_cold_email_duplicate_and_unsubscribe_suppression(admin_user, products, login):
    a, _ = products
    client = login(admin_user)
    data = form_data("outreach", a, suffix="x")
    assert client.post(reverse("records:create", args=["outreach"]), data).status_code == 302
    resp = client.post(reverse("records:create", args=["outreach"]), data)
    assert resp.status_code == 200 and "email" in resp.context["form"].errors  # duplicate
    lead = Lead.objects.get(email="personx@example.com")
    lead.unsubscribed = True
    lead.save()
    data2 = form_data("outreach", a, suffix="x")
    data2["subject"] = "Another"
    camp = create_record("email_campaigns", a)
    data2["campaign"] = str(camp.pk)
    resp = client.post(reverse("records:create", args=["outreach"]), data2)
    assert "unsubscribed" in str(resp.context["form"].errors["email"])
    assert EmailActivity.objects.count() == 1


def test_custom_fields_end_to_end(admin_user, products, login):
    client = login(admin_user)
    resp = client.post(reverse("admin_panel:config_create", args=["custom-fields"]), {
        "resource": "investors", "label": "Ticket size", "key": "ticket_size", "field_type": "currency",
        "required": "on", "order": "0", "show_in_list": "on", "is_active": "on", "choices_text": "",
    })
    assert resp.status_code == 302
    d = CustomFieldDefinition.objects.get(key="ticket_size")
    data = form_data("investors", products[0])
    resp = client.post(reverse("records:create", args=["investors"]), data)
    assert "cf__ticket_size" in resp.context["form"].errors  # required
    data["cf__ticket_size"] = "2500000"
    assert client.post(reverse("records:create", args=["investors"]), data).status_code == 302
    assert Decimal(CustomFieldValue.objects.get(definition=d).value) == Decimal("2500000")
    resp = client.get(reverse("records:list", args=["investors"]))
    assert "cf:ticket_size" in resp.context["columns"]


def test_custom_select_field_requires_options(admin_user, login):
    client = login(admin_user)
    resp = client.post(reverse("admin_panel:config_create", args=["custom-fields"]), {
        "resource": "leads", "label": "Tier", "key": "tier", "field_type": "single_select", "order": "0",
        "is_active": "on", "choices_text": "",
    })
    assert resp.status_code == 200 and "choices_text" in resp.context["form"].errors


def test_custom_status_becomes_available(admin_user, products, login):
    client = login(admin_user)
    client.post(reverse("admin_panel:statuses_materialize"))
    client.post(reverse("admin_panel:config_create", args=["statuses"]), {
        "resource": "tasks", "key": "waiting_client", "label": "Waiting on client", "state": "open",
        "color": "info", "order": "9", "is_active": "on"})
    assert StatusOption.objects.filter(key="waiting_client").exists()
    data = form_data("tasks", products[0])
    data["status"] = "waiting_client"
    assert client.post(reverse("records:create", args=["tasks"]), data).status_code == 302


def test_module_enable_disable_persists(admin_user, products, login):
    a, _ = products
    client = login(admin_user)
    data = {f"enabled_{k}": "on" for k in ["listings", "community", "seo", "advertising", "events", "outreach",
                                            "meetings", "consultants", "social"]}  # investors disabled
    client.post(reverse("admin_panel:product_modules", args=[a.pk]), data)
    assert "investors" not in a.enabled_module_keys()
    resp = client.get(reverse("products:dashboard", args=[a.slug]))
    assert len(resp.context["module_cards"]) == 9


def test_user_and_membership_management(admin_user, products, login):
    a, _ = products
    client = login(admin_user)
    resp = client.post(reverse("admin_panel:user_create"), {
        "username": "newbie", "first_name": "New", "last_name": "User", "email": "newbie@example.com",
        "is_active": "on", "password1": PASSWORD, "password2": PASSWORD, "org_role": ""})
    assert resp.status_code == 302
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(username="newbie")
    resp = client.post(reverse("admin_panel:membership_add", args=[a.pk]),
                       {"user": user.pk, "role": "viewer", "is_active": "on"})
    assert resp.status_code == 302
    assert user.memberships.get().role == "viewer"
    assert user.notifications.exists()


def test_login_throttling(client, users):
    url = reverse("accounts:login")
    for _ in range(5):
        client.post(url, {"username": "member_a", "password": "wrong"})
    resp = client.post(url, {"username": "member_a", "password": PASSWORD})
    assert resp.status_code == 200
    assert "Too many failed" in resp.content.decode()


def test_login_success(client, users):
    resp = client.post(reverse("accounts:login"), {"username": "member_a", "password": PASSWORD})
    assert resp.status_code == 302


def test_integrations_never_claim_connected(admin_user, login):
    client = login(admin_user)
    client.post(reverse("integrations:edit", args=["meta_ads"]), {
        "ad_account_id": "act_1", "app_id": "1", "app_secret": "s3cret", "access_token": "tok", "is_enabled": "on"})
    cfg = IntegrationConfiguration.objects.get(provider="meta_ads")
    assert cfg.status == "not_configured"
    assert "s3cret" not in cfg.secret_data  # encrypted at rest
    assert cfg.secrets["app_secret"] == "s3cret"
    client.post(reverse("integrations:test", args=["meta_ads"]))
    cfg.refresh_from_db()
    assert cfg.status == "error"
    page = client.get(reverse("integrations:edit", args=["meta_ads"])).content.decode()
    assert "s3cret" not in page


def test_security_headers_and_csrf(client, users):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    strict.force_login(users["member_a"])
    resp = strict.post(reverse("records:create", args=["tasks"]), {})
    assert resp.status_code == 403
    resp = client.get(reverse("accounts:login"))
    assert resp["X-Frame-Options"] == "DENY"


