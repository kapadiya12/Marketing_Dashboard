from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.core.models import BaseRecord


class Task(BaseRecord):
    RESOURCE_KEY = "tasks"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    related_module = models.CharField(max_length=40, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False)
    object_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    related_record = GenericForeignKey("content_type", "object_id")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    reminder_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField("Completion date", null=True, blank=True)

    class Meta(BaseRecord.Meta):
        ordering = ["due_date", "-priority", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        from apps.core.statuses import keys_in_state

        if self.status in keys_in_state(self.RESOURCE_KEY, "completed"):
            self.completed_at = self.completed_at or timezone.now()
        else:
            self.completed_at = None
        if self.content_type_id and not self.related_module:
            from apps.core.registry import registry

            res = registry.resource_for_model(self.content_type.model_class())
            if res:
                self.related_module = res.module
        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        from apps.core.statuses import keys_in_state

        return bool(
            self.due_date and self.due_date < timezone.localdate()
            and self.status not in keys_in_state(self.RESOURCE_KEY, "completed", "closed")
        )
