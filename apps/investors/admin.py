from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import Investor, InvestorCategory, InvestorInteraction


@admin.register(InvestorCategory)
class InvestorCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "display_order")


class InteractionInline(admin.TabularInline):
    model = InvestorInteraction
    extra = 0


@admin.register(Investor)
class InvestorAdmin(RecordAdmin):
    list_display = ("name", "investor_category", "product", "status", "meeting_date", "funding_status")
    search_fields = ("name", "contact_person")
    inlines = [InteractionInline]
