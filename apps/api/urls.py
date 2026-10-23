from django.urls import path

from . import views

app_name = "api"

record_list = views.ResourceViewSet.as_view({"get": "list", "post": "create"})
record_detail = views.ResourceViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path("", views.resource_list, name="index"),
    path("products/", views.product_list, name="products"),
    path("dashboard/metrics/", views.dashboard_metrics, name="dashboard_metrics"),
    path("records/<slug:resource>/", record_list, name="record_list"),
    path("records/<slug:resource>/<int:pk>/", record_detail, name="record_detail"),
]
