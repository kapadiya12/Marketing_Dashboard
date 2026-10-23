from django.urls import path

from . import views

app_name = "admin_panel"

urlpatterns = [
    path("", views.index, name="index"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/modules/", views.product_modules, name="product_modules"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/members/add/", views.membership_add, name="membership_add"),
    path("members/<int:pk>/", views.membership_edit, name="membership_edit"),
    path("members/<int:pk>/remove/", views.membership_remove, name="membership_remove"),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/import/", views.users_import, name="users_import"),
    path("products/import/", views.products_import, name="products_import"),
    path("products/<int:pk>/members/import/", views.members_import, name="members_import"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
    path("modules/", views.module_overview, name="modules"),
    path("dashboard-layout/", views.dashboard_layout, name="dashboard_layout"),
    path("table-columns/", views.table_columns, name="table_columns"),
    path("notifications/", views.broadcast, name="broadcast"),
    path("audit-log/", views.audit_log, name="audit"),
    path("attachments/", views.attachments, name="attachments"),
    path("config/statuses/defaults/", views.statuses_materialize, name="statuses_materialize"),
    path("config/<slug:key>/", views.config_list, name="config_list"),
    path("config/<slug:key>/new/", views.config_edit, name="config_create"),
    path("config/<slug:key>/import/", views.config_import, name="config_import"),
    path("config/<slug:key>/<int:pk>/", views.config_edit, name="config_edit"),
    path("config/<slug:key>/<int:pk>/delete/", views.config_delete, name="config_delete"),
]
