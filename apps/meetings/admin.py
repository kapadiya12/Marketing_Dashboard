from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import CustomerMeeting


@admin.register(CustomerMeeting)
class CustomerMeetingAdmin(RecordAdmin):
    list_display = ("title", "customer_company", "product", "start_at", "status", "outcome")
    search_fields = ("title", "customer_company", "contact_person")
