from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.urls_misc import notification_patterns, search_patterns
from apps.core.views import import_hub

admin.site.site_header = "Business Dashboard — Maintenance"
admin.site.site_title = "Business Dashboard Admin"

def healthz(request):
    """Render's health check: answers without touching the database (no Turso sync either)."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", RedirectView.as_view(pattern_name="analytics:dashboard", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.analytics.urls")),
    path("products/", include("apps.products.urls")),
    path("records/", include("apps.core.urls")),
    path("import/", import_hub, name="import_hub"),
    path("search/", include(search_patterns)),
    path("notifications/", include(notification_patterns)),
    path("reports/", include("apps.analytics.urls_reports")),
    path("listings/", include("apps.listings.urls")),
    path("investors/", include("apps.investors.urls")),
    path("seo/", include("apps.seo_optimization.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("email-marketing/", include("apps.email_marketing.urls")),
    path("admin-panel/", include("apps.admin_panel.urls")),
    path("integrations/", include("apps.integrations.urls")),
    path("api/v1/", include("apps.api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Product logos are public brand images; serve them in production too. Attachments are never
    # served from here — they always go through the permission-checked download view.
    from django.urls import re_path
    from django.views.static import serve

    urlpatterns += [re_path(r"^media/(?P<path>product_logos/[\w\-. ]+)$", serve,
                            {"document_root": settings.MEDIA_ROOT})]
