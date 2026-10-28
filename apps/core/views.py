"""
Generic, permission-checked views for every registered resource:
list (table / cards / board / calendar), create, detail, edit, archive, restore,
delete, inline status change, bulk actions, CSV/XLSX export, CSV import,
attachments and inline child records.
"""
import calendar as pycal
import datetime
from contextlib import nullcontext

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import (
    accessible_products,
    has_level,
    is_org_admin,
    module_level,
    product_ids_for,
    scoped_queryset,
)
from apps.audit.models import AuditLog
from apps.audit.services import diff_instances, log_action, snapshot

from . import csvio
from .filtering import apply_filters, apply_sort, filter_field_choices
from .forms import AttachmentForm, assignable_users, child_form_class, make_record_form
from .models import Attachment, CustomFieldDefinition, ModuleSetting, Tag
from .notifications import notify_assignment
from .periods import PERIODS, resolve_period
from .registry import registry
from .statuses import get_status, get_statuses


# --------------------------------------------------------------------------- helpers

def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def get_resource(key):
    resource = registry.get(key)
    if resource is None:
        raise Http404("Unknown module")
    return resource


def get_scope_product(request, resource, slug):
    """Product from the URL slug, enforcing membership and module enablement (404 otherwise)."""
    if not slug:
        return None
    product = get_object_or_404(accessible_products(request.user), slug=slug)
    if module_level(request.user, product, resource.module) == "none":
        raise Http404("Module not available for this product")
    return product


def get_record(request, resource, pk, level="read"):
    obj = scoped_queryset(request.user, resource, "read").filter(pk=pk).first()
    if obj is None:
        raise Http404("Record not found")
    if level != "read" and not has_level(request.user, obj.product_id, resource.module, level):
        raise PermissionDenied("You do not have permission to change this record.")
    return obj


def require_any_access(request, resource, level="read"):
    if not product_ids_for(request.user, resource.module, level) and not is_org_admin(request.user):
        raise PermissionDenied("You do not have access to this module.")


def purge_record(obj):
    """Delete a record together with its attachment files and custom field values."""
    for att in obj.attachments.all():
        att.file.delete(save=False)
        att.delete()
    obj.custom_values.all().delete()
    obj.delete()


def list_columns(resource):
    setting = ModuleSetting.objects.filter(resource=resource.key).first()
    allowed = set(resource.allowed_columns)
    cols = [c for c in (setting.list_columns if setting and setting.list_columns else resource.list_columns)
            if c in allowed]
    cols = cols or resource.list_columns
    cfs = CustomFieldDefinition.objects.filter(resource=resource.key, is_active=True, show_in_list=True)
    cols += [f"cf:{d.key}" for d in cfs]
    return cols


def page_size(resource):
    setting = ModuleSetting.objects.filter(resource=resource.key).first()
    return min(max(setting.page_size if setting else 25, 5), 200)


def records_url(resource, product=None):
    if product is not None:
        return reverse("products:records", kwargs={"slug": product.slug, "resource": resource.key})
    return reverse("records:list", kwargs={"resource": resource.key})


def _attach_custom_values(resource, objects, columns):
    keys = [c[3:] for c in columns if c.startswith("cf:")]
    if not keys or not objects:
        return
    from .models import CustomFieldValue

    ct = ContentType.objects.get_for_model(resource.model)
    values = CustomFieldValue.objects.filter(
        content_type=ct, object_id__in=[o.pk for o in objects], definition__key__in=keys,
        definition__resource=resource.key,
    ).select_related("definition")
    by_obj = {}
    for v in values:
        by_obj.setdefault(v.object_id, {})[v.definition.key] = v.value
    for o in objects:
        o._cf_values = by_obj.get(o.pk, {})


def base_context(request, resource, product):
    module = registry.module(resource.module)
    products = accessible_products(request.user)
    return {
        "resource": resource,
        "module": module,
        "module_resources": [registry.get(k) for k in module.resources] if module else [resource],
        "scope_product": product,
        "can_write": bool(product_ids_for(request.user, resource.module, "write")) if product is None
        else has_level(request.user, product, resource.module, "write"),
        "can_manage": has_level(request.user, product, resource.module, "manage") if product is not None
        else bool(product_ids_for(request.user, resource.module, "manage")),
        "products_for_filter": products.filter(pk__in=product_ids_for(request.user, resource.module, "read")),
        "records_url": records_url(resource, product),
    }


# --------------------------------------------------------------------------- list

