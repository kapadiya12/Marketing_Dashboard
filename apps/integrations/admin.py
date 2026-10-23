from django.contrib import admin

from .models import IntegrationConfiguration


@admin.register(IntegrationConfiguration)
class IntegrationConfigurationAdmin(admin.ModelAdmin):
    list_display = ("provider", "product", "status", "is_enabled", "last_tested_at")
    list_filter = ("provider", "status")
    exclude = ("secret_data",)
    readonly_fields = ("status", "last_tested_at", "last_synced_at", "last_error")
