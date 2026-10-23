from django.db import models

from apps.core.models import BaseRecord


class DemoEvent(BaseRecord):
    RESOURCE_KEY = "events"

    class Mode(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline / in person"
        HYBRID = "hybrid", "Hybrid"

    name = models.CharField("Event name", max_length=200)
    organizer = models.CharField(max_length=200, blank=True)
    website = models.URLField("Event website", blank=True)
    location = models.CharField(max_length=200, blank=True)
    event_mode = models.CharField("Online / offline", max_length=10, choices=Mode.choices, default=Mode.OFFLINE)
    registration_deadline = models.DateField(null=True, blank=True)
    event_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    presentation_url = models.URLField("Presentation URL", blank=True)
    leads_collected = models.PositiveIntegerField(default=0)
    expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    outcomes = models.TextField("Event outcomes", blank=True)
    follow_up_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "demo day / event"
        constraints = [
            models.CheckConstraint(condition=models.Q(expenses__gte=0), name="demo_event_expenses_non_negative"),
        ]

    def __str__(self):
        return self.name
