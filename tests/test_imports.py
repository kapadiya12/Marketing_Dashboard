"""Import everywhere: templates with sample data, CSV and Excel uploads, admin and history imports."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import load_workbook

from apps.core.importing import MARKER_TEXT, SAMPLE_MARKER
from apps.core.registry import registry
from apps.investors.models import InvestorCategory
from apps.listings.models import ListingPlatform

from .factories import ALL_RESOURCES, create_record

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _strip_markers(text):
    """What a user does with a sample template: keep the example values, remove the sample marker."""
    return text.replace(MARKER_TEXT + " | ", "").replace(MARKER_TEXT, "")


def _csv(text, name="import.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


@pytest.fixture
def catalog(db):
    ListingPlatform.objects.create(name="G2", website_url="https://www.g2.com")
    ListingPlatform.objects.create(name="Capterra", website_url="https://www.capterra.com")
    InvestorCategory.objects.create(name="Angel investors")


@pytest.mark.parametrize("key", ALL_RESOURCES)
def test_every_module_sample_template_imports_cleanly(key, admin_user, products, catalog, login):
    """The sample rows in each template are valid: with the marker removed they import as real records."""
    client = login(admin_user)
    url = reverse("records:import", args=[key])
    page = client.get(url)
    assert page.status_code == 200 and page.context["guide"]
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    assert SAMPLE_MARKER in sample
    resp = client.post(url, {"file": _csv(_strip_markers(sample))})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    assert registry.get(key).model.objects.count() == 2


@pytest.mark.parametrize("key", ["meetings", "listings", "tasks"])
def test_product_scoped_sample_import(key, admin_user, products, catalog, login):
    client = login(admin_user)
    url = reverse("products:record_import", args=[products[1].slug, key])
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    assert client.post(url, {"file": _csv(_strip_markers(sample))}).status_code == 302
    assert set(registry.get(key).model.objects.values_list("product__slug", flat=True)) == {"shifteaze"}


def test_sample_rows_are_skipped(admin_user, products, catalog, login):
    client = login(admin_user)
    url = reverse("records:import", args=["tasks"])
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    resp = client.post(url, {"file": _csv(sample)})
    assert resp.status_code == 200
    assert resp.context["result"]["skipped"] == 2 and resp.context["result"]["created"] == 0
    assert not registry.get("tasks").model.objects.exists()


def test_excel_template_has_samples_guide_and_dropdowns(admin_user, products, catalog, login):
    client = login(admin_user)
    resp = client.get(reverse("records:import", args=["meetings"]) + "?template=xlsx")
    assert resp["Content-Type"] == XLSX
    wb = load_workbook(io.BytesIO(resp.content))
    assert {"How to import", "Data", "Field guide", "Lists"} <= set(wb.sheetnames)
    data = wb["Data"]
    headers = [c.value for c in data[1]]
    assert headers[:3] == ["product", "title", "customer_company"]
    assert data.max_row == 3  # header + 2 sample rows
    assert data.data_validations.dataValidation  # dropdowns for choice columns
    guide = {r[0]: r for r in wb["Field guide"].iter_rows(min_row=2, values_only=True)}
    assert guide["title"][2] == "Yes"  # required
    assert "Online" in guide["meeting_type"][4]  # allowed values listed


def test_excel_upload_imports(admin_user, products, catalog, login):
    client = login(admin_user)
    url = reverse("records:import", args=["consultants"])
    wb = load_workbook(io.BytesIO(client.get(url + "?template=xlsx").content))
    ws = wb["Data"]
    headers = [c.value for c in ws[1]]
    notes_col = headers.index("notes") + 1
    for r in (2, 3):
        ws.cell(row=r, column=notes_col, value="Imported from Excel")
    buf = io.BytesIO()
    wb.save(buf)
    resp = client.post(url, {"file": SimpleUploadedFile("consultants.xlsx", buf.getvalue(), content_type=XLSX)})
    assert resp.status_code == 302
    assert registry.get("consultants").model.objects.filter(notes="Imported from Excel").count() == 2


def test_import_rejects_bad_files(admin_user, products, login):
    client = login(admin_user)
    url = reverse("records:import", args=["tasks"])
    resp = client.post(url, {"file": SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")})
    assert resp.status_code == 200 and resp.context["form"].errors
    resp = client.post(url, {"file": SimpleUploadedFile("fake.xlsx", b"not excel", content_type=XLSX)})
    assert resp.context["form"].errors


def test_choice_labels_and_names_are_understood(admin_user, products, catalog, login):
    client = login(admin_user)
    csv = ("product,title,customer_company,meeting_type,status,start_at,outcome,assigned_to\n"
           "ShiftEaze,Kickoff,Example Co,In person,Scheduled,2026-12-01 09:30,Positive — next steps agreed,admin\n")
    resp = client.post(reverse("records:import", args=["meetings"]), {"file": _csv(csv)})
    assert resp.status_code == 302
    m = registry.get("meetings").model.objects.get()
    assert (m.product.slug, m.meeting_type, m.outcome, m.assigned_to.username) == \
        ("shifteaze", "offline", "positive", "admin")


def test_import_permissions(users, products, catalog, login):
    client = login(users["viewer_a"])
    assert client.get(reverse("records:import", args=["tasks"])).status_code == 403
    client = login(users["member_b"])
    csv = "product,title,priority,status\nproceaze,Sneaky,high,todo\n"
    resp = client.post(reverse("records:import", args=["tasks"]), {"file": _csv(csv)})
    assert resp.context["result"]["errors"]
    assert not registry.get("tasks").model.objects.exists()
    assert client.get(reverse("products:record_import", args=["proceaze", "tasks"])).status_code == 404


@pytest.mark.parametrize("resource,child", [("seo", "measurements"), ("consultants", "interactions"),
                                            ("investors", "interactions")])
def test_history_entry_import(resource, child, admin_user, products, login):
    client = login(admin_user)
    rec = create_record(resource, products[0])
    url = reverse("records:child_import", args=[resource, rec.pk, child])
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    resp = client.post(url, {"file": _csv(_strip_markers(sample))})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    spec = next(c for c in registry.get(resource).children if c.key == child)
    assert spec.model.objects.filter(**{spec.fk_name: rec}).count() == 2


@pytest.mark.parametrize("key", ["listing-platforms", "investor-categories", "categories", "tags", "statuses",
                                 "custom-fields", "targets"])
def test_admin_settings_imports(key, admin_user, products, login):
    client = login(admin_user)
    url = reverse("admin_panel:config_import", args=[key])
    assert client.get(url).status_code == 200
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    resp = client.post(url, {"file": _csv(_strip_markers(sample))})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp


def test_admin_users_products_members_imports(admin_user, users, products, login):
    from django.contrib.auth import get_user_model

    from apps.products.models import Product

    client = login(admin_user)
    for url in [reverse("admin_panel:users_import"), reverse("admin_panel:products_import")]:
        sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
        resp = client.post(url, {"file": _csv(_strip_markers(sample))})
        assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    new_user = get_user_model().objects.get(username="asha.example")
    assert not new_user.has_usable_password()
    assert Product.objects.filter(slug="example-product").exists()

    product = Product.objects.get(slug="example-product")
    csv = "user,role,is_active\nasha.example,Viewer,yes\nrahul.example@example.com,Team Member,yes\n"
    resp = client.post(reverse("admin_panel:members_import", args=[product.pk]), {"file": _csv(csv)})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    assert product.memberships.count() == 2


def test_admin_imports_require_admin(users, login):
    client = login(users["member_a"])
    assert client.get(reverse("admin_panel:users_import")).status_code == 403
    assert client.get(reverse("admin_panel:config_import", args=["tags"])).status_code == 403


def test_import_hub(admin_user, users, products, login):
    client = login(admin_user)
    resp = client.get(reverse("import_hub"))
    assert resp.status_code == 200
    assert len(resp.context["rows"]) == len([r for r in registry.resources() if r.importable])
    assert resp.context["admin_imports"]
    assert client.get(reverse("import_hub") + "?product=proceaze").context["selected"] == products[0]
    for kind in ("xlsx", "csv_sample", "csv"):
        r = client.get(reverse("records:import_template", args=["leads"]) + f"?kind={kind}&product=proceaze")
        assert r.status_code == 200
    viewer = login(users["viewer_a"])
    resp = viewer.get(reverse("import_hub"))
    assert resp.status_code == 200 and not resp.context["rows"] and not resp.context["admin_imports"]


REAL_WORLD_MEETINGS = (
    "product,shared_products,title,customer_company,meeting_type,status,start_at,end_at,outcome,assigned_to,"
    "category,tags,notes\n"
    "proceaze,shifteaze; ShiftEaze,Discovery call,Aarav Mfg,Online,Confirmed,2026-10-20 11:00,2026-10-20 11:45,"
    "Requirements captured,admin,Discovery,procurement;RFQ,Real data\n"
    "proceaze,,Demo,BluePeak,In person,Scheduled,2026-10-21 15:00,,Pending,nobody-here,Discovery,RFQ,\n"
)


def test_real_world_file_imports_with_adjustments(admin_user, products, login):
    """Unknown tags/categories/statuses/outcomes no longer block an import; nothing is lost."""
    from apps.core.models import Category, StatusOption, Tag

    client = login(admin_user)
    resp = client.post(reverse("records:import", args=["meetings"]), {"file": _csv(REAL_WORLD_MEETINGS)})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    m = registry.get("meetings").model.objects.get(customer_company="Aarav Mfg")
    assert m.status == "confirmed" and StatusOption.objects.filter(resource="meetings", key="confirmed").exists()
    assert StatusOption.objects.filter(resource="meetings", key="scheduled").exists()  # defaults kept
    assert m.outcome == "pending" and "Outcome: Requirements captured" in m.meeting_notes
    # category / tags / shared products are no longer on the simplified form: those columns are skipped
    assert m.category is None and not m.tags.exists() and not m.shared_products.exists()
    assert not Category.objects.filter(name="Discovery").exists() and not Tag.objects.filter(name="RFQ").exists()
    other = registry.get("meetings").model.objects.get(customer_company="BluePeak")
    assert other.assigned_to is None and "Assigned to: nobody-here" in other.meeting_notes


def test_team_member_cannot_create_statuses_by_import(users, products, login):
    from apps.core.models import StatusOption

    client = login(users["member_a"])
    resp = client.post(reverse("records:import", args=["meetings"]), {"file": _csv(REAL_WORLD_MEETINGS)})
    assert resp.status_code == 302  # imported, but the unknown status fell back to the default
    assert not StatusOption.objects.filter(key="confirmed").exists()
    m = registry.get("meetings").model.objects.get(customer_company="Aarav Mfg")
    assert m.status == "scheduled" and "Status: Confirmed" in m.meeting_notes


def test_include_sample_rows_option(admin_user, products, catalog, login):
    client = login(admin_user)
    url = reverse("records:import", args=["tasks"])
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    resp = client.post(url, {"file": _csv(sample), "include_samples": "on"})
    assert resp.status_code == 302
    tasks = registry.get("tasks").model.objects.all()
    assert tasks.count() == 2 and not any(SAMPLE_MARKER in (t.notes or "") for t in tasks)


def test_listing_import_updates_existing_and_creates_platforms(admin_user, products, catalog, login):
    from apps.listings.models import ListingPlatform, ListingRecord

    a = products[0]
    g2 = ListingPlatform.objects.get(name="G2")
    existing = ListingRecord.objects.create(product=a, platform=g2, status="not_started")
    csv = ("product,platform,status,submission_date,next_verification_date,listing_url\n"
           "proceaze,G2,Approved,20/10/2026,15-11-2026,https://g2.com/p/x\n"
           "proceaze,Brand New Directory,Submitted,2026-10-21,,\n")
    resp = client_post = login(admin_user).post(reverse("records:import", args=["listings"]), {"file": _csv(csv)})
    assert client_post.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    existing.refresh_from_db()
    assert existing.status == "approved" and str(existing.submission_date) == "2026-10-20"
    assert existing.listing_url == "https://g2.com/p/x"  # next_verification_date is no longer on the form
    assert ListingPlatform.objects.filter(name="Brand New Directory").exists()
    assert ListingRecord.objects.filter(product=a).count() == 2


def test_numbers_and_dates_in_spreadsheet_formats(admin_user, products, login):
    csv = ("product,name,channel,objective,status,start_date,end_date,budget,actual_spend,impressions,reach,clicks,"
           "leads,conversions\n"
           "proceaze,Diwali push,Meta (Facebook / Instagram),Lead generation,Active,01/10/2026,31/10/2026,"
           "\"₹7,50,000\",\"1,20,000.50\",\"25,000\",0,300,12,1\n")
    resp = login(admin_user).post(reverse("records:import", args=["advertising"]), {"file": _csv(csv)})
    assert resp.status_code == 302, resp.context["result"]["errors"] if resp.context else resp
    c = registry.get("advertising").model.objects.get()
    assert (str(c.start_date), str(c.end_date), int(c.budget), c.impressions) == ("2026-10-01", "2026-10-31", 750000, 25000)


def test_settings_reimport_updates_by_name(admin_user, login):
    from apps.listings.models import ListingPlatform

    ListingPlatform.objects.create(name="G2", website_url="https://old.example.com")
    csv = "name,website_url,kind,description,is_active,display_order\nG2,https://www.g2.com,Review site,,yes,1\n"
    resp = login(admin_user).post(reverse("admin_panel:config_import", args=["listing-platforms"]), {"file": _csv(csv)})
    assert resp.status_code == 302
    assert ListingPlatform.objects.get(name="G2").website_url == "https://www.g2.com"


@pytest.mark.parametrize("key", ALL_RESOURCES)
def test_minimal_column_files_import(key, admin_user, products, catalog, login):
    """A file with only the essential columns imports: everything else uses the normal defaults."""
    import csv as _csv_mod
    import io as _io

    client = login(admin_user)
    url = reverse("records:import", args=[key])
    guide = client.get(url).context["guide"]
    keep = [g["name"] for g in guide if g["required"] and g["name"] not in ("status",)]
    sample = client.get(url + "?template=csv_sample").content.decode("utf-8-sig")
    rows = list(_csv_mod.DictReader(_io.StringIO(_strip_markers(sample))))
    out = _io.StringIO()
    w = _csv_mod.DictWriter(out, fieldnames=keep, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    resp = client.post(url, {"file": _csv(out.getvalue())})
    assert resp.status_code == 302, (keep, resp.context["result"]["errors"] if resp.context else resp)


@pytest.fixture
def background_imports(settings, tmp_path, monkeypatch):
    """Background imports, with the import process run inline (in the test database)."""
    from apps.core import import_jobs

    settings.IMPORT_IN_BACKGROUND = True
    settings.IMPORT_JOB_DIR = str(tmp_path)
    monkeypatch.setattr(import_jobs, "_spawn", import_jobs.run)
    return import_jobs


def _upload(text):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("calls.csv", text.encode("utf-8"), content_type="text/csv")


def test_background_import_saves_and_reports(background_imports, admin_user, products, login):
    from apps.cold_calls.models import ColdCall

    client = login(admin_user)
    url = reverse("products:record_import", args=["proceaze", "calls"])
    resp = client.post(url, {"file": _upload("contact_name,company\nAsha,Example Co\nRavi,\n")})
    assert resp.status_code == 302 and "?job=" in resp["Location"]
    job_id = resp["Location"].split("?job=")[1]
    assert background_imports.read(job_id)["status"] == "done"
    polled = client.get(resp["Location"], HTTP_HX_REQUEST="true")
    assert polled["HX-Redirect"] == resp["Location"]  # finished: the polling page reloads
    done = client.get(resp["Location"], follow=True)
    assert done.redirect_chain[0][0] == reverse("products:records", args=["proceaze", "calls"])
    assert "Imported 2 record(s)" in done.content.decode()
    assert sorted(ColdCall.objects.values_list("contact_name", flat=True)) == ["Asha", "Ravi"]


def test_background_import_shows_row_problems(background_imports, admin_user, users, products, login):
    from apps.cold_calls.models import ColdCall

    client = login(admin_user)
    url = reverse("products:record_import", args=["proceaze", "calls"])
    resp = client.post(url, {"file": _upload("contact_name,contact_date\nAsha,2026-10-01\n,2026-10-02\n")})
    page = client.get(resp["Location"]).content.decode()
    assert "need attention" in page and "Problems found" in page
    assert ColdCall.objects.count() == 0
    assert login(users["member_a"]).get(resp["Location"]).status_code == 404  # someone else's job


def test_background_import_progress_while_running(background_imports, admin_user, products, login, monkeypatch):
    monkeypatch.setattr(background_imports, "_spawn", lambda job_id: None)  # process not started yet
    client = login(admin_user)
    url = reverse("products:record_import", args=["proceaze", "calls"])
    resp = client.post(url, {"file": _upload("contact_name\nAsha\n")})
    page = client.get(resp["Location"]).content.decode()
    assert "Importing calls.csv" in page and 'hx-trigger="load delay:2s"' in page
    partial = client.get(resp["Location"], HTTP_HX_REQUEST="true").content.decode()
    assert partial.strip().startswith("{#") or 'id="import-job"' in partial
