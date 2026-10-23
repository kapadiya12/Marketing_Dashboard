"""
Create in-app reminder notifications. Schedule daily (cron / Task Scheduler / Celery beat):

    python manage.py send_reminders

Idempotent: a dedupe key prevents duplicate notifications for the same item and day.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core import metrics as m
from apps.core.notifications import notify
from apps.core.registry import registry


class Command(BaseCommand):
    help = "Create in-app notifications for task reminders, due follow-ups and overdue items."

    def handle(self, *args, **options):
        today = timezone.localdate()
        created = 0
        for res in registry.resources():
            model = res.model
            base = model.objects.filter(is_archived=False).exclude(assigned_to=None).filter(m.open_q(res.key))
            if res.key == "tasks":
                for task in base.filter(reminder_date=today).select_related("product", "assigned_to"):
                    if notify(task.assigned_to, f"Reminder: {task.title}",
                              f"Due {task.due_date or 'no date'} · {task.product}", task.get_absolute_url(),
                              "warning", task.product, f"task-reminder-{task.pk}-{today}"):
                        created += 1
            if not res.due_field:
                continue
            for obj in base.filter(**{res.due_field: today}).select_related("product", "assigned_to"):
                if notify(obj.assigned_to, f"Due today: {obj}", f"{res.label} · {obj.product}",
                          obj.get_absolute_url(), "warning", obj.product, f"due-{res.key}-{obj.pk}-{today}"):
                    created += 1
            for obj in base.filter(**{f"{res.due_field}__lt": today}).select_related("product", "assigned_to"):
                if notify(obj.assigned_to, f"Overdue: {obj}",
                          f"{res.label} · {obj.product} · was due {getattr(obj, res.due_field)}",
                          obj.get_absolute_url(), "danger", obj.product, f"overdue-{res.key}-{obj.pk}-{today}"):
                    created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} in-app notification(s)."))
