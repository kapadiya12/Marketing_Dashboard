from decimal import Decimal

from django.db import models

from apps.core.models import BaseRecord


class AdCampaign(BaseRecord):
    RESOURCE_KEY = "advertising"

    class Channel(models.TextChoices):
        META = "meta", "Meta (Facebook / Instagram)"
        LINKEDIN = "linkedin", "LinkedIn"

    class Objective(models.TextChoices):
        AWARENESS = "awareness", "Awareness"
        TRAFFIC = "traffic", "Traffic"
        ENGAGEMENT = "engagement", "Engagement"
        LEADS = "leads", "Lead generation"
        CONVERSIONS = "conversions", "Conversions"
        VIDEO_VIEWS = "video_views", "Video views"
        OTHER = "other", "Other"

    name = models.CharField("Campaign name", max_length=200)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.META)
    objective = models.CharField(max_length=20, choices=Objective.choices, default=Objective.LEADS)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    actual_spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impressions = models.PositiveBigIntegerField(default=0)
    reach = models.PositiveBigIntegerField(default=0)
    clicks = models.PositiveBigIntegerField(default=0)
    leads = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    landing_page_url = models.URLField("Landing page", blank=True)
    external_campaign_id = models.CharField(
        max_length=100, blank=True, help_text="Campaign ID in Meta/LinkedIn, used by future API sync."
    )

    class Meta(BaseRecord.Meta):
        verbose_name = "ad campaign"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(start_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="ad_campaign_dates_valid",
            ),
            models.CheckConstraint(condition=models.Q(budget__gte=0) & models.Q(actual_spend__gte=0),
                                   name="ad_campaign_money_non_negative"),
        ]

    def __str__(self):
        return self.name

    @property
    def ctr(self):
        """Click-through rate in percent."""
        if not self.impressions:
            return None
        return (Decimal(self.clicks) / Decimal(self.impressions) * 100).quantize(Decimal("0.01"))

    @property
    def cpc(self):
        if not self.clicks:
            return None
        return (self.actual_spend / Decimal(self.clicks)).quantize(Decimal("0.01"))

    @property
    def cost_per_lead(self):
        if not self.leads:
            return None
        return (self.actual_spend / Decimal(self.leads)).quantize(Decimal("0.01"))

    @property
    def budget_used_pct(self):
        if not self.budget:
            return None
        return int(self.actual_spend / self.budget * 100)
