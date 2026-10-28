from django.db import models
from django.utils import timezone

from apps.core.models import BaseRecord


class ColdCall(BaseRecord):
    """One cold call or direct message (WhatsApp, LinkedIn, SMS) to a prospect."""

    RESOURCE_KEY = "calls"

    class Channel(models.TextChoices):
        PHONE = "phone", "Phone call"
        WHATSAPP = "whatsapp", "WhatsApp"
        LINKEDIN = "linkedin", "LinkedIn message"
        SMS = "sms", "SMS"
        OTHER = "other", "Other"

    class Outcome(models.TextChoices):
        NO_ANSWER = "no_answer", "No answer"
        CALL_BACK = "call_back", "Call back later"
        INTERESTED = "interested", "Interested"
        MEETING = "meeting", "Meeting booked"
        NOT_INTERESTED = "not_interested", "Not interested"

    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.PHONE)
    contact_name = models.CharField(max_length=150)
    company = models.CharField(max_length=200, blank=True)
    phone = models.CharField("Phone / profile", max_length=255, blank=True,
                             help_text="Phone number, or the LinkedIn / WhatsApp profile link.")
    contact_date = models.DateField("Date", default=timezone.localdate)
    outcome = models.CharField(max_length=15, choices=Outcome.choices, default=Outcome.NO_ANSWER)
    follow_up_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "cold call / message"
        verbose_name_plural = "cold calls & messages"
        ordering = ["-contact_date", "-created_at"]

    def __str__(self):
        return f"{self.contact_name}{f' ({self.company})' if self.company else ''}"
