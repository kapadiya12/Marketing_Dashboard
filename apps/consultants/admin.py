from django.contrib import admin

from apps.core.admin_base import RecordAdmin

from .models import Consultant, ConsultantInteraction


class InteractionInline(admin.TabularInline):
    model = ConsultantInteraction
    extra = 0


@admin.register(Consultant)
class ConsultantAdmin(RecordAdmin):
    list_display = ("name", "organization", "expertise", "product", "status", "last_interaction_date")
    search_fields = ("name", "organization", "expertise")
    inlines = [InteractionInline]
