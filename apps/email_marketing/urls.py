from django.urls import path

from . import views

app_name = "email_marketing"

urlpatterns = [
    path("open/", views.open_email_dashboard, name="open"),
    path("summary/", views.summary, name="summary"),
]
