from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.permissions import accessible_products, module_level, product_ids_for, scoped_queryset
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.filtering import apply_filters
from apps.core.registry import registry

from .snapshot import build_snapshot


@login_required
def pipeline_snapshot(request, slug=None):
    """Download a standalone HTML page of the investor pipeline, using the list page's current filters."""
    resource = registry.get("investors")
    product = None
    if slug:
        product = get_object_or_404(accessible_products(request.user), slug=slug)
        if module_level(request.user, product, "investors") == "none":
            raise PermissionDenied
    elif not product_ids_for(request.user, "investors", "read"):
        raise PermissionDenied
    qs = scoped_queryset(request.user, resource, "read", product=product)
    qs = apply_filters(qs, resource, request.GET, {p.slug: p for p in accessible_products(request.user)})
    include_private = request.GET.get("private") == "1"
    if product is None and request.GET.get("product"):
        product = accessible_products(request.user).filter(slug=request.GET["product"]).first()
    scope = product.name if product else "All products"
    labels = []
    if request.GET.get("q"):
        labels.append(f"search “{request.GET['q']}”")
    if request.GET.getlist("status"):
        labels.append("selected stages")
    html = build_snapshot(qs, scope=scope, include_private=include_private,
                          prepared_by=request.user.get_full_name() or request.user.username,
                          filters_label=", ".join(labels))
    log_action(AuditLog.Action.EXPORT, None, request.user, resource="investors", product=product,
               message=f"Investor pipeline HTML snapshot ({qs.count()} investors{', with private fields' if include_private else ''})")
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    name = f"investor-pipeline-{product.slug if product else 'all'}-{timezone.localdate():%Y%m%d}.html"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
