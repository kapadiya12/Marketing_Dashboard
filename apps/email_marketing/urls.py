from django.urls import path

from . import views

app_name = "email_marketing"

urlpatterns = [
    path("", views.email_dashboard, name="dashboard"),
    path("open/", views.open_email_dashboard, name="open"),
    path("summary/", views.summary, name="summary"),
]
