from django.db import models

from apps.core.models import TimeStampedModel

from .crypto import decrypt_json, encrypt_json


class IntegrationConfiguration(TimeStampedModel):
    class Provider(models.TextChoices):
        META_ADS = "meta_ads", "Meta Ads"
        LINKEDIN_ADS = "linkedin_ads", "LinkedIn Ads"
        GOOGLE_ANALYTICS = "google_analytics", "Google Analytics"
        SEARCH_CONSOLE = "search_console", "Google Search Console"
        EMAIL_PROVIDER = "email_provider", "Email provider"
        GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
        OUTLOOK_CALENDAR = "outlook_calendar", "Microsoft Outlook Calendar"
        FILE_STORAGE = "file_storage", "File storage"

    class Status(models.TextChoices):
        NOT_CONFIGURED = "not_configured", "Not Configured"
        CONNECTED = "connected", "Connected"
        ERROR = "error", "Connection Error"
        EXPIRED = "expired", "Authorization Expired"

    provider = models.CharField(max_length=30, choices=Provider.choices)
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, null=True, blank=True,
        help_text="Leave blank for an organization-wide connection.",
    )
    display_name = models.CharField(max_length=120, blank=True)
    is_enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_CONFIGURED)
    settings = models.JSONField(default=dict, blank=True, help_text="Non-secret settings (account IDs, etc.).")
    secret_data = models.TextField(blank=True, editable=False)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["provider", "product"]
        constraints = [models.UniqueConstraint(fields=["provider", "product"], name="unique_integration_scope")]

    def __str__(self):
        return f"{self.get_provider_display()} ({self.product or 'Organization'})"

    @property
    def secrets(self):
        return decrypt_json(self.secret_data)

    def set_secrets(self, data):
        self.secret_data = encrypt_json(data) if data else ""

    @property
    def has_secrets(self):
        return bool(self.secret_data)
