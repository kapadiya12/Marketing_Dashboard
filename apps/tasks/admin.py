from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import Task


@admin.register(Task)
class TaskAdmin(RecordAdmin):
    list_display = ("title", "product", "priority", "status", "due_date", "assigned_to")
    search_fields = ("title", "description")
