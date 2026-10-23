from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.permissions import scoped_queryset

from .exporting import export_filename, export_tables, requested_format
from .filtering import search_q
from .statuses import get_status
from .models import Notification
from .registry import registry


@login_required
def global_search(request):
    term = (request.GET.get("q") or "").strip()
    groups = []
    fmt = requested_format(request)
    if len(term) >= 2:
        for resource in registry.resources():
            qs = scoped_queryset(request.user, resource, "read").filter(is_archived=False)
            qs = qs.filter(search_q(resource, term)).select_related("product")
            total = qs.count()
            if total:
                groups.append({"resource": resource, "items": list(qs[:1000] if fmt else qs[:8]), "total": total})
    if fmt:
        rows = [[g["resource"].label, str(o), o.product.name, get_status(g["resource"].key, o.status).label,
                 request.build_absolute_uri(o.get_absolute_url())] for g in groups for o in g["items"]]
        return export_tables([{"title": f"Search results for {term}", "headers": ["Type", "Record", "Product",
                                                                               "Status", "Link"], "rows": rows}],
                             fmt, export_filename("search", term[:30]), f"Search: {term}")
    template = "search/_results.html" if request.headers.get("HX-Request") == "true" else "search/results.html"
    return render(request, template, {"q": term, "groups": groups})


@login_required
def notification_list(request):
    qs = Notification.objects.filter(user=request.user)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page": page})


@login_required
def notification_dropdown(request):
    items = Notification.objects.filter(user=request.user)[:8]
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return render(request, "notifications/_dropdown.html", {"items": items, "unread": unread})


@login_required
@require_POST
def notification_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    if n.url and url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}):
        return redirect(n.url)
    return redirect("notifications:list")


@login_required
@require_POST
def notification_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(
        request.POST.get("next"), allowed_hosts={request.get_host()}) else "notifications:list")