@login_required
def record_list(request, resource, slug=None):
    resource = get_resource(resource)
    product = get_scope_product(request, resource, slug)
    require_any_access(request, resource)
    base = scoped_queryset(request.user, resource, "read", product=product)
    products_by_slug = {p.slug: p for p in accessible_products(request.user)}
    qs = apply_filters(base, resource, request.GET, products_by_slug)

    view_mode = request.GET.get("view", "table")
    if view_mode == "board" and not resource.board:
        view_mode = "table"
    if view_mode == "calendar" and not resource.calendar_field:
        view_mode = "table"
    if view_mode == "cards" and not resource.card_view:
        view_mode = "table"

    ctx = base_context(request, resource, product)
    kpi_ctx = {"product_count": 1 if product else (
        len({request.GET.get("product")} - {None, ""}) or len(ctx["products_for_filter"]))}
    if resource.key == "seo":
        from apps.seo_optimization.models import SEOUpdate

        update_products = [product.pk] if product else product_ids_for(request.user, "seo", "read")
        updates = SEOUpdate.objects.filter(product_id__in=update_products).select_related(
            "product", "record", "created_by")
        if request.GET.get("product") and not product:
            updates = updates.filter(product__slug=request.GET["product"])
        kpi_ctx["seo_updates"] = updates.count()
        ctx["seo_updates"] = updates[:12]
        ctx["seo_update_products"] = ctx["products_for_filter"].filter(
            pk__in=product_ids_for(request.user, "seo", "write"))
        ctx["seo_update_keywords"] = scoped_queryset(request.user, resource, "write", product=product).filter(
            is_archived=False).order_by("keyword")[:300]
    ctx["kpis"] = resource.kpis(qs, kpi_ctx) if resource.kpis else []
    _resolve_kpi_links(request, resource, ctx["kpis"])
    preset = resource.presets.get(request.GET.get("preset") or "")
    ctx["active_preset"] = preset[0] if preset else None
    ctx["charts"] = resource.charts(qs, kpi_ctx) if resource.charts and view_mode == "table" else []

    columns = list_columns(resource)
    ordered = apply_sort(qs, resource, request.GET.get("sort"))
    ordered = ordered.select_related("product", "assigned_to")

    if view_mode == "board":
        statuses = get_statuses(resource.key)
        items = list(ordered[:500])
        ctx["board"] = [
            {"status": s, "items": [o for o in items if o.status == s.key]} for s in statuses
        ]
    elif view_mode == "calendar":
        ctx.update(_calendar_context(request, resource, ordered))
    else:
        paginator = Paginator(ordered, page_size(resource))
        page = paginator.get_page(request.GET.get("page"))
        _attach_custom_values(resource, page.object_list, columns)
        ctx["page"] = page

    query = request.GET.copy()
    query.pop("page", None)
    sort_query = query.copy()
    sort_query.pop("sort", None)
    ctx.update({
        "columns": columns,
        "column_defs": [{"name": c, "label": resource.column_label(c),
                         "sortable": c in resource.sort_fields or c in ("status", "created_at", "updated_at")}
                        for c in columns],
        "view_mode": view_mode,
        "statuses": get_statuses(resource.key),
        "users": assignable_users(request.user),
        "tags": Tag.objects.all(),
        "extra_filters": [
            {"name": f, "label": resource.column_label(f),
             "choices": filter_field_choices(resource, f, request.user, base), "value": request.GET.get(f, "")}
            for f in resource.filter_fields
        ],
        "periods": PERIODS,
        "period": resolve_period(request.GET),
        "querystring": query.urlencode(),
        "sort_querystring": sort_query.urlencode(),
        "current_sort": request.GET.get("sort", ""),
        "total_count": qs.count(),
        "filters_active": any(k in request.GET for k in
                              ["q", "status", "assigned", "product", "period", "overdue", "state", "tag", "archived"]
                              + resource.filter_fields),
    })
    if is_htmx(request) and request.headers.get("HX-Target") == "record-results":
        return render(request, "records/_results.html", ctx)
    return render(request, "records/list.html", ctx)


DRILL_KEYS = ("status", "state", "overdue", "preset", "sort", "page", "view")


def _resolve_kpi_links(request, resource, cards):
    """
    Give each KPI card a URL showing the records behind it: the page's current filters
    (search, product, assignee, dates…) plus the card's own filter parameters.
    """
    for card in cards:
        if card.get("url", "") and card["url"].startswith("#"):
            card["url"] = request.get_full_path() + card["url"]  # anchor on this page
            continue
        if card.get("url") or card.get("link") is None:
            continue
        query = request.GET.copy()
        for key in DRILL_KEYS + tuple(resource.filter_fields):
            if key in card["link"] or key in DRILL_KEYS:
                query.pop(key, None)
        for key, value in card["link"].items():
            if isinstance(value, (list, tuple)):
                query.setlist(key, list(value))
            else:
                query[key] = value
        card["url"] = f"{request.path}?{query.urlencode()}" if query else request.path


