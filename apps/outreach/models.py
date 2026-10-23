from django.db import models
from django.utils import timezone

from apps.core.models import BaseRecord


class EmailCampaign(BaseRecord):
    RESOURCE_KEY = "email_campaigns"

    name = models.CharField("Campaign", max_length=200)
    subject = models.CharField("Default subject", max_length=255, blank=True)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "email campaign"

    def __str__(self):
        return self.name


class Lead(BaseRecord):
    """A contact/company. ``unsubscribed`` suppresses all further outreach to this address for the product."""

    RESOURCE_KEY = "leads"

    company = models.CharField(max_length=200)
    contact_name = models.CharField("Contact", max_length=150, blank=True)
    email = models.EmailField("Business email")
    phone = models.CharField(max_length=40, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    industry = models.CharField(max_length=120, blank=True)
    lead_source = models.CharField(max_length=120, blank=True)
    unsubscribed = models.BooleanField(default=False, db_index=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "lead"
        constraints = [models.UniqueConstraint(fields=["product", "email"], name="unique_lead_email_per_product")]

    def __str__(self):
        return f"{self.contact_name or self.email} ({self.company})"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if self.unsubscribed and not self.unsubscribed_at:
            self.unsubscribed_at = timezone.now()
        if not self.unsubscribed:
            self.unsubscribed_at = None
        super().save(*args, **kwargs)


class EmailActivity(BaseRecord):
    """One outreach email (and its follow-ups) to one contact."""

    RESOURCE_KEY = "outreach"

    class Delivery(models.TextChoices):
        NOT_SENT = "not_sent", "Not sent"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        BOUNCED = "bounced", "Bounced"
        FAILED = "failed", "Failed"

    class Reply(models.TextChoices):
        NO_REPLY = "no_reply", "No reply"
        POSITIVE = "positive", "Replied — positive"
        NEUTRAL = "neutral", "Replied — neutral"
        NEGATIVE = "negative", "Replied — negative"
        AUTO = "auto", "Auto-reply"

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities", editable=False)
    company = models.CharField(max_length=200)
    contact_name = models.CharField("Contact", max_length=150, blank=True)
    email = models.EmailField("Business email")
    industry = models.CharField(max_length=120, blank=True)
    lead_source = models.CharField(max_length=120, blank=True)
    subject = models.CharField("Email subject", max_length=255, blank=True)
    sent_date = models.DateField(null=True, blank=True)
    delivery_status = models.CharField(max_length=12, choices=Delivery.choices, default=Delivery.NOT_SENT)
    reply_status = models.CharField(max_length=12, choices=Reply.choices, default=Reply.NO_REPLY)
    follow_up_date = models.DateField(null=True, blank=True)
    meeting_booked = models.BooleanField(default=False)
    unsubscribed = models.BooleanField("Unsubscribe requested", default=False)

    class Meta(BaseRecord.Meta):
        verbose_name = "email outreach"
        verbose_name_plural = "email outreach"

    def __str__(self):
        return f"{self.email} — {self.subject or self.company}"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        lead, created = Lead.objects.get_or_create(
            product_id=self.product_id,
            email=self.email,
            defaults={
                "company": self.company,
                "contact_name": self.contact_name,
                "industry": self.industry,
                "lead_source": self.lead_source,
                "status": "contacted",
                "assigned_to": self.assigned_to,
                "created_by": self.created_by,
            },
        )
        if self.unsubscribed and not lead.unsubscribed:
            lead.unsubscribed = True
            lead.save()
        self.lead = lead
        super().save(*args, **kwargs)
