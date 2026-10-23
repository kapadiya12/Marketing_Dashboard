from django.conf import settings
from django.db import models

from apps.core.models import BaseRecord, TimeStampedModel


class InvestorCategory(TimeStampedModel):
    """Configurable *prospective* investor categories (not confirmed relationships)."""

    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "investor categories"

    def __str__(self):
        return self.name


class Investor(BaseRecord):
    RESOURCE_KEY = "investors"

    class Stage(models.TextChoices):
        PRE_SEED = "pre_seed", "Pre-seed"
        SEED = "seed", "Seed"
        SERIES_A = "series_a", "Series A"
        SERIES_B = "series_b", "Series B+"
        GROWTH = "growth", "Growth"
        MULTI = "multi", "Multi-stage"

    class FundingStatus(models.TextChoices):
        NOT_DISCUSSED = "not_discussed", "Not discussed"
        EXPLORING = "exploring", "Exploring"
        TERM_SHEET = "term_sheet", "Term sheet received"
        COMMITTED = "committed", "Committed (confirmed)"
        DECLINED = "declined", "Declined"

    name = models.CharField("Investor / fund name", max_length=200)
    investor_category = models.ForeignKey(
        InvestorCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="investors",
        verbose_name="Investor category",
    )
    website = models.URLField(blank=True)
    investment_thesis = models.TextField(blank=True)
    industry_focus = models.CharField(max_length=255, blank=True)
    investment_stage = models.CharField(max_length=10, choices=Stage.choices, blank=True)
    investment_range = models.CharField(
        "Verified investment range", max_length=100, blank=True,
        help_text="Only enter a range confirmed from the investor's official sources.",
    )
    contact_person = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    introduction_source = models.CharField(max_length=200, blank=True)
    meeting_date = models.DateTimeField(null=True, blank=True)
    pitch_deck_url = models.URLField("Pitch deck link", blank=True)
    meeting_notes = models.TextField(blank=True)
    feedback = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    funding_target = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    funding_discussed = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    funding_status = models.CharField(max_length=15, choices=FundingStatus.choices, default=FundingStatus.NOT_DISCUSSED)

    class Meta(BaseRecord.Meta):
        verbose_name = "investor"

    def __str__(self):
        return self.name


class InvestorInteraction(models.Model):
    class Kind(models.TextChoices):
        EMAIL = "email", "Email"
        CALL = "call", "Call"
        MEETING = "meeting", "Meeting"
        PITCH = "pitch", "Pitch"
        INTRO = "intro", "Introduction"
        OTHER = "other", "Other"

    investor = models.ForeignKey(Investor, on_delete=models.CASCADE, related_name="interactions")
    date = models.DateField()
    interaction_type = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EMAIL)
    summary = models.TextField()
    next_step = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.investor} · {self.date}"
