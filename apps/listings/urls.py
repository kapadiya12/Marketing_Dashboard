from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("platform-report/", views.platform_report, name="platform_report"),
]