def _calendar_context(request, resource, qs):
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in request.GET.get("month", f"{today.year}-{today.month}").split("-"))
        first = datetime.date(year, month, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
    field = resource.calendar_field
    model_field = resource.model._meta.get_field(field)
    is_dt = model_field.get_internal_type() == "DateTimeField"
    last_day = pycal.monthrange(first.year, first.month)[1]
    last = first.replace(day=last_day)
    lookup = f"{field}__date" if is_dt else field
    items = qs.filter(**{f"{lookup}__gte": first, f"{lookup}__lte": last})
    by_day = {}
    for obj in items[:1000]:
        value = getattr(obj, field)
        day = timezone.localtime(value).date() if is_dt else value
        by_day.setdefault(day, []).append(obj)
    weeks = []
    for week in pycal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month):
        weeks.append([{"date": d, "in_month": d.month == first.month, "is_today": d == today,
                       "items": by_day.get(d, [])} for d in week])
    prev_month = (first - datetime.timedelta(days=1)).replace(day=1)
    next_month = last + datetime.timedelta(days=1)
    return {"weeks": weeks, "cal_month": first, "prev_month": f"{prev_month.year}-{prev_month.month}",
            "next_month": f"{next_month.year}-{next_month.month}", "calendar_is_datetime": is_dt}


# --------------------------------------------------------------------------- create / edit

def _related_from_request(request):
    """Parse ?related=<resource>:<pk> for tasks created from a record page (permission checked)."""
    value = request.GET.get("related") or request.POST.get("related")
    if not value or ":" not in value:
        return None
    key, _, pk = value.partition(":")
    res = registry.get(key)
    if res is None or not pk.isdigit():
        return None
    return scoped_queryset(request.user, res, "read").filter(pk=int(pk)).first()


@login_required
def record_create(request, resource, slug=None):
    resource = get_resource(resource)
    product = get_scope_product(request, resource, slug)
    if product is None and request.GET.get("product"):
        product = accessible_products(request.user).filter(slug=request.GET["product"]).first()
    require_any_access(request, resource, "write")
    if product is not None and not has_level(request.user, product, resource.module, "write"):
        raise PermissionDenied("You do not have write access to this module for this product.")
    related = _related_from_request(request) if resource.key == "tasks" else None
    # Prefill from query parameters (e.g. ?platform=12). The form still validates and scopes every choice.
    initial = {k: v for k, v in request.GET.items() if k in resource.form_fields and k not in ("product", "status")}
    if related is not None:
        initial.update({"product": related.product_id, "related_module": related.resource.module,
                        "title": f"Follow up: {related}"[:200]})
        product = product or related.product

    if request.method == "POST":
        form = make_record_form(resource, request.user, data=request.POST, files=request.FILES, product=product)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.updated_by = request.user
                if related is not None:
                    obj.content_type = ContentType.objects.get_for_model(related.__class__)
                    obj.object_id = related.pk
                obj.save()
                form.save_m2m()
                form.save_custom_fields(obj)
                log_action(AuditLog.Action.CREATE, obj, request.user, message=f"Created {resource.label.lower()}")
            notify_assignment(obj, obj.assigned_to, request.user)
            messages.success(request, f"{resource.label} “{obj}” created.")
            if "save_add" in request.POST:
                return redirect(request.path + (f"?product={obj.product.slug}" if not slug else ""))
            if related is not None:
                return redirect(related.get_absolute_url())
            return redirect(obj.get_absolute_url())
        messages.error(request, "Please correct the errors below.")
    else:
        form = make_record_form(resource, request.user, product=product, initial=initial)
    ctx = base_context(request, resource, product)
    ctx.update({"form": form, "is_create": True, "related": related})
    return render(request, "records/form.html", ctx)


