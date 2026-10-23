from django.urls import path

from . import views

app_name = "seo"

urlpatterns = [
    path("updates/add/", views.add_update, name="add_update"),
    path("updates/<int:pk>/delete/", views.delete_update, name="delete_update"),
]
