from django.conf import settings

from apps.accounts.permissions import accessible_products, is_org_admin, module_level

from .models import Notification
from .registry import registry


def navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"currency_symbol": getattr(settings, "CURRENCY_SYMBOL", "₹")}
    products = list(accessible_products(user).filter(is_active=True))
    match = getattr(request, "resolver_match", None)
    current = None
    slug = (match.kwargs.get("slug") if match else None) or request.GET.get("product")
    if slug:
        current = next((p for p in products if p.slug == slug), None)
    modules = []
    for mod in registry.modules():
        if current is not None:
            if module_level(user, current, mod.key) == "none":
                continue
        modules.append(mod)
    from apps.products.models import ProductMembership

    manages = is_org_admin(user) or ProductMembership.objects.filter(
        user=user, role="product_manager", is_active=True).exists()
    from django.urls import reverse

    palette = [
        {"group": "Go to", "label": "Organization dashboard", "url": reverse("analytics:dashboard"), "icon": "bi-speedometer2"},
        {"group": "Go to", "label": "My day & follow-ups", "url": reverse("tasks:overview"), "icon": "bi-calendar-check"},
        {"group": "Go to", "label": "Reports", "url": reverse("reports:index"), "icon": "bi-file-earmark-bar-graph"},
        {"group": "Go to", "label": "Import data", "url": reverse("import_hub"), "icon": "bi-upload"},
        {"group": "Go to", "label": "Notifications", "url": reverse("notifications:list"), "icon": "bi-bell"},
        {"group": "Go to", "label": "My profile & access", "url": reverse("accounts:profile"), "icon": "bi-person"},
    ]
    palette += [{"group": "Products", "label": p.name, "hint": p.tagline, "url": p.get_absolute_url(),
                 "icon": "bi-box", "color": p.brand_color} for p in products]
    for mod in registry.modules(include_tasks=True):
        for key in mod.resources:
            res = registry.get(key)
            if current is not None:
                url = reverse("products:records", kwargs={"slug": current.slug, "resource": key})
            else:
                url = reverse("records:list", args=[key])
            palette.append({"group": "Modules", "label": res.label_plural, "hint": mod.label, "url": url,
                            "icon": res.icon})
            palette.append({"group": "Create", "label": f"New {res.label.lower()}", "hint": mod.short_label,
                            "url": reverse("products:record_create", kwargs={"slug": current.slug, "resource": key})
                            if current is not None else reverse("records:create", args=[key]),
                            "icon": "bi-plus-lg"})
    from apps.email_marketing import access as email_marketing
    from apps.email_marketing.views import open_url as email_open_url

    # Cold Email opens the email system (for the current product) full page, signed in, when allowed.
    email_url = email_open_url(current) if email_marketing.can_open(user, current) else None
    if email_url:
        palette.append({"group": "Go to", "label": f"Email dashboard{f' · {current.name}' if current else ''}",
                        "hint": "The email system, signed in", "url": email_url, "icon": "bi-envelope-paper"})
    manages_panel = is_org_admin(user)
    if manages_panel:
        palette += [
            {"group": "Admin", "label": "Admin panel", "url": reverse("admin_panel:index"), "icon": "bi-sliders"},
            {"group": "Admin", "label": "Users & roles", "url": reverse("admin_panel:users"), "icon": "bi-people"},
            {"group": "Admin", "label": "Products & members", "url": reverse("admin_panel:products"), "icon": "bi-boxes"},
            {"group": "Admin", "label": "Custom fields", "url": reverse("admin_panel:config_list", args=["custom-fields"]), "icon": "bi-input-cursor-text"},
            {"group": "Admin", "label": "Dashboard layout", "url": reverse("admin_panel:dashboard_layout"), "icon": "bi-layout-wtf"},
            {"group": "Admin", "label": "Integrations", "url": reverse("integrations:list"), "icon": "bi-plug"},
            {"group": "Admin", "label": "Audit log", "url": reverse("admin_panel:audit"), "icon": "bi-journal-text"},
        ]
    return {
        "palette_items": palette,
        "nav_products": products,
        "nav_current_product": current,
        "nav_modules": modules,
        "nav_email_url": email_url,
        "nav_tasks_module": registry.module("tasks"),
        "nav_is_admin": is_org_admin(user),
        "nav_can_admin_panel": manages,
        "nav_unread": Notification.objects.filter(user=user, is_read=False).count(),
        "currency_symbol": getattr(settings, "CURRENCY_SYMBOL", "₹"),
    }