@login_required
def record_edit(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    before = snapshot(obj)
    before_assignee = obj.assigned_to
    if request.method == "POST":
        form = make_record_form(resource, request.user, data=request.POST, files=request.FILES, instance=obj,
                                product=obj.product)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.updated_by = request.user
                obj.save()
                form.save_m2m()
                form.save_custom_fields(obj)
                changes = diff_instances(before, snapshot(obj))
                log_action(AuditLog.Action.UPDATE, obj, request.user, changes=changes,
                           message=f"Updated {len(changes)} field(s)")
            if obj.assigned_to != before_assignee:
                notify_assignment(obj, obj.assigned_to, request.user)
            messages.success(request, f"{resource.label} “{obj}” saved.")
            return redirect(obj.get_absolute_url())
        messages.error(request, "Please correct the errors below.")
    else:
        form = make_record_form(resource, request.user, instance=obj, product=obj.product)
    ctx = base_context(request, resource, obj.product)
    ctx.update({"form": form, "object": obj, "is_create": False})
    return render(request, "records/form.html", ctx)


# --------------------------------------------------------------------------- detail

@login_required
def record_detail(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "read")
    ct = ContentType.objects.get_for_model(obj.__class__)
    from apps.tasks.models import Task

    fields = []
    for name in resource.form_fields:
        if name in ("notes",):
            continue
        fields.append({"name": name, "label": resource.column_label(name)})
    custom = []
    values = {cv.definition_id: cv.value for cv in obj.custom_values.all()}
    for d in CustomFieldDefinition.objects.filter(resource=resource.key, is_active=True):
        if d.product_id and d.product_id != obj.product_id:
            continue
        v = values.get(d.id)
        custom.append({"label": d.label, "value": "; ".join(v) if isinstance(v, list) else v, "type": d.field_type})
    children = []
    can_write = has_level(request.user, obj.product_id, resource.module, "write")
    for child in resource.children:
        items = child.model.objects.filter(**{child.fk_name: obj})
        headers = [str(child.model._meta.get_field(f).verbose_name).capitalize() for f in child.list_fields]
        children.append({"spec": child, "items": items, "headers": headers,
                         "form": child_form_class(child)() if can_write else None})
    for c in children:
        if c["form"]:
            from .forms import bootstrapify

            bootstrapify(c["form"])
    tasks = Task.objects.filter(content_type=ct, object_id=obj.pk, is_archived=False)
    history = AuditLog.objects.filter(content_type=ct, object_id=str(obj.pk)).select_related("user")[:50]
    ctx = base_context(request, resource, obj.product)
    ctx.update({
        "object": obj,
        "fields": fields,
        "custom": custom,
        "children": children,
        "attachments": obj.attachments.all(),
        "attachment_form": AttachmentForm() if can_write else None,
        "tasks": tasks,
        "history": history,
        "can_write": can_write,
        "can_manage": has_level(request.user, obj.product_id, resource.module, "manage"),
        "statuses": get_statuses(resource.key),
        "status_info": get_status(resource.key, obj.status),
    })
    return render(request, "records/detail.html", ctx)


@login_required
def record_detail_export(request, resource, pk):
    """Export one record with its custom fields, history entries, tasks, attachments and audit trail."""
    from apps.tasks.models import Task

    from .exporting import export_tables, plain, requested_format

    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "read")
    fmt = requested_format(request) or "pdf"
    rows = [[resource.column_label(n), csvio.cell_value(obj, n, resource)] for n in resource.form_fields]
    values = {cv.definition_id: cv.value for cv in obj.custom_values.all()}
    for d in CustomFieldDefinition.objects.filter(resource=resource.key, is_active=True):
        if d.id in values:
            v = values[d.id]
            rows.append([d.label, "; ".join(v) if isinstance(v, list) else v])
    rows += [["Created", plain(obj.created_at)], ["Created by", plain(obj.created_by)],
             ["Last updated", plain(obj.updated_at)], ["Archived", "Yes" if obj.is_archived else "No"]]
    tables = [{"title": "Details", "headers": ["Field", "Value"], "rows": rows}]
    for child in resource.children:
        items = child.model.objects.filter(**{child.fk_name: obj})
        tables.append({
            "title": child.label,
            "headers": [str(child.model._meta.get_field(f).verbose_name).capitalize() for f in child.list_fields],
            "rows": [[csvio.cell_value(i, f) for f in child.list_fields] for i in items],
        })
    ct = ContentType.objects.get_for_model(obj.__class__)
    tasks = Task.objects.filter(content_type=ct, object_id=obj.pk)
    tables.append({"title": "Follow-up tasks", "headers": ["Task", "Status", "Priority", "Due", "Assigned to"],
                   "rows": [[t.title, get_status("tasks", t.status).label, t.get_priority_display(),
                             plain(t.due_date), plain(t.assigned_to)] for t in tasks]})
    tables.append({"title": "Attachments", "headers": ["File", "Size (bytes)", "Uploaded by", "Uploaded"],
                   "rows": [[a.original_name, a.size, plain(a.uploaded_by), plain(a.created_at)]
                            for a in obj.attachments.all()]})
    history = AuditLog.objects.filter(content_type=ct, object_id=str(obj.pk)).select_related("user")[:500]
    tables.append({"title": "Activity history", "headers": ["When", "User", "Action", "Details"],
                   "rows": [[plain(h.created_at), plain(h.user), h.get_action_display(),
                             h.message or ", ".join(h.changes.keys())] for h in history]})
    log_action(AuditLog.Action.EXPORT, obj, request.user, message=f"Exported record ({fmt})")
    title = f"{resource.label}: {obj}"
    return export_tables(tables, fmt, f"{resource.key}-{obj.pk}-{timezone.localdate():%Y%m%d}", title,
                         f"{obj.product.name} · exported {timezone.localtime():%Y-%m-%d %H:%M}")


