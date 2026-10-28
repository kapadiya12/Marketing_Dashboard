from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import ColdCall


@admin.register(ColdCall)
class ColdCallAdmin(RecordAdmin):
    list_display = ("contact_name", "company", "product", "channel", "contact_date", "status", "outcome")
    search_fields = ("contact_name", "company", "phone")
