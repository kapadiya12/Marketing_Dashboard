from django.urls import path

from . import views

app_name = "investors"

urlpatterns = [
    path("snapshot/", views.pipeline_snapshot, name="snapshot"),
    path("<slug:slug>/snapshot/", views.pipeline_snapshot, name="product_snapshot"),
]
