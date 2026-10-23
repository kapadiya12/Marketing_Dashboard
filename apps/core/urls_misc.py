from django.urls import path

from . import views_misc

search_patterns = ([path("", views_misc.global_search, name="global")], "search")

notification_patterns = (
    [
        path("", views_misc.notification_list, name="list"),
        path("dropdown/", views_misc.notification_dropdown, name="dropdown"),
        path("<int:pk>/read/", views_misc.notification_read, name="read"),
        path("read-all/", views_misc.notification_read_all, name="read_all"),
    ],
    "notifications",
)
