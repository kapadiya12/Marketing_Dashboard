from django.conf import settings
from django.db import models

from apps.core.models import BaseRecord


class Consultant(BaseRecord):
    RESOURCE_KEY = "consultants"

    name = models.CharField("Consultant name", max_length=150)
    organization = models.CharField(max_length=200, blank=True)
    expertise = models.CharField(max_length=255, blank=True)
    industry = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    profile_url = models.URLField("Public professional profile", blank=True)
    last_interaction_date = models.DateField("Last interaction", null=True, blank=True)
    recommendations = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "consultant"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ConsultantInteraction(models.Model):
    class Kind(models.TextChoices):
        MEETING = "meeting", "Meeting"
        CALL = "call", "Call"
        EMAIL = "email", "Email"
        WORKSHOP = "workshop", "Workshop / session"
        OTHER = "other", "Other"

    consultant = models.ForeignKey(Consultant, on_delete=models.CASCADE, related_name="interactions")
    date = models.DateField()
    interaction_type = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MEETING)
    summary = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.consultant} · {self.date}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        c = self.consultant
        if not c.last_interaction_date or self.date > c.last_interaction_date:
            c.last_interaction_date = self.date
            c.save(update_fields=["last_interaction_date", "updated_at"])