# --------------------------------------------------------------------------- state changes

@login_required
@require_POST
def record_archive(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    obj.archive(request.user)
    log_action(AuditLog.Action.ARCHIVE, obj, request.user)
    messages.success(request, f"“{obj}” archived. It no longer counts toward active dashboards.")
    return redirect(request.POST.get("next") or obj.get_absolute_url())


@login_required
@require_POST
def record_restore(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    obj.restore(request.user)
    log_action(AuditLog.Action.RESTORE, obj, request.user)
    messages.success(request, f"“{obj}” restored.")
    return redirect(request.POST.get("next") or obj.get_absolute_url())


@login_required
def record_delete(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "manage")
    if request.method == "POST":
        product = obj.product
        label = str(obj)
        log_action(AuditLog.Action.DELETE, obj, request.user, message=f"Deleted “{label}”")
        try:
            with transaction.atomic():
                purge_record(obj)
        except ProtectedError:
            messages.error(request, "This record is referenced by other records and cannot be deleted. Archive it.")
            return redirect(obj.get_absolute_url())
        messages.success(request, f"“{label}” permanently deleted.")
        return redirect(records_url(resource, product))
    ctx = base_context(request, resource, obj.product)
    ctx["object"] = obj
    return render(request, "records/confirm_delete.html", ctx)


@login_required
@require_POST
def record_status(request, resource, pk):
    """Inline status change (HTMX)."""
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    new_status = request.POST.get("status", "")
    if new_status not in {s.key for s in get_statuses(resource.key)}:
        return HttpResponse("Invalid status", status=400)
    old = obj.status
    if old != new_status:
        obj.status = new_status
        obj.updated_by = request.user
        obj.save()
        log_action(AuditLog.Action.STATUS, obj, request.user,
                   changes={"status": {"from": old, "to": new_status}})
    if is_htmx(request):
        resp = render(request, "components/status_badge.html",
                      {"status": get_status(resource.key, obj.status)})
        resp["HX-Trigger"] = "dashboard-refresh"
        return resp
    messages.success(request, "Status updated.")
    return redirect(request.POST.get("next") or obj.get_absolute_url())


@login_required
@require_POST
def bulk_action(request, resource):
    resource = get_resource(resource)
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action")
    next_url = request.POST.get("next") or records_url(resource)
    if not ids:
        messages.warning(request, "Select at least one record.")
        return redirect(next_url)
    if action in ("export_csv", "export_xlsx"):
        qs = scoped_queryset(request.user, resource, "read").filter(pk__in=ids).select_related("product", "assigned_to")
        log_action(AuditLog.Action.EXPORT, None, request.user, resource=resource.key,
                   message=f"Exported {qs.count()} selected {resource.label_plural}")
        name = f"{resource.key}-selected-{timezone.localdate():%Y%m%d}"
        if action == "export_xlsx":
            return csvio.xlsx_response([(resource.label_plural, csvio.rows_for_export(resource, qs))], f"{name}.xlsx")
        return csvio.csv_response(resource, qs, f"{name}.csv")
    level = "manage" if action == "delete" else "write"
    qs = scoped_queryset(request.user, resource, level).filter(pk__in=ids)
    count = qs.count()
    if count != len(set(ids)):
        messages.warning(request, f"{len(set(ids)) - count} selected record(s) skipped: insufficient permission.")
    # Turso closes a write transaction after a few seconds and every statement in it is a network round trip,
    # so there each record commits on its own instead of the whole selection in one transaction.
    with nullcontext() if getattr(connection, "is_remote", False) else transaction.atomic():
        if action == "archive":
            for obj in qs:
                obj.archive(request.user)
                log_action(AuditLog.Action.ARCHIVE, obj, request.user, message="Bulk archive")
        elif action == "restore":
            for obj in qs:
                obj.restore(request.user)
                log_action(AuditLog.Action.RESTORE, obj, request.user, message="Bulk restore")
        elif action == "delete":
            for obj in qs:
                log_action(AuditLog.Action.DELETE, obj, request.user, message="Bulk delete")
                purge_record(obj)
        elif action == "status":
            new_status = request.POST.get("status")
            if new_status not in {s.key for s in get_statuses(resource.key)}:
                messages.error(request, "Choose a valid status.")
                return redirect(next_url)
            for obj in qs:
                old = obj.status
                obj.status = new_status
                obj.updated_by = request.user
                obj.save()
                log_action(AuditLog.Action.STATUS, obj, request.user, changes={"status": {"from": old, "to": new_status}})
        elif action == "assign":
            uid = request.POST.get("assigned_to")
            assignee = assignable_users(request.user).filter(pk=uid).first() if uid else None
            if uid and assignee is None:
                messages.error(request, "Choose a valid team member.")
                return redirect(next_url)
            for obj in qs:
                obj.assigned_to = assignee
                obj.updated_by = request.user
                obj.save()
                log_action(AuditLog.Action.UPDATE, obj, request.user,
                           changes={"assigned_to": {"to": str(assignee) if assignee else None}})
                notify_assignment(obj, assignee, request.user)
        else:
            messages.error(request, "Unknown bulk action.")
            return redirect(next_url)
    messages.success(request, f"{count} record(s) updated.")
    return redirect(next_url)


# --------------------------------------------------------------------------- export / import

@login_required
def record_export(request, resource, slug=None):
    resource = get_resource(resource)
    product = get_scope_product(request, resource, slug)
    require_any_access(request, resource)
    base = scoped_queryset(request.user, resource, "read", product=product)
    products_by_slug = {p.slug: p for p in accessible_products(request.user)}
    qs = apply_filters(base, resource, request.GET, products_by_slug)
    qs = apply_sort(qs, resource, request.GET.get("sort")).select_related("product", "assigned_to")
    log_action(AuditLog.Action.EXPORT, None, request.user, resource=resource.key, product=product,
               message=f"Exported {qs.count()} {resource.label_plural}")
    stamp = timezone.localdate().strftime("%Y%m%d")
    name = f"{resource.key}-{product.slug + '-' if product else ''}{stamp}"
    if request.GET.get("format") == "xlsx":
        return csvio.xlsx_response([(resource.label_plural, csvio.rows_for_export(resource, qs))], f"{name}.xlsx")
    if request.GET.get("format") == "pdf":
        from .exporting import export_tables

        cols = [c for c in list_columns(resource) if not c.startswith("cf:")]
        rows = [[csvio.cell_value(o, c, resource) for c in cols] for o in qs[:5000]]
        scope = product.name if product else "All products"
        return export_tables([{"title": f"{resource.label_plural} ({len(rows)})",
                               "headers": [resource.column_label(c) for c in cols], "rows": rows}],
                             "pdf", name, f"{resource.label_plural} — {scope}",
                             f"Generated {timezone.localtime():%Y-%m-%d %H:%M}")
    return csvio.csv_response(resource, qs, f"{name}.csv")


def resource_import_spec(request, resource, product=None):
    """ImportSpec for a module record type (validated with the same form as manual entry)."""
    from .importing import ImportSpec
    from .statuses import default_status

    user = request.user

    def form_factory(data=None, instance=None):
        return make_record_form(resource, user, data=data, product=product, instance=instance)

    def save(form):
        obj = form.save(commit=False)
        obj.created_by = user
        obj.updated_by = user
        obj.save()
        form.save_m2m()
        form.save_custom_fields(obj)
        return obj

    defaults = {"status": default_status(resource.key)}
    if product is not None:
        defaults["product"] = product.slug

    from django.utils.text import slugify

    from .models import Category, StatusOption, Tag

    def create_tag(text):
        return Tag.objects.get_or_create(name__iexact=text.strip()[:50], defaults={"name": text.strip()[:50]})[0]

    def create_category(text):
        name = text.strip()[:80]
        existing = Category.objects.filter(name__iexact=name).filter(
            Q(resource="") | Q(resource=resource.key)).first()
        return existing or Category.objects.create(name=name, resource=resource.key)

    can_add_statuses = is_org_admin(user) or bool(product_ids_for(user, resource.module, "manage"))

    def create_status(text):
        """Add a new open status for this module (only for people who manage it)."""
        if not can_add_statuses:
            return None
        key = slugify(text).replace("-", "_")[:40] or None
        if not key:
            return None
        StatusOption.objects.get_or_create(
            resource=resource.key, key=key,
            defaults={"label": text.strip()[:60], "state": "open", "color": "info", "order": 50})
        if not StatusOption.objects.filter(resource=resource.key).exclude(key=key).exists():
            # first custom status: materialise the defaults too so they stay available
            for i, (k, label, state, color) in enumerate(resource.default_statuses):
                StatusOption.objects.get_or_create(resource=resource.key, key=k,
                                                   defaults={"label": label, "state": state, "color": color,
                                                             "order": i})
        return key

    creators = {"tags": create_tag, "category": create_category, "status": create_status}
    match_existing = None
    writable = scoped_queryset(user, resource, "write")

    if resource.key == "listings":
        from apps.listings.models import ListingPlatform

        def create_platform(text):
            name = text.strip()[:120]
            return ListingPlatform.objects.filter(name__iexact=name).first() or \
                ListingPlatform.objects.create(name=name, kind=ListingPlatform.Kind.OTHER, display_order=999)

        creators["platform"] = create_platform

        def match_existing(data):  # one listing per platform and product: update it
            if str(data.get("platform", "")).isdigit() and str(data.get("product", "")).isdigit():
                return writable.filter(platform_id=int(data["platform"]), product_id=int(data["product"])).first()
            return None
    elif resource.key == "leads":
        def match_existing(data):  # one lead per email and product: update it
            email = str(data.get("email", "")).strip().lower()
            if email and str(data.get("product", "")).isdigit():
                return writable.filter(product_id=int(data["product"]), email__iexact=email).first()
            return None
    return ImportSpec(
        key=resource.key,
        title=resource.label_plural,
        columns=csvio.import_template_columns(resource),
        form_factory=form_factory,
        save=save,
        back_url=records_url(resource, product),
        filename=f"{resource.key}{'-' + product.slug if product else ''}",
        defaults=defaults,
        ignored_columns={"id", "created_at", "updated_at"} | {
            f.name for f in resource.model._meta.get_fields()
            if (getattr(f, "concrete", False) or f.many_to_many) and not f.auto_created
        } - set(csvio.import_template_columns(resource)),
        description=resource.description,
        sample_context={"product": product, "user": user},
        creators=creators,
        note_field=next((f for f in ("notes", "meeting_notes") if f in resource.form_fields), None),
        match_existing=match_existing,
    )


@login_required
def import_template(request, resource):
    """Download a template: ?kind=csv (headers), csv_sample (with sample rows) or xlsx (default, with guide)."""
    from .importing import template_response

    resource = get_resource(resource)
    require_any_access(request, resource, "write")
    kind = request.GET.get("kind", "csv_sample")
    product = accessible_products(request.user).filter(slug=request.GET.get("product", "")).first()
    return template_response(resource_import_spec(request, resource, product),
                             kind if kind in ("csv", "csv_sample", "xlsx") else "csv_sample")


@login_required
def record_import(request, resource, slug=None):
    from .importing import import_page

    resource = get_resource(resource)
    product = get_scope_product(request, resource, slug)
    require_any_access(request, resource, "write")
    if product is not None and not has_level(request.user, product, resource.module, "write"):
        raise PermissionDenied
    if not resource.importable:
        raise Http404
    spec = resource_import_spec(request, resource, product)

    def audit(count):
        log_action(AuditLog.Action.IMPORT, None, request.user, resource=resource.key, product=product,
                   message=f"Imported {count} {resource.label_plural}")

    ctx = base_context(request, resource, product)
    ctx["crumbs"] = [(product.name, product.get_absolute_url())] if product else []
    ctx["crumbs"].append((resource.label_plural, spec.back_url))
    return import_page(request, spec, audit=audit, extra_context=ctx)


@login_required
def child_import(request, resource, pk, child):
    """Import history entries (measurements, interactions) for one record."""
    from .importing import ImportSpec, import_page

    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    spec_def = next((c for c in resource.children if c.key == child), None)
    if spec_def is None:
        raise Http404
    form_cls = child_form_class(spec_def)

    def save(form):
        item = form.save(commit=False)
        setattr(item, spec_def.fk_name, obj)
        if hasattr(item, "created_by_id"):
            item.created_by = request.user
        if hasattr(item, "product_id") and not item.product_id:
            item.product_id = obj.product_id
        item.save()
        return item

    spec = ImportSpec(
        key=f"{resource.key}:{child}", title=f"{spec_def.label} — {obj}", columns=list(spec_def.fields),
        form_factory=lambda data=None: form_cls(data=data), save=save,
        back_url=obj.get_absolute_url() + f"#child-{child}", filename=f"{resource.key}-{obj.pk}-{child}",
    )

    def audit(count):
        log_action(AuditLog.Action.IMPORT, obj, request.user, message=f"Imported {count} {spec_def.label.lower()}")

    ctx = base_context(request, resource, obj.product)
    ctx["crumbs"] = [(obj.product.name, obj.product.get_absolute_url()), (resource.label_plural, ctx["records_url"]),
                     (str(obj)[:40], obj.get_absolute_url())]
    return import_page(request, spec, audit=audit, extra_context=ctx)


@login_required
def import_hub(request):
    """One page listing every import the user can run."""
    rows = []
    for module in registry.modules(include_tasks=True):
        for key in module.resources:
            res = registry.get(key)
            if res.importable and (product_ids_for(request.user, res.module, "write") or is_org_admin(request.user)):
                rows.append({"module": module, "resource": res})
    products = accessible_products(request.user).filter(is_active=True)
    selected = products.filter(slug=request.GET.get("product", "")).first()
    for row in rows:
        row["can_import"] = selected is None or has_level(request.user, selected, row["resource"].module, "write")
    admin_imports = []
    if is_org_admin(request.user):
        from django.urls import reverse

        admin_imports = [
            ("Users", "bi-people", reverse("admin_panel:users_import")),
            ("Products", "bi-boxes", reverse("admin_panel:products_import")),
        ] + [(cfg["label"], cfg["icon"], reverse("admin_panel:config_import", args=[k]))
             for k, cfg in __import__("apps.admin_panel.views", fromlist=["CONFIG"]).CONFIG.items()]
    return render(request, "imports/hub.html", {"rows": rows, "products": products, "selected": selected,
                                                "admin_imports": admin_imports})


# --------------------------------------------------------------------------- attachments & children

@login_required
@require_POST
def attachment_upload(request, resource, pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        att = form.save(commit=False)
        att.content_object = obj
        att.product = obj.product
        att.original_name = request.FILES["file"].name[:255]
        att.size = request.FILES["file"].size
        att.uploaded_by = request.user
        att.save()
        log_action(AuditLog.Action.ATTACH, obj, request.user, message=f"Attached {att.original_name}")
        messages.success(request, f"Uploaded {att.original_name}.")
    else:
        for err in form.errors.get("file", []):
            messages.error(request, f"Upload failed: {err}")
    return redirect(obj.get_absolute_url() + "#attachments")


def _attachment_with_access(request, att_id, level):
    att = get_object_or_404(Attachment, pk=att_id)
    target = att.content_object
    resource = getattr(target, "resource", None)
    if target is None or resource is None:
        raise Http404
    get_record(request, resource, target.pk, level)
    return att, target, resource


@login_required
def attachment_download(request, att_id):
    att, target, resource = _attachment_with_access(request, att_id, "read")
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404("File missing")
    return FileResponse(fh, as_attachment=not att.is_image, filename=att.original_name)


@login_required
@require_POST
def attachment_delete(request, att_id):
    att, target, resource = _attachment_with_access(request, att_id, "write")
    name = att.original_name
    att.file.delete(save=False)
    att.delete()
    log_action(AuditLog.Action.DETACH, target, request.user, message=f"Removed {name}")
    messages.success(request, f"Removed {name}.")
    return redirect(target.get_absolute_url() + "#attachments")


@login_required
@require_POST
def child_add(request, resource, pk, child):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    spec = next((c for c in resource.children if c.key == child), None)
    if spec is None:
        raise Http404
    form = child_form_class(spec)(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        setattr(item, spec.fk_name, obj)
        if hasattr(item, "created_by_id"):
            item.created_by = request.user
        if hasattr(item, "product_id") and not item.product_id:
            item.product_id = obj.product_id
        item.save()
        log_action(AuditLog.Action.UPDATE, obj, request.user, message=f"Added {spec.label.lower()} entry")
        messages.success(request, f"{spec.label}: entry added.")
    else:
        for field, errs in form.errors.items():
            messages.error(request, f"{field}: {'; '.join(errs)}")
    return redirect(obj.get_absolute_url() + f"#child-{spec.key}")


@login_required
@require_POST
def child_delete(request, resource, pk, child, child_pk):
    resource = get_resource(resource)
    obj = get_record(request, resource, pk, "write")
    spec = next((c for c in resource.children if c.key == child), None)
    if spec is None:
        raise Http404
    item = get_object_or_404(spec.model, pk=child_pk, **{spec.fk_name: obj})
    item.delete()
    log_action(AuditLog.Action.UPDATE, obj, request.user, message=f"Removed {spec.label.lower()} entry")
    messages.success(request, "Entry removed.")
    return redirect(obj.get_absolute_url() + f"#child-{spec.key}")


# --------------------------------------------------------------------------- module landing

@login_required
def module_redirect(request, module):
    mod = registry.module(module)
    if mod is None or not mod.resources:
        raise Http404
    slug = request.GET.get("product")
    resource = mod.primary_resource
    if slug:
        return redirect("products:records", slug=slug, resource=resource.key)
    return redirect("records:list", resource=resource.key)
