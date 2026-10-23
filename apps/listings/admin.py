from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import ListingPlatform, ListingRecord


@admin.register(ListingPlatform)
class ListingPlatformAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "website_url", "is_active", "display_order")
    list_filter = ("kind", "is_active")
    search_fields = ("name",)


@admin.register(ListingRecord)
class ListingRecordAdmin(RecordAdmin):
    list_display = ("platform", "product", "status", "verification_status", "submission_date", "assigned_to")
    search_fields = ("platform__name", "listing_url")
