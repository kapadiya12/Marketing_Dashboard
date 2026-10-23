from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import SEOMeasurement, SEOTrackingRecord


class MeasurementInline(admin.TabularInline):
    model = SEOMeasurement
    extra = 0


@admin.register(SEOTrackingRecord)
class SEOTrackingRecordAdmin(RecordAdmin):
    list_display = ("keyword", "optimization_type", "search_platform", "product", "measured_ranking",
                    "target_ranking", "status")
    search_fields = ("keyword",)
    inlines = [MeasurementInline]
