from django.urls import path

from apps.core import views as record_views

from . import views

app_name = "products"

urlpatterns = [
    path("", views.product_list, name="list"),
    path("<slug:slug>/", views.product_dashboard, name="dashboard"),
    path("<slug:slug>/records/<slug:resource>/", record_views.record_list, name="records"),
    path("<slug:slug>/records/<slug:resource>/new/", record_views.record_create, name="record_create"),
    path("<slug:slug>/records/<slug:resource>/export/", record_views.record_export, name="record_export"),
    path("<slug:slug>/records/<slug:resource>/import/", record_views.record_import, name="record_import"),
]
