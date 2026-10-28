import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.registry import registry

from .factories import ALL_RESOURCES, create_record, form_data


def test_all_nine_modules_registered():
    keys = [m.key for m in registry.modules()]
    assert keys == ["listings", "community", "seo", "advertising", "events", "outreach", "meetings",
                    "consultants", "investors", "social", "calls"]
    for m in registry.modules():
        assert m.primary_resource is not None


@pytest.mark.parametrize("key", ALL_RESOURCES)
def test_full_crud_cycle(key, admin_user, products, platform, login):
    client = login(admin_user)
    product = products[0]
    resource = registry.get(key)
    model = resource.model

    # list (empty state)
    resp = client.get(reverse("records:list", args=[key]))
    assert resp.status_code == 200

    # create
    resp = client.post(reverse("records:create", args=[key]), form_data(key, product, platform))
    assert resp.status_code == 302, resp.context["form"].errors if resp.context else resp
    obj = model.objects.get()
    assert obj.product == product
    assert obj.created_by == admin_user
    assert AuditLog.objects.filter(action="create", object_id=str(obj.pk)).exists()

    # detail + product-scoped list
    assert client.get(obj.get_absolute_url()).status_code == 200
    resp = client.get(reverse("products:records", args=[product.slug, key]))
    assert resp.status_code == 200 and resp.context["total_count"] == 1

    # edit
    data = form_data(key, product, platform)
    note_field = "notes" if "notes" in resource.form_fields else "meeting_notes"
    data[note_field] = "Updated notes"
    resp = client.post(reverse("records:edit", args=[key, obj.pk]), data)
    assert resp.status_code == 302
    obj.refresh_from_db()
    assert getattr(obj, note_field) == "Updated notes"

    # inline status change
    new_status = [s for s, _ in __import__("apps.core.statuses", fromlist=["x"]).status_choices(key)][1]
    resp = client.post(reverse("records:status", args=[key, obj.pk]), {"status": new_status}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    obj.refresh_from_db()
    assert obj.status == new_status

    # archive / restore
    client.post(reverse("records:archive", args=[key, obj.pk]))
    obj.refresh_from_db()
    assert obj.is_archived
    resp = client.get(reverse("records:list", args=[key]))
    assert resp.context["total_count"] == 0
    client.post(reverse("records:restore", args=[key, obj.pk]))
    obj.refresh_from_db()
    assert not obj.is_archived

    # export
    resp = client.get(reverse("records:export", args=[key]))
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/csv")
    resp = client.get(reverse("records:export", args=[key]) + "?format=xlsx")
    assert resp.status_code == 200

    # delete
    resp = client.post(reverse("records:delete", args=[key, obj.pk]))
    assert resp.status_code == 302
    assert not model.objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize("key", ALL_RESOURCES)
def test_form_validation_errors(key, admin_user, products, login):
    client = login(admin_user)
    resp = client.post(reverse("records:create", args=[key]), {"product": str(products[0].pk)})
    assert resp.status_code == 200
    assert resp.context["form"].errors


def test_list_views_render(admin_user, products, platform, login):
    client = login(admin_user)
    create_record("events", products[0], event_date="2026-10-20")
    create_record("investors", products[0])
    create_record("consultants", products[0])
    assert client.get(reverse("records:list", args=["events"]) + "?view=calendar&month=2026-10").status_code == 200
    assert client.get(reverse("records:list", args=["investors"]) + "?view=board").status_code == 200
    assert client.get(reverse("records:list", args=["consultants"]) + "?view=cards").status_code == 200


def test_search_filter_sort_paginate(admin_user, products, login):
    client = login(admin_user)
    for i in range(30):
        create_record("tasks", products[0], suffix=str(i), title=f"Task {i}", priority="high" if i % 2 else "low")
    url = reverse("records:list", args=["tasks"])
    resp = client.get(url)
    assert resp.context["page"].paginator.count == 30
    assert len(resp.context["page"].object_list) == 25
    assert client.get(url + "?page=2").context["page"].number == 2
    assert client.get(url + "?q=Task 1").context["total_count"] == 11  # 1, 10-19
    assert client.get(url + "?priority=high").context["total_count"] == 15
    resp = client.get(url + "?sort=title")
    assert resp.context["page"].object_list[0].title == "Task 0"
    resp = client.get(url + "?q=Task", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="record-results")
    assert resp.templates[0].name == "records/_results.html"


def test_bulk_actions(admin_user, products, login):
    client = login(admin_user)
    t1 = create_record("tasks", products[0], suffix="a")
    t2 = create_record("tasks", products[0], suffix="b")
    url = reverse("records:bulk", args=["tasks"])
    client.post(url, {"ids": [t1.pk, t2.pk], "action": "status", "status": "done"})
    t1.refresh_from_db()
    assert t1.status == "done" and t1.completed_at is not None
    client.post(url, {"ids": [t1.pk, t2.pk], "action": "archive"})
    t2.refresh_from_db()
    assert t2.is_archived


def test_child_records_and_measurement_updates_parent(admin_user, products, login):
    client = login(admin_user)
    rec = create_record("seo", products[0], target_ranking=5)
    url = reverse("records:child_add", args=["seo", rec.pk, "measurements"])
    client.post(url, {"measured_on": "2026-09-01", "ranking": "30"})
    client.post(url, {"measured_on": "2026-10-01", "ranking": "4", "ai_mentioned": "true"})
    rec.refresh_from_db()
    assert rec.measured_ranking == 4
    assert rec.baseline_ranking == 30
    assert rec.on_target is True


def test_follow_up_task_linked_to_record(admin_user, products, login):
    client = login(admin_user)
    inv = create_record("investors", products[0])
    data = form_data("tasks", products[0])
    resp = client.post(reverse("records:create", args=["tasks"]) + f"?related=investors:{inv.pk}", data)
    assert resp.status_code == 302
    from apps.tasks.models import Task

    task = Task.objects.get()
    assert task.related_record == inv
    assert task.related_module == "investors"


def test_seo_updates_box(admin_user, users, products, login):
    a, b = products
    kw = create_record("seo", a, keyword="procurement software")
    client = login(admin_user)
    resp = client.post(reverse("seo:add_update"), {"text": "Ranking moved 18 → 11", "product": a.pk,
                                                   "record": kw.pk, "next": "/records/seo/"})
    assert resp.status_code == 302
    page = client.get(reverse("records:list", args=["seo"]))
    assert [u.text for u in page.context["seo_updates"]] == ["Ranking moved 18 → 11"]
    box = next(c for c in page.context["kpis"] if c["label"] == "SEO / GEO updates")
    assert box["value"] == 1
    assert "Ranking moved" in client.get(kw.get_absolute_url()).content.decode()  # shown on the keyword too
    # a ShiftEaze member cannot post updates for ProcEaze, and does not see them
    other = login(users["member_b"])
    assert other.post(reverse("seo:add_update"), {"text": "x", "product": a.pk}).status_code == 403
    assert not other.get(reverse("records:list", args=["seo"])).context["seo_updates"]


def test_community_question_and_answer_view(admin_user, products, login):
    create_record("community", products[0], topic="How do I automate approvals?",
                  answer_summary="Use amount-based approval limits.", upvotes=12, comments_count=3, views=400)
    client = login(admin_user)
    html = client.get(reverse("records:list", args=["community"]) + "?view=cards").content.decode()
    assert "How do I automate approvals?" in html and "Use amount-based approval limits." in html
    kpis = {c["label"]: c["value"] for c in client.get(reverse("records:list", args=["community"])).context["kpis"]}
    assert kpis["Upvotes"] == 12 and kpis["Comments"] == 3 and kpis["Views"] == 400 and kpis["Total activity"] == 15


def test_dashboard_hides_products_overdue_listings_boxes(admin_user, products, login):
    keys = [c["key"] for c in login(admin_user).get(reverse("analytics:dashboard")).context["kpi_cards"]]
    assert "products" not in keys and "overdue" not in keys and "listings" not in keys
    assert "activities" in keys and "leads" in keys


def test_listing_platform_typed_as_text(admin_user, products, platform, login):
    from apps.listings.models import ListingPlatform, ListingRecord

    client = login(admin_user)
    a, b = products
    url = reverse("records:create", args=["listings"])
    page = client.get(url).content.decode()
    assert '<datalist id="id_platform_options"><option value="G2"></option>' in page

    # Existing platform matched by name, ignoring case and spaces: no duplicate created.
    data = form_data("listings", a, platform)
    data["platform"] = "  g2 "
    assert client.post(url, data).status_code == 302
    assert ListingRecord.objects.get().platform == platform
    assert ListingPlatform.objects.count() == 1

    # A new name is added to the catalog and used.
    data = form_data("listings", a)
    data["platform"] = "My New Directory"
    assert client.post(url, data).status_code == 302
    new = ListingPlatform.objects.get(name="My New Directory")
    assert new.is_active and ListingRecord.objects.filter(platform=new, product=a).exists()

    # An invalid submit (no product) does not leave a stray platform behind.
    data = form_data("listings", a)
    data.update(platform="Never Saved", product="")
    resp = client.post(url, data)
    assert resp.status_code == 200 and "product" in resp.context["form"].errors
    assert not ListingPlatform.objects.filter(name="Never Saved").exists()

    # Editing shows the platform's name, not its id.
    rec = ListingRecord.objects.get(platform=new)
    page = client.get(reverse("records:edit", args=["listings", rec.pk])).content.decode()
    assert 'value="My New Directory"' in page


def test_bulk_delete_on_turso_commits_record_by_record(admin_user, products, login, monkeypatch):
    """Turso closes long write transactions, so a bulk action there runs without one around the selection."""
    from types import SimpleNamespace

    from apps.core import views
    from apps.tasks.models import Task

    monkeypatch.setattr(views, "connection", SimpleNamespace(is_remote=True))
    monkeypatch.setattr(views, "transaction", SimpleNamespace(
        atomic=lambda *a, **k: pytest.fail("bulk action opened a transaction")))
    t1 = create_record("tasks", products[0], suffix="a")
    t2 = create_record("tasks", products[0], suffix="b")
    resp = login(admin_user).post(reverse("records:bulk", args=["tasks"]), {"ids": [t1.pk, t2.pk], "action": "delete"})
    assert resp.status_code == 302
    assert not Task.objects.filter(pk__in=[t1.pk, t2.pk]).exists()
