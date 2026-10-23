from django.contrib import admin

from .models import (
    Attachment,
    Category,
    CustomFieldDefinition,
    CustomFieldValue,
    DashboardItem,
    ModuleSetting,
    Notification,
    StatusOption,
    Tag,
    Target,
)


@admin.register(StatusOption)
class StatusOptionAdmin(admin.ModelAdmin):
    list_display = ("resource", "label", "key", "state", "color", "order", "is_active")
    list_filter = ("resource", "state", "is_active")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "resource", "product", "is_active")
    list_filter = ("resource", "product")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color")
    search_fields = ("name",)


@admin.register(CustomFieldDefinition)
class CustomFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = ("resource", "label", "key", "field_type", "product", "required", "is_active")
    list_filter = ("resource", "field_type")


admin.site.register(CustomFieldValue)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "content_type", "object_id", "product", "uploaded_by", "created_at")
    list_filter = ("product", "content_type")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ("product", "metric", "label", "target_value", "period_start", "period_end")
    list_filter = ("product", "metric")


admin.site.register(DashboardItem)
admin.site.register(ModuleSetting)
