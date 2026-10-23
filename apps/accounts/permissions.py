"""
Server-side access control.

Hierarchy:
* Super Admin (``is_superuser``) and Organization Admin (``UserProfile.org_role``)
  can manage everything, including inactive products.
* Everyone else needs an active ``ProductMembership``. Their role gives a default
  access level per module, which may be overridden per module through
  ``MembershipModulePermission``.

Levels: none < read < write < manage. ``manage`` additionally allows hard delete
and product configuration (targets, enabled modules) for that product.

Every view, export, report, search and API endpoint obtains its querysets via
``scoped_queryset`` so changing URLs or IDs can never expose another product's data.
"""
from django.db.models import Q

LEVELS = {"none": 0, "read": 1, "write": 2, "manage": 3}

MARKETING_MODULES = {"listings", "community", "seo", "advertising", "events", "outreach", "social"}
SALES_MODULES = {"outreach", "meetings", "consultants", "investors", "events"}

ROLE_DEFAULTS = {
    "product_manager": lambda module: "manage",
    "marketing_manager": lambda module: "write" if module in MARKETING_MODULES | {"tasks"} else "read",
    "sales_bd": lambda module: "write" if module in SALES_MODULES | {"tasks"} else "read",
    "team_member": lambda module: "write",
    "viewer": lambda module: "read",
}


def is_org_admin(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.org_role == "org_admin")


def _membership_map(user):
    """{product_id: {"role": str, "overrides": {module: level}}} cached on the user object per request."""
    cache = getattr(user, "_membership_cache", None)
    if cache is not None:
        return cache
    from apps.products.models import ProductMembership

    cache = {}
    memberships = (
        ProductMembership.objects.filter(user=user, is_active=True, product__is_active=True)
        .prefetch_related("module_permissions")
    )
    for m in memberships:
        cache[m.product_id] = {
            "role": m.role,
            "overrides": {p.module: p.level for p in m.module_permissions.all()},
        }
    user._membership_cache = cache
    return cache


def _disabled_modules(product_id):
    from apps.products.models import ProductModuleConfiguration

    return set(
        ProductModuleConfiguration.objects.filter(product_id=product_id, is_enabled=False).values_list(
            "module", flat=True
        )
    )


def _disabled_map():
    from apps.products.models import ProductModuleConfiguration

    out = {}
    for pid, module in ProductModuleConfiguration.objects.filter(is_enabled=False).values_list("product_id", "module"):
        out.setdefault(pid, set()).add(module)
    return out


def module_level(user, product, module):
    """Effective access level of ``user`` for ``module`` in ``product``."""
    if not user or not user.is_authenticated or not user.is_active:
        return "none"
    product_id = getattr(product, "pk", product)
    if module != "tasks" and module in _disabled_modules(product_id):
        return "none"
    if is_org_admin(user):
        return "manage"
    entry = _membership_map(user).get(product_id)
    if not entry:
        return "none"
    if module in entry["overrides"]:
        return entry["overrides"][module]
    return ROLE_DEFAULTS.get(entry["role"], ROLE_DEFAULTS["viewer"])(module)


def has_level(user, product, module, level="read"):
    return LEVELS[module_level(user, product, module)] >= LEVELS[level]


def accessible_products(user):
    """Products the user may see at all."""
    from apps.products.models import Product

    if not user or not user.is_authenticated or not user.is_active:
        return Product.objects.none()
    if is_org_admin(user):
        return Product.objects.all()
    return Product.objects.filter(pk__in=list(_membership_map(user).keys()), is_active=True)


def product_ids_for(user, module, level="read"):
    """IDs of products where the user has at least ``level`` on ``module`` (and the module is enabled)."""
    from apps.products.models import Product

    if not user or not user.is_authenticated or not user.is_active:
        return []
    disabled = _disabled_map() if module != "tasks" else {}
    if is_org_admin(user):
        ids = Product.objects.values_list("pk", flat=True)
        return [pid for pid in ids if module not in disabled.get(pid, set())]
    out = []
    for pid, entry in _membership_map(user).items():
        if module in disabled.get(pid, set()):
            continue
        lvl = entry["overrides"].get(module) or ROLE_DEFAULTS.get(entry["role"], ROLE_DEFAULTS["viewer"])(module)
        if LEVELS[lvl] >= LEVELS[level]:
            out.append(pid)
    return out


def can_manage_product(user, product):
    if is_org_admin(user):
        return True
    entry = _membership_map(user).get(getattr(product, "pk", product))
    return bool(entry and entry["role"] == "product_manager")


def scoped_queryset(user, resource, level="read", product=None, include_shared=True):
    """
    Records of ``resource`` the user may access at ``level``.

    A record is visible when its primary product is permitted, or (for read access)
    when it is shared with a permitted product. Write access always requires
    permission on the record's primary product.
    """
    model = resource.model
    ids = product_ids_for(user, resource.module, level)
    if product is not None:
        pid = getattr(product, "pk", product)
        ids = [i for i in ids if i == pid]
    if not ids:
        return model.objects.none()
    condition = Q(product_id__in=ids)
    if include_shared and level == "read":
        through = model.shared_products.through
        fk_name = model._meta.model_name
        shared_ids = through.objects.filter(product_id__in=ids).values(fk_name)
        condition |= Q(pk__in=shared_ids)
    return model.objects.filter(condition)


def can_edit_record(user, record):
    return has_level(user, record.product_id, record.resource.module, "write")


def can_delete_record(user, record):
    return has_level(user, record.product_id, record.resource.module, "manage")


def module_levels_for_user(user, product):
    """{module_key: level} for display/navigation."""
    from apps.core.registry import registry

    return {m.key: module_level(user, product, m.key) for m in registry.modules(include_tasks=True)}
