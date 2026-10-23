"""
Custom application admin panel (/admin-panel/).

Organization admins (and Super Admins) can manage everything. Product managers can
manage the settings, module configuration, members and targets of their own products.
Configuration is persisted in the database; no arbitrary code, SQL or templates can be
entered anywhere.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import UserProfile
from apps.accounts.permissions import can_manage_product, is_org_admin
from apps.analytics import layout
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.models import (
    Attachment,
    Category,
    CustomFieldDefinition,
    DashboardItem,
    ModuleSetting,
    Notification,
    StatusOption,
    Tag,
    Target,
)
from apps.core.exporting import export_filename, export_tables, plain, requested_format
from apps.core.notifications import notify
from apps.core.registry import registry
from apps.core.statuses import get_statuses
from apps.investors.models import InvestorCategory
from apps.listings.models import ListingPlatform
from apps.products.models import MembershipModulePermission, Product, ProductMembership, ProductModuleConfiguration

from . import forms as f

User = get_user_model()


def admin_required(view):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_org_admin(request.user):
            raise PermissionDenied("Organization administrators only.")
        return view(request, *args, **kwargs)
    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return wrapped


def managed_products(user):
    if is_org_admin(user):
        return Product.objects.all()
    ids = ProductMembership.objects.filter(user=user, role="product_manager", is_active=True).values("product_id")
    return Product.objects.filter(pk__in=ids)


def panel_required(view):
    """Org admins, or product managers (for their own products)."""
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_org_admin(request.user) and not managed_products(request.user).exists():
            raise PermissionDenied("You do not manage any products.")
        return view(request, *args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


def _export(request, fmt, title, headers, rows):
    log_action(AuditLog.Action.EXPORT, None, request.user, message=f"Admin panel export: {title} ({fmt})")
    return export_tables([{"title": title, "headers": headers, "rows": rows}], fmt, export_filename(title), title)


def get_managed_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if not can_manage_product(request.user, product):
        raise PermissionDenied("You cannot manage this product.")
    return product


# --------------------------------------------------------------------------- overview

@panel_required
def index(request):
    ctx = {
        "is_admin": is_org_admin(request.user),
        "counts": {
            "products": Product.objects.count(),
            "users": User.objects.filter(is_active=True).count(),
            "memberships": ProductMembership.objects.filter(is_active=True).count(),
            "custom_fields": CustomFieldDefinition.objects.filter(is_active=True).count(),
            "statuses": StatusOption.objects.count(),
            "categories": Category.objects.count(),
            "targets": Target.objects.count(),
            "platforms": ListingPlatform.objects.count(),
            "attachments": Attachment.objects.count(),
            "audit": AuditLog.objects.count(),
        },
        "recent_audit": AuditLog.objects.select_related("user", "product")[:10],
        "products": managed_products(request.user),
    }
    return render(request, "admin_panel/index.html", ctx)


# --------------------------------------------------------------------------- products

@panel_required
def product_list(request):
    products = managed_products(request.user).annotate(members=Count("memberships", distinct=True))
    return render(request, "admin_panel/products.html", {"products": products,
                                                         "is_admin": is_org_admin(request.user)})


@admin_required
def product_create(request):
    form = f.ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        log_action(AuditLog.Action.CONFIG, product, request.user, product=product, message="Product created")
        messages.success(request, f"Product {product} created. All nine modules are enabled by default.")
        return redirect("admin_panel:product_edit", pk=product.pk)
    return render(request, "admin_panel/form.html", {"form": form, "title": "Add product",
                                                     "back": "admin_panel:products"})


@panel_required
def product_edit(request, pk):
    product = get_managed_product(request, pk)
    form = f.ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(AuditLog.Action.CONFIG, product, request.user, product=product,
                   changes={k: str(form.cleaned_data.get(k)) for k in form.changed_data if k != "logo"},
                   message="Product settings updated")
        messages.success(request, "Product saved.")
        return redirect("admin_panel:product_edit", pk=product.pk)
    fmt = requested_format(request)
    if fmt:
        rows = []
        for mb in product.memberships.select_related("user").prefetch_related("module_permissions"):
            overrides = "; ".join(f"{p.module}: {p.get_level_display()}" for p in mb.module_permissions.all())
            rows.append([mb.user.username, mb.user.get_full_name(), mb.user.email, mb.get_role_display(),
                         "Active" if mb.is_active else "Suspended", overrides])
        return _export(request, fmt, f"{product.name} members", ["Username", "Name", "Email", "Role", "Status",
                                                                 "Module overrides"], rows)
    configs = {c.module: c for c in product.module_configs.all()}
    modules = [{"module": m, "config": configs.get(m.key)} for m in registry.modules()]
    return render(request, "admin_panel/product_edit.html", {
        "product": product, "form": form, "modules": modules,
        "memberships": product.memberships.select_related("user").order_by("user__username"),
        "targets": product.targets.all(),
    })


@panel_required
@require_POST
def product_modules(request, pk):
    product = get_managed_product(request, pk)
    with transaction.atomic():
        for i, module in enumerate(registry.modules()):
            enabled = request.POST.get(f"enabled_{module.key}") == "on"
            try:
                order = int(request.POST.get(f"order_{module.key}", i))
            except ValueError:
                order = i
            name = (request.POST.get(f"name_{module.key}") or "").strip()[:80]
            ProductModuleConfiguration.objects.update_or_create(
                product=product, module=module.key,
                defaults={"is_enabled": enabled, "display_order": order, "display_name": name},
            )
    log_action(AuditLog.Action.CONFIG, product, request.user, product=product, message="Module configuration saved")
    messages.success(request, "Module configuration saved.")
    return redirect("admin_panel:product_edit", pk=product.pk)


@admin_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = str(product)
    try:
        with transaction.atomic():
            product.delete()
        log_action(AuditLog.Action.DELETE, None, request.user, message=f"Product {name} deleted")
        messages.success(request, f"Product {name} deleted.")
    except ProtectedError:
        messages.error(request, "This product has records. Deactivate it instead of deleting.")
    return redirect("admin_panel:products")


# --------------------------------------------------------------------------- members

@panel_required
def membership_add(request, pk):
    product = get_managed_product(request, pk)
    form = f.MembershipForm(request.POST or None, product=product)
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.product = product
        m.save()
        log_action(AuditLog.Action.PERMISSION, m, request.user, product=product,
                   message=f"{m.user} added as {m.get_role_display()}")
        notify(m.user, f"You were added to {product}", f"Role: {m.get_role_display()}", product.get_absolute_url(),
               product=product)
        messages.success(request, f"{m.user} added to {product}.")
        return redirect("admin_panel:product_edit", pk=product.pk)
    return render(request, "admin_panel/form.html", {"form": form, "title": f"Add member to {product}",
                                                     "back_url": product_edit_url(product)})


def product_edit_url(product):
    from django.urls import reverse

    return reverse("admin_panel:product_edit", kwargs={"pk": product.pk})


@panel_required
def membership_edit(request, pk):
    membership = get_object_or_404(ProductMembership.objects.select_related("product", "user"), pk=pk)
    product = get_managed_product(request, membership.product_id)
    form = f.MembershipForm(request.POST or None, instance=membership, product=product, prefix="m")
    perm_form = f.ModulePermissionsForm(membership, request.POST or None, prefix="p")
    if request.method == "POST" and form.is_valid() and perm_form.is_valid():
        with transaction.atomic():
            form.save()
            for module_key, level in perm_form.cleaned_data.items():
                if level:
                    MembershipModulePermission.objects.update_or_create(
                        membership=membership, module=module_key, defaults={"level": level})
                else:
                    MembershipModulePermission.objects.filter(membership=membership, module=module_key).delete()
        log_action(AuditLog.Action.PERMISSION, membership, request.user, product=product,
                   changes={k: v for k, v in perm_form.cleaned_data.items() if v},
                   message=f"Permissions updated for {membership.user}")
        messages.success(request, "Membership and module permissions saved.")
        return redirect("admin_panel:product_edit", pk=product.pk)
    return render(request, "admin_panel/membership_edit.html", {"membership": membership, "form": form,
                                                                "perm_form": perm_form, "product": product})


@panel_required
@require_POST
def membership_remove(request, pk):
    membership = get_object_or_404(ProductMembership, pk=pk)
    product = get_managed_product(request, membership.product_id)
    log_action(AuditLog.Action.PERMISSION, membership, request.user, product=product,
               message=f"{membership.user} removed from {product}")
    membership.delete()
    messages.success(request, "Member removed.")
    return redirect("admin_panel:product_edit", pk=product.pk)


# --------------------------------------------------------------------------- users

@admin_required
def user_list(request):
    q = request.GET.get("q", "").strip()
    users = User.objects.select_related("profile").annotate(product_count=Count("memberships")).order_by("username")
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q)
                             | Q(last_name__icontains=q))
    fmt = requested_format(request)
    if fmt:
        memberships = {}
        for mb in ProductMembership.objects.select_related("product"):
            memberships.setdefault(mb.user_id, []).append(f"{mb.product.name} ({mb.get_role_display()})")
        rows = [[u.username, u.get_full_name(), u.email, getattr(getattr(u, "profile", None), "role_label", ""),
                 "; ".join(memberships.get(u.pk, [])), "Active" if u.is_active else "Inactive",
                 plain(u.last_login), plain(u.date_joined)] for u in users]
        return _export(request, fmt, "Users & roles", ["Username", "Name", "Email", "Role", "Products",
                                                       "Status", "Last login", "Joined"], rows)
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    return render(request, "admin_panel/users.html", {"page": page, "q": q})


def _save_user(form, request, is_new):
    with transaction.atomic():
        user = form.save(commit=False)
        if form.cleaned_data.get("password1"):
            user.set_password(form.cleaned_data["password1"])
        user.save()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not user.is_superuser:
            profile.org_role = form.cleaned_data.get("org_role") or ""
        profile.job_title = form.cleaned_data.get("job_title") or ""
        profile.save()
    log_action(AuditLog.Action.PERMISSION if "org_role" in form.changed_data else AuditLog.Action.CONFIG, user,
               request.user, changes={k: "changed" for k in form.changed_data if not k.startswith("password")},
               message="User created" if is_new else "User updated")
    return user


@admin_required
def user_create(request):
    form = f.UserCreateForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        user = _save_user(form, request, True)
        messages.success(request, f"User {user.username} created. Add them to products to grant access.")
        return redirect("admin_panel:user_edit", pk=user.pk)
    return render(request, "admin_panel/form.html", {"form": form, "title": "Add user", "back": "admin_panel:users"})


@admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.is_superuser and not request.user.is_superuser:
        raise PermissionDenied("Only Super Admins can edit Super Admin accounts.")
    form = f.UserEditForm(request.POST or None, instance=target, user=request.user)
    if request.method == "POST" and form.is_valid():
        if target == request.user and not form.cleaned_data.get("is_active"):
            form.add_error("is_active", "You cannot deactivate your own account.")
        else:
            _save_user(form, request, False)
            messages.success(request, "User saved.")
            return redirect("admin_panel:user_edit", pk=target.pk)
    memberships = target.memberships.select_related("product")
    return render(request, "admin_panel/user_edit.html", {"form": form, "target": target,
                                                          "memberships": memberships})


# --------------------------------------------------------------------------- generic configuration CRUD

CONFIG = {
    "statuses": {"model": StatusOption, "form": f.StatusOptionForm, "label": "Statuses", "icon": "bi-flag",
                 "columns": ["resource", "label", "key", "state", "color", "order", "is_active"],
                 "help": "Statuses available per module. 'Completed' counts toward completion KPIs; 'Closed' "
                         "removes the item from pending and overdue counts."},
    "categories": {"model": Category, "form": f.CategoryForm, "label": "Categories", "icon": "bi-folder",
                   "columns": ["name", "resource", "product", "is_active"]},
    "tags": {"model": Tag, "form": f.TagForm, "label": "Tags", "icon": "bi-tags", "columns": ["name", "color"]},
    "custom-fields": {"model": CustomFieldDefinition, "form": f.CustomFieldForm, "label": "Custom fields",
                      "icon": "bi-input-cursor-text",
                      "columns": ["resource", "label", "key", "field_type", "product", "required", "show_in_list",
                                  "is_active"],
                      "help": "Supported types: text, long text, number, currency, date, URL, yes/no, single and "
                              "multi-select. Values are validated on every form and import."},
    "targets": {"model": Target, "form": f.TargetForm, "label": "Targets & KPIs", "icon": "bi-bullseye",
                "columns": ["product", "metric", "label", "target_value", "period_start", "period_end"],
                "product_scoped": True,
                "help": "Actual values are computed live from records for the target period."},
    "listing-platforms": {"model": ListingPlatform, "form": f.ListingPlatformForm, "label": "Listing platforms",
                          "icon": "bi-globe2", "columns": ["name", "kind", "website_url", "is_active", "display_order"],
                          "help": "Catalog of directories and review sites. Each product's submission is tracked "
                                  "as a listing record."},
    "investor-categories": {"model": InvestorCategory, "form": f.InvestorCategoryForm,
                            "label": "Investor categories", "icon": "bi-bank",
                            "columns": ["name", "description", "is_active", "display_order"],
                            "help": "Prospective investor categories only — not confirmed relationships."},
}


def _config(key, request):
    cfg = CONFIG.get(key)
    if cfg is None:
        raise Http404
    if cfg.get("product_scoped"):
        if not is_org_admin(request.user) and not managed_products(request.user).exists():
            raise PermissionDenied
    elif not is_org_admin(request.user):
        raise PermissionDenied("Organization administrators only.")
    return cfg


def _config_qs(cfg, request):
    qs = cfg["model"].objects.all()
    if cfg.get("product_scoped") and not is_org_admin(request.user):
        qs = qs.filter(product__in=managed_products(request.user))
    return qs


@login_required
def config_list(request, key):
    cfg = _config(key, request)
    qs = _config_qs(cfg, request)
    resource = request.GET.get("resource")
    if resource and hasattr(cfg["model"], "resource"):
        qs = qs.filter(resource=resource)
    q = request.GET.get("q", "").strip()
    if q:
        name_field = "label" if hasattr(cfg["model"], "label") and key != "categories" else "name"
        qs = qs.filter(**{f"{name_field}__icontains": q})
    fmt = requested_format(request)
    if fmt:
        return _export(request, fmt, cfg["label"], [_header(cfg["model"], c) for c in cfg["columns"]],
                       [[_display(o, c) for c in cfg["columns"]] for o in qs])
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rows = [{"obj": o, "cells": [_display(o, c) for c in cfg["columns"]]} for o in page.object_list]
    defaults_notice = None
    if key == "statuses" and not StatusOption.objects.exists():
        defaults_notice = "Built-in default statuses are in use. Run the seed command or add statuses here."
    return render(request, "admin_panel/config_list.html", {
        "cfg": cfg, "key": key, "page": page, "rows": rows,
        "headers": [_header(cfg["model"], c) for c in cfg["columns"]],
        "resources": f.resource_choices() if hasattr(cfg["model"], "resource") else None,
        "selected_resource": resource, "q": q, "defaults_notice": defaults_notice,
    })


def _header(model, name):
    try:
        return model._meta.get_field(name).verbose_name.capitalize()
    except Exception:
        return name.replace("_", " ").capitalize()


def _display(obj, name):
    field = obj._meta.get_field(name)
    if field.choices:
        return getattr(obj, f"get_{name}_display")()
    if name == "resource":
        res = registry.get(obj.resource)
        return res.label_plural if res else (obj.resource or "All modules")
    value = getattr(obj, name)
    if name == "metric":
        from apps.analytics.targets import METRICS

        return METRICS.get(value, (value,))[0]
    if value is None:
        return "—"
    return value


@login_required
def config_edit(request, key, pk=None):
    cfg = _config(key, request)
    instance = get_object_or_404(_config_qs(cfg, request), pk=pk) if pk else None
    form = cfg["form"](request.POST or None, instance=instance, user=request.user,
                       initial={"resource": request.GET.get("resource", "")} if not pk else None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_action(AuditLog.Action.CONFIG, obj, request.user, product=getattr(obj, "product", None),
                   changes={k: str(form.cleaned_data.get(k)) for k in form.changed_data},
                   message=f"{cfg['label']}: {'updated' if pk else 'created'} {obj}")
        messages.success(request, f"{cfg['label']}: saved “{obj}”.")
        return redirect("admin_panel:config_list", key=key)
    return render(request, "admin_panel/form.html", {"form": form, "cfg": cfg,
                                                     "title": f"{'Edit' if pk else 'Add'} — {cfg['label']}",
                                                     "back_url": f"/admin-panel/config/{key}/"})


@login_required
@require_POST
def config_delete(request, key, pk):
    cfg = _config(key, request)
    obj = get_object_or_404(_config_qs(cfg, request), pk=pk)
    label = str(obj)
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, f"“{label}” is in use by existing records. Deactivate it instead.")
        return redirect("admin_panel:config_list", key=key)
    log_action(AuditLog.Action.CONFIG, None, request.user, message=f"{cfg['label']}: deleted {label}")
    messages.success(request, f"Deleted “{label}”.")
    return redirect("admin_panel:config_list", key=key)


@admin_required
@require_POST
def statuses_materialize(request):
    """Copy built-in default statuses into editable StatusOption rows (only missing ones)."""
    created = 0
    for res in registry.resources():
        for i, (k, label, state, color) in enumerate(res.default_statuses):
            _, was_created = StatusOption.objects.get_or_create(
                resource=res.key, key=k, defaults={"label": label, "state": state, "color": color, "order": i})
            created += was_created
    log_action(AuditLog.Action.CONFIG, None, request.user, message=f"Default statuses created ({created})")
    messages.success(request, f"{created} default status(es) created. You can now edit them.")
    return redirect("admin_panel:config_list", key="statuses")


# --------------------------------------------------------------------------- dashboard layout & columns

@panel_required
def dashboard_layout(request):
    products = managed_products(request.user)
    pid = request.GET.get("product") or request.POST.get("product")
    product = products.filter(pk=pid).first() if pid else None
    if product is None and not is_org_admin(request.user):
        product = products.first()
    if request.method == "POST":
        with transaction.atomic():
            for item_type, defaults in ((DashboardItem.SECTION, layout.PRODUCT_SECTIONS if product
                                         else layout.ORG_SECTIONS), (DashboardItem.KPI, layout.KPI_CARDS)):
                DashboardItem.objects.filter(product=product, item_type=item_type).delete()
                for i, (k, _label) in enumerate(defaults):
                    try:
                        order = int(request.POST.get(f"{item_type}_order_{k}", i))
                    except ValueError:
                        order = i
                    DashboardItem.objects.create(product=product, item_type=item_type, key=k, order=order,
                                                 is_visible=request.POST.get(f"{item_type}_visible_{k}") == "on")
        log_action(AuditLog.Action.CONFIG, product, request.user, product=product,
                   message=f"Dashboard layout saved ({product or 'organization'})")
        messages.success(request, "Dashboard layout saved.")
        return redirect(f"{request.path}?product={product.pk if product else ''}")
    return render(request, "admin_panel/dashboard_layout.html", {
        "products": products, "product": product, "is_admin": is_org_admin(request.user),
        "sections": layout.sections(product), "kpis": layout.kpi_cards(product),
    })


@admin_required
def table_columns(request):
    resources = registry.resources()
    key = request.GET.get("resource") or request.POST.get("resource") or resources[0].key
    resource = registry.get(key)
    if resource is None:
        raise Http404
    setting = ModuleSetting.objects.filter(resource=key).first()
    current = (setting.list_columns if setting and setting.list_columns else resource.list_columns)
    if request.method == "POST":
        allowed = resource.allowed_columns
        chosen = [c for c in request.POST.getlist("columns") if c in allowed]
        order = {c: int(request.POST.get(f"order_{c}") or 0) if (request.POST.get(f"order_{c}") or "0").isdigit()
                 else 0 for c in chosen}
        chosen.sort(key=lambda c: order[c])
        try:
            size = max(5, min(200, int(request.POST.get("page_size", 25))))
        except ValueError:
            size = 25
        ModuleSetting.objects.update_or_create(resource=key, defaults={"list_columns": chosen, "page_size": size})
        log_action(AuditLog.Action.CONFIG, None, request.user, resource=key, message="Table columns updated")
        messages.success(request, f"Columns saved for {resource.label_plural}.")
        return redirect(f"{request.path}?resource={key}")
    columns = [{"name": c, "label": resource.column_label(c), "checked": c in current,
                "order": current.index(c) if c in current else 99} for c in resource.allowed_columns]
    columns.sort(key=lambda c: (not c["checked"], c["order"]))
    return render(request, "admin_panel/table_columns.html", {
        "resources": resources, "resource": resource, "columns": columns,
        "page_size": setting.page_size if setting else 25,
    })


# --------------------------------------------------------------------------- notifications, audit, attachments

@admin_required
def broadcast(request):
    form = f.BroadcastForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.cleaned_data["product"]
        users = User.objects.filter(is_active=True)
        if product:
            users = users.filter(memberships__product=product, memberships__is_active=True).distinct()
        sent = sum(1 for u in users if notify(u, form.cleaned_data["title"], form.cleaned_data["message"],
                                              form.cleaned_data["url"], form.cleaned_data["level"], product))
        log_action(AuditLog.Action.CONFIG, None, request.user, product=product,
                   message=f"Broadcast notification to {sent} user(s)")
        messages.success(request, f"In-app notification created for {sent} user(s).")
        return redirect("admin_panel:broadcast")
    recent = Notification.objects.select_related("user").order_by("-created_at")[:20]
    return render(request, "admin_panel/broadcast.html", {"form": form, "recent": recent})


@admin_required
def audit_log(request):
    qs = AuditLog.objects.select_related("user", "product")
    for param, field in (("action", "action"), ("resource", "resource"), ("product", "product_id"),
                         ("user", "user_id")):
        v = request.GET.get(param)
        if v:
            qs = qs.filter(**{field: v})
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(object_repr__icontains=q) | Q(message__icontains=q))
    fmt = requested_format(request)
    if fmt:
        rows = [[plain(a.created_at), plain(a.user), a.get_action_display(), a.object_repr, a.resource,
                 a.product.name if a.product else "", a.message,
                 "; ".join(f"{k}: {v.get('from', '') if isinstance(v, dict) else ''} → "
                           f"{v.get('to', '') if isinstance(v, dict) else v}" for k, v in a.changes.items()),
                 a.ip_address or ""] for a in qs[:20000]]
        return _export(request, fmt, "Audit log", ["When", "User", "Action", "Record", "Module", "Product",
                                                   "Message", "Changes", "IP"], rows)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "admin_panel/audit.html", {
        "page": page, "actions": AuditLog.Action.choices, "products": Product.objects.all(),
        "resources": registry.resources(), "users": User.objects.order_by("username"),
        "querystring": query.urlencode(),
    })


@admin_required
def attachments(request):
    qs = Attachment.objects.select_related("uploaded_by", "product", "content_type")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(original_name__icontains=q)
    fmt = requested_format(request)
    if fmt:
        rows = [[a.original_name, str(a.content_object or "Deleted record"), a.content_type.model,
                 a.product.name if a.product else "", a.size, plain(a.uploaded_by), plain(a.created_at),
                 a.description] for a in qs]
        return _export(request, fmt, "Attachments", ["File", "Record", "Type", "Product", "Size (bytes)",
                                                     "Uploaded by", "Uploaded", "Description"], rows)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "admin_panel/attachments.html", {"page": page, "q": q})


@admin_required
def module_overview(request):
    """Module configuration overview: statuses, custom fields and enablement per product."""
    products = Product.objects.all()
    disabled = {}
    for c in ProductModuleConfiguration.objects.filter(is_enabled=False):
        disabled.setdefault(c.module, set()).add(c.product_id)
    rows = []
    for module in registry.modules(include_tasks=True):
        rows.append({
            "module": module,
            "resources": [registry.get(k) for k in module.resources],
            "statuses": sum(len(get_statuses(k)) for k in module.resources),
            "custom_fields": CustomFieldDefinition.objects.filter(resource__in=module.resources).count(),
            "enabled": [p for p in products if p.pk not in disabled.get(module.key, set())],
        })
    return render(request, "admin_panel/modules.html", {"rows": rows, "products": products})


# --------------------------------------------------------------------------- imports

def _admin_import(request, spec, label):
    from apps.core.importing import import_page

    def audit(count):
        log_action(AuditLog.Action.IMPORT, None, request.user, message=f"Imported {count} {label}")

    return import_page(request, spec, audit=audit, extra_context={
        "base_template": "admin_panel/_base.html", "crumbs": [("Admin panel", "/admin-panel/")]})


@login_required
def config_import(request, key):
    from django.urls import reverse

    from apps.core.importing import ImportSpec

    cfg = _config(key, request)
    form_cls = cfg["form"]
    columns = [n for n in form_cls(user=request.user).fields]
    product = managed_products(request.user).first()

    model = cfg["model"]
    unique_name = next((n for n in ("name",) if n in columns and model._meta.get_field(n).unique), None)

    def match_existing(data):  # re-importing an entry with the same unique name updates it
        if unique_name and data.get(unique_name):
            return _config_qs(cfg, request).filter(**{f"{unique_name}__iexact": data[unique_name].strip()}).first()
        if key == "statuses" and data.get("resource") and data.get("key"):
            return StatusOption.objects.filter(resource=data["resource"], key=data["key"].strip()).first()
        if key == "custom-fields" and data.get("resource") and data.get("key"):
            return CustomFieldDefinition.objects.filter(resource=data["resource"], key=data["key"].strip()).first()
        return None

    spec = ImportSpec(
        key=key, title=cfg["label"], columns=columns,
        form_factory=lambda data=None, instance=None: form_cls(data=data, instance=instance, user=request.user),
        save=lambda form: form.save(), back_url=reverse("admin_panel:config_list", args=[key]),
        filename=key, description=cfg.get("help", ""), sample_context={"product": product, "user": request.user},
        match_existing=match_existing, note_field=None,
    )
    return _admin_import(request, spec, cfg["label"])


@admin_required
def users_import(request):
    from django.urls import reverse

    from apps.core.importing import ImportSpec

    def save(form):
        with transaction.atomic():
            user = form.save(commit=False)
            user.set_unusable_password()
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.org_role = form.cleaned_data.get("org_role") or ""
            profile.job_title = form.cleaned_data.get("job_title") or ""
            profile.save()
        return user

    spec = ImportSpec(
        key="users", title="Users", columns=["username", "first_name", "last_name", "email", "is_active",
                                             "org_role", "job_title"],
        form_factory=lambda data=None: f.UserImportForm(data=data), save=save,
        back_url=reverse("admin_panel:users"), filename="users", defaults={"is_active": "yes"},
        description="Imported users have no password: they set one with “Forgot password” on the sign-in page. "
                    "Then add them to products (Products → Members → Import members).",
        sample_context={"user": request.user},
    )
    return _admin_import(request, spec, "users")


@admin_required
def products_import(request):
    from django.urls import reverse

    from apps.core.importing import ImportSpec

    columns = ["name", "slug", "tagline", "description", "brand_color", "website", "is_active", "display_order"]
    spec = ImportSpec(
        key="products", title="Products", columns=columns,
        form_factory=lambda data=None: f.ProductImportForm(data=data), save=lambda form: form.save(),
        back_url=reverse("admin_panel:products"), filename="products",
        defaults={"is_active": "yes", "display_order": "0", "brand_color": "#4F46E5"},
        description="Logos can be uploaded afterwards on each product's settings page.",
    )
    return _admin_import(request, spec, "products")


@panel_required
def members_import(request, pk):
    from django.urls import reverse

    from apps.core.importing import ImportSpec

    product = get_managed_product(request, pk)

    def save(form):
        m = form.save(commit=False)
        m.product = product
        m.save()
        notify(m.user, f"You were added to {product}", f"Role: {m.get_role_display()}", product.get_absolute_url(),
               product=product)
        return m

    spec = ImportSpec(
        key="members", title=f"{product.name} members", columns=["user", "role", "is_active"],
        form_factory=lambda data=None: f.MembershipForm(data=data, product=product), save=save,
        back_url=reverse("admin_panel:product_edit", args=[product.pk]), filename=f"{product.slug}-members",
        defaults={"is_active": "yes"},
        description="“user” is the username or email of an existing user. Import users first if needed.",
        sample_context={"user": request.user},
    )
    return _admin_import(request, spec, f"{product.name} members")
