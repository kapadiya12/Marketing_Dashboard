from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import CommunityPost


@admin.register(CommunityPost)
class CommunityPostAdmin(RecordAdmin):
    list_display = ("topic", "platform", "community", "product", "status", "publication_date")
    search_fields = ("topic", "community")
