from django.contrib import admin


class RecordAdmin(admin.ModelAdmin):
    """Shared Django admin configuration for BaseRecord models (internal maintenance)."""

    list_filter = ("product", "status", "is_archived")
    list_select_related = ("product", "assigned_to")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by", "archived_at")
    filter_horizontal = ("shared_products", "tags")
    date_hierarchy = "created_at"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
