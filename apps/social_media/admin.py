from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import SocialPost


@admin.register(SocialPost)
class SocialPostAdmin(RecordAdmin):
    list_display = ("title", "platform", "product", "status", "post_date", "likes", "reach")
    search_fields = ("title", "post_url")
