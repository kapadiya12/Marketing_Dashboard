from django.conf import settings
from django.db import models

from apps.core.models import BaseRecord


class SEOTrackingRecord(BaseRecord):
    RESOURCE_KEY = "seo"

    class OptimizationType(models.TextChoices):
        SEO = "seo", "SEO — search engine"
        GEO = "geo", "GEO — generative engine"
        AEO = "aeo", "AEO — answer engine"

    class SearchPlatform(models.TextChoices):
        GOOGLE = "google", "Google Search"
        GOOGLE_AI = "google_ai", "Google AI Overviews"
        BING = "bing", "Bing"
        CHATGPT = "chatgpt", "ChatGPT"
        PERPLEXITY = "perplexity", "Perplexity"
        GEMINI = "gemini", "Gemini"
        COPILOT = "copilot", "Microsoft Copilot"
        CLAUDE = "claude", "Claude"
        OTHER = "other", "Other"

    keyword = models.CharField("Keyword / query", max_length=255)
    optimization_type = models.CharField(max_length=5, choices=OptimizationType.choices, default=OptimizationType.SEO)
    search_platform = models.CharField(max_length=20, choices=SearchPlatform.choices, default=SearchPlatform.GOOGLE)
    landing_page_url = models.URLField("Landing page", blank=True)
    target_ranking = models.PositiveIntegerField(null=True, blank=True, help_text="Target position (1 = top).")
    baseline_ranking = models.PositiveIntegerField(null=True, blank=True)
    baseline_date = models.DateField(null=True, blank=True)
    measured_ranking = models.PositiveIntegerField("Latest ranking", null=True, blank=True)
    last_measured_date = models.DateField("Last measured", null=True, blank=True)
    ai_mentioned = models.BooleanField(
        "Cited by AI engine", null=True, blank=True, help_text="Leave blank until it has actually been checked."
    )
    ai_citation_url = models.URLField("AI citation / mention URL", blank=True)
    target_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "SEO / GEO / AEO record"

    def __str__(self):
        return f"{self.keyword} ({self.get_optimization_type_display().split(' ')[0]})"

    @property
    def on_target(self):
        if self.measured_ranking and self.target_ranking:
            return self.measured_ranking <= self.target_ranking
        return None

    @property
    def ranking_change(self):
        if self.measured_ranking and self.baseline_ranking:
            return self.baseline_ranking - self.measured_ranking
        return None


class SEOMeasurement(models.Model):
    """Historical measurement; the most recent one updates the parent record's latest ranking."""

    record = models.ForeignKey(SEOTrackingRecord, on_delete=models.CASCADE, related_name="measurements")
    measured_on = models.DateField()
    ranking = models.PositiveIntegerField(null=True, blank=True)
    ai_mentioned = models.BooleanField("Cited by AI", null=True, blank=True)
    citation_url = models.URLField(blank=True)
    source = models.CharField(max_length=100, blank=True, help_text="Tool or method used, e.g. Search Console.")
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measured_on", "-created_at"]

    def __str__(self):
        return f"{self.record.keyword} @ {self.measured_on}: {self.ranking or '—'}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        latest = self.record.measurements.order_by("-measured_on", "-created_at").first()
        if latest:
            rec = self.record
            rec.measured_ranking = latest.ranking
            rec.last_measured_date = latest.measured_on
            if latest.ai_mentioned is not None:
                rec.ai_mentioned = latest.ai_mentioned
            if latest.citation_url:
                rec.ai_citation_url = latest.citation_url
            if rec.baseline_ranking is None and latest.ranking:
                first = rec.measurements.order_by("measured_on", "created_at").first()
                rec.baseline_ranking = first.ranking
                rec.baseline_date = first.measured_on
            rec.save()


class SEOUpdate(models.Model):
    """A short progress update for SEO / GEO / AEO work (optionally about one keyword)."""

    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="seo_updates")
    record = models.ForeignKey(SEOTrackingRecord, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="updates", verbose_name="Keyword / query")
    text = models.TextField("Update")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField("Posted", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "SEO / GEO update"

    def __str__(self):
        return self.text[:80]
