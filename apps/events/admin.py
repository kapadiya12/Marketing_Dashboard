from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import DemoEvent


@admin.register(DemoEvent)
class DemoEventAdmin(RecordAdmin):
    list_display = ("name", "organizer", "product", "event_date", "status", "leads_collected")
    search_fields = ("name", "organizer")
