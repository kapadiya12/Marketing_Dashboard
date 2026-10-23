from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.permissions import has_level, scoped_queryset
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.registry import registry
from apps.products.models import Product

from .models import SEOUpdate


@login_required
@require_POST
def add_update(request):
    """Post a short SEO / GEO update from the box on the SEO page."""
    text = (request.POST.get("text") or "").strip()
    nxt = request.POST.get("next") or "/records/seo/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/records/seo/"
    if not text:
        messages.warning(request, "Write an update before posting.")
        return redirect(nxt)
    record = None
    record_id = request.POST.get("record") or ""
    if record_id.isdigit():
        record = scoped_queryset(request.user, registry.get("seo"), "write").filter(pk=int(record_id)).first()
    product = record.product if record else Product.objects.filter(pk=request.POST.get("product") or 0).first()
    if product is None or not has_level(request.user, product, "seo", "write"):
        raise PermissionDenied("You cannot post SEO updates for this product.")
    update = SEOUpdate.objects.create(product=product, record=record, text=text[:5000], created_by=request.user)
    log_action(AuditLog.Action.CREATE, record or update, request.user, product=product, resource="seo",
               message=f"SEO / GEO update: {text[:120]}")
    messages.success(request, "Update posted.")
    return redirect(nxt + "#seo-updates")


@login_required
@require_POST
def delete_update(request, pk):
    update = SEOUpdate.objects.filter(pk=pk).select_related("product").first()
    if update is None or not (update.created_by_id == request.user.pk
                              or has_level(request.user, update.product, "seo", "manage")):
        raise PermissionDenied
    update.delete()
    messages.success(request, "Update removed.")
    nxt = request.POST.get("next") or "/records/seo/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/records/seo/"
    return redirect(nxt + "#seo-updates")
