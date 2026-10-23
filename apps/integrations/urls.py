from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("", login_required(views.integration_list), name="list"),
    path("<slug:provider>/", login_required(views.integration_edit), name="edit"),
    path("<slug:provider>/test/", login_required(views.integration_test), name="test"),
    path("<slug:provider>/disconnect/", login_required(views.integration_disconnect), name="disconnect"),
]
