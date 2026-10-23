from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Core platform"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("resources")
