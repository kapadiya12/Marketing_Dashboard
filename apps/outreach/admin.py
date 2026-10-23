from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import EmailActivity, EmailCampaign, Lead


@admin.register(EmailCampaign)
class EmailCampaignAdmin(RecordAdmin):
    list_display = ("name", "product", "status", "start_date")
    search_fields = ("name",)


@admin.register(Lead)
class LeadAdmin(RecordAdmin):
    list_display = ("email", "company", "contact_name", "product", "status", "unsubscribed")
    search_fields = ("email", "company", "contact_name")


@admin.register(EmailActivity)
class EmailActivityAdmin(RecordAdmin):
    list_display = ("email", "company", "campaign", "product", "delivery_status", "reply_status", "meeting_booked")
    search_fields = ("email", "company", "subject")
