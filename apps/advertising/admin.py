from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import AdCampaign


@admin.register(AdCampaign)
class AdCampaignAdmin(RecordAdmin):
    list_display = ("name", "channel", "product", "status", "budget", "actual_spend", "leads")
    search_fields = ("name", "external_campaign_id")
