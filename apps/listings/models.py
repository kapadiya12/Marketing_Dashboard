from django.db import models

from apps.core.models import BaseRecord, TimeStampedModel


class ListingPlatform(TimeStampedModel):
    """A directory, marketplace or review site where products can be listed (catalog only)."""

    class Kind(models.TextChoices):
        SOFTWARE_DIRECTORY = "software_directory", "Software directory"
        REVIEW_SITE = "review_site", "Review site"
        STARTUP_DIRECTORY = "startup_directory", "Startup directory / launch platform"
        BUSINESS_LISTING = "business_listing", "Business listing"
        MARKETPLACE = "marketplace", "Marketplace"
        SOCIAL_PROFILE = "social_profile", "Social / company profile"
        COMMUNITY = "community", "Community"
        OTHER = "other", "Other"

    name = models.CharField(max_length=120, unique=True)
    website_url = models.URLField(blank=True)
    kind = models.CharField("Platform type", max_length=30, choices=Kind.choices, default=Kind.SOFTWARE_DIRECTORY)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class ListingRecord(BaseRecord):
    RESOURCE_KEY = "listings"

    class Verification(models.TextChoices):
        UNVERIFIED = "unverified", "Not verified"
        PENDING = "pending", "Verification pending"
        VERIFIED = "verified", "Verified live"
        FAILED = "failed", "Verification failed"

    platform = models.ForeignKey(ListingPlatform, on_delete=models.PROTECT, related_name="listings")
    listing_url = models.URLField("Listing URL", blank=True)
    submission_date = models.DateField(null=True, blank=True)
    verification_status = models.CharField(max_length=20, choices=Verification.choices, default=Verification.UNVERIFIED)
    last_checked_date = models.DateField("Last checked", null=True, blank=True)
    next_verification_date = models.DateField("Next verification", null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "listing"
        constraints = [models.UniqueConstraint(fields=["platform", "product"], name="unique_listing_per_platform_product")]

    def __str__(self):
        return f"{self.platform} — {self.product}"

    @property
    def website_url(self):
        return self.platform.website_url
