"""Product isolation and role-based access, enforced server-side."""
import pytest
from django.urls import reverse

from apps.accounts.permissions import module_level, scoped_queryset
from apps.core.registry import registry
from apps.products.models import MembershipModulePermission, ProductModuleConfiguration

from .factories import create_record, form_data


def test_anonymous_redirected_to_login(client, products):
    for url in [reverse("analytics:dashboard"), reverse("records:list", args=["tasks"]),
                reverse("products:dashboard", args=["proceaze"]), reverse("admin_panel:index")]:
        resp = client.get(url)
        assert resp.status_code == 302 and "/accounts/login/" in resp["Location"]


def test_user_cannot_see_other_product_by_url(users, products, login):
    a, b = products
    rec_a = create_record("investors", a)
    client = login(users["member_b"])
    assert client.get(rec_a.get_absolute_url()).status_code == 404
    assert client.get(reverse("records:edit", args=["investors", rec_a.pk])).status_code == 404
    assert client.post(reverse("records:archive", args=["investors", rec_a.pk])).status_code == 404
    assert client.get(reverse("products:dashboard", args=[a.slug])).status_code == 404
    assert client.get(reverse("products:records", args=[a.slug, "investors"])).status_code == 404
    resp = client.get(reverse("records:list", args=["investors"]))
    assert resp.context["total_count"] == 0
    rec_a.refresh_from_db()
    assert not rec_a.is_archived


def test_user_cannot_create_in_other_product(users, products, login):
    a, b = products
    client = login(users["member_b"])
    resp = client.post(reverse("records:create", args=["consultants"]), form_data("consultants", a))
    assert resp.status_code == 200  # form error, not saved
    assert "product" in resp.context["form"].errors
    assert not registry.get("consultants").model.objects.exists()


def test_viewer_is_read_only(users, products, login):
    a, _ = products
    rec = create_record("tasks", a)
    client = login(users["viewer_a"])
    assert client.get(rec.get_absolute_url()).status_code == 200
    assert client.get(reverse("records:create", args=["tasks"])).status_code == 403
    assert client.get(reverse("records:edit", args=["tasks", rec.pk])).status_code == 403
    assert client.post(reverse("records:status", args=["tasks", rec.pk]), {"status": "done"}).status_code == 403


def test_team_member_cannot_hard_delete(users, products, login):
    a, _ = products
    rec = create_record("tasks", a)
    client = login(users["member_a"])
    assert client.post(reverse("records:delete", args=["tasks", rec.pk])).status_code == 403
    client = login(users["pm_a"])
    assert client.post(reverse("records:delete", args=["tasks", rec.pk])).status_code == 302


def test_role_defaults(users, products):
    a, _ = products
    assert module_level(users["marketing_a"], a, "listings") == "write"
    assert module_level(users["marketing_a"], a, "investors") == "read"
    assert module_level(users["pm_a"], a, "investors") == "manage"
    assert module_level(users["nobody"], a, "listings") == "none"


def test_module_override_and_disabled_module(users, products, login):
    a, _ = products
    membership = users["member_a"].memberships.get(product=a)
    MembershipModulePermission.objects.create(membership=membership, module="investors", level="none")
    client = login(users["member_a"])
    assert client.get(reverse("products:records", args=[a.slug, "investors"])).status_code == 404
    ProductModuleConfiguration.objects.create(product=a, module="seo", is_enabled=False)
    users["member_a"].__dict__.pop("_membership_cache", None)
    assert client.get(reverse("products:records", args=[a.slug, "seo"])).status_code == 404


def test_shared_record_visible_read_only(users, products, login):
    a, b = products
    rec = create_record("consultants", a)
    rec.shared_products.add(b)
    qs = scoped_queryset(users["member_b"], registry.get("consultants"), "read")
    assert list(qs) == [rec]
    assert not scoped_queryset(users["member_b"], registry.get("consultants"), "write").exists()
    client = login(users["member_b"])
    assert client.get(rec.get_absolute_url()).status_code == 200
    assert client.get(reverse("records:edit", args=["consultants", rec.pk])).status_code == 403


def test_export_respects_permissions(users, products, login):
    a, b = products
    create_record("tasks", a, title="Secret A task")
    create_record("tasks", b, title="B task")
    client = login(users["member_b"])
    content = client.get(reverse("records:export", args=["tasks"])).content.decode()
    assert "B task" in content and "Secret A task" not in content


def test_attachment_download_permission(users, products, login):
    from django.core.files.uploadedfile import SimpleUploadedFile

    a, _ = products
    rec = create_record("tasks", a)
    client = login(users["member_a"])
    f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
    client.post(reverse("records:attachment_upload", args=["tasks", rec.pk]), {"file": f})
    att = rec.attachments.get()
    assert client.get(reverse("records:attachment_download", args=[att.pk])).status_code == 200
    client = login(users["member_b"])
    assert client.get(reverse("records:attachment_download", args=[att.pk])).status_code == 404


def test_attachment_rejects_bad_type(users, products, login):
    from django.core.files.uploadedfile import SimpleUploadedFile

    a, _ = products
    rec = create_record("tasks", a)
    client = login(users["member_a"])
    client.post(reverse("records:attachment_upload", args=["tasks", rec.pk]),
                {"file": SimpleUploadedFile("evil.exe", b"MZ...", content_type="application/octet-stream")})
    client.post(reverse("records:attachment_upload", args=["tasks", rec.pk]),
                {"file": SimpleUploadedFile("fake.pdf", b"not a pdf", content_type="application/pdf")})
    assert not rec.attachments.exists()


def test_admin_panel_access(users, admin_user, products, login):
    client = login(users["member_a"])
    assert client.get(reverse("admin_panel:index")).status_code == 403
    client = login(users["pm_a"])
    assert client.get(reverse("admin_panel:index")).status_code == 200
    assert client.get(reverse("admin_panel:product_edit", args=[products[0].pk])).status_code == 200
    assert client.get(reverse("admin_panel:product_edit", args=[products[1].pk])).status_code == 403
    assert client.get(reverse("admin_panel:users")).status_code == 403
    client = login(admin_user)
    assert client.get(reverse("admin_panel:users")).status_code == 200


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_api_isolation(method, users, products, login):
    a, _ = products
    rec = create_record("tasks", a)
    client = login(users["member_b"])
    url = reverse("api:record_detail", args=["tasks", rec.pk])
    if method == "get":
        resp = client.get(url)
    else:
        resp = getattr(client, method)(url, content_type="application/json", data="{}")
    assert resp.status_code == 404
    resp = client.get(reverse("api:record_list", args=["tasks"]))
    assert resp.json()["count"] == 0


def test_api_crud_for_permitted_user(users, products, login):
    a, _ = products
    client = login(users["member_a"])
    resp = client.post(reverse("api:record_list", args=["tasks"]),
                       {"product": a.pk, "title": "API task", "status": "todo", "priority": "high"},
                       content_type="application/json")
    assert resp.status_code == 201, resp.content
    pk = resp.json()["id"]
    resp = client.patch(reverse("api:record_detail", args=["tasks", pk]), {"status": "done"},
                        content_type="application/json")
    assert resp.status_code == 200
    resp = client.patch(reverse("api:record_detail", args=["tasks", pk]), {"status": "bogus"},
                        content_type="application/json")
    assert resp.status_code == 400
    assert client.get(reverse("api:dashboard_metrics")).status_code == 200
