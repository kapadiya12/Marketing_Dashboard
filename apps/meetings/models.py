from django.db import models

from apps.core.models import BaseRecord


class CustomerMeeting(BaseRecord):
    RESOURCE_KEY = "meetings"

    class MeetingType(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "In person"
        PHONE = "phone", "Phone call"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        POSITIVE = "positive", "Positive — next steps agreed"
        NEUTRAL = "neutral", "Neutral"
        NEGATIVE = "negative", "Not interested"
        WON = "won", "Deal won"
        LOST = "lost", "Deal lost"

    title = models.CharField("Meeting title", max_length=200)
    customer_company = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    meeting_type = models.CharField(max_length=10, choices=MeetingType.choices, default=MeetingType.ONLINE)
    start_at = models.DateTimeField("Date & time")
    end_at = models.DateTimeField("Ends", null=True, blank=True)
    meeting_link = models.URLField(blank=True)
    venue = models.CharField(max_length=255, blank=True)
    agenda = models.TextField(blank=True)
    participants = models.TextField(blank=True, help_text="One per line.")
    meeting_notes = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    action_items = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    opportunity_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.PENDING)

    class Meta(BaseRecord.Meta):
        verbose_name = "customer meeting"
        ordering = ["-start_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True) | models.Q(end_at__gte=models.F("start_at")),
                name="meeting_end_after_start",
            ),
        ]

    def __str__(self):
        return self.title
