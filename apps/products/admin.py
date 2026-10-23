from django.contrib import admin

from .models import MembershipModulePermission, Product, ProductMembership, ProductModuleConfiguration


class MembershipInline(admin.TabularInline):
    model = ProductMembership
    extra = 0
    autocomplete_fields = ["user"]


class ModuleConfigInline(admin.TabularInline):
    model = ProductModuleConfiguration
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "display_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ModuleConfigInline, MembershipInline]


class ModulePermissionInline(admin.TabularInline):
    model = MembershipModulePermission
    extra = 0


@admin.register(ProductMembership)
class ProductMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "role", "is_active")
    list_filter = ("product", "role", "is_active")
    search_fields = ("user__username", "user__email")
    inlines = [ModulePermissionInline]
