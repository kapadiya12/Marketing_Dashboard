from django.urls import path

from . import views

app_name = "records"

urlpatterns = [
    path("module/<slug:module>/", views.module_redirect, name="module"),
    path("attachments/<int:att_id>/download/", views.attachment_download, name="attachment_download"),
    path("attachments/<int:att_id>/delete/", views.attachment_delete, name="attachment_delete"),
    path("<slug:resource>/", views.record_list, name="list"),
    path("<slug:resource>/new/", views.record_create, name="create"),
    path("<slug:resource>/export/", views.record_export, name="export"),
    path("<slug:resource>/import/", views.record_import, name="import"),
    path("<slug:resource>/import/template/", views.import_template, name="import_template"),
    path("<slug:resource>/bulk/", views.bulk_action, name="bulk"),
    path("<slug:resource>/<int:pk>/", views.record_detail, name="detail"),
    path("<slug:resource>/<int:pk>/edit/", views.record_edit, name="edit"),
    path("<slug:resource>/<int:pk>/export/", views.record_detail_export, name="detail_export"),
    path("<slug:resource>/<int:pk>/delete/", views.record_delete, name="delete"),
    path("<slug:resource>/<int:pk>/archive/", views.record_archive, name="archive"),
    path("<slug:resource>/<int:pk>/restore/", views.record_restore, name="restore"),
    path("<slug:resource>/<int:pk>/status/", views.record_status, name="status"),
    path("<slug:resource>/<int:pk>/attachments/", views.attachment_upload, name="attachment_upload"),
    path("<slug:resource>/<int:pk>/<slug:child>/add/", views.child_add, name="child_add"),
    path("<slug:resource>/<int:pk>/<slug:child>/import/", views.child_import, name="child_import"),
    path("<slug:resource>/<int:pk>/<slug:child>/<int:child_pk>/delete/", views.child_delete, name="child_delete"),
]
