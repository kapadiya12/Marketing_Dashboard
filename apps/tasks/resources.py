from django.utils import timezone

from apps.core import metrics as m
from apps.core.registry import Resource, registry

from .models import Task


def due_today(qs):
    return qs.filter(m.open_q("tasks"), due_date=timezone.localdate())


def urgent(qs):
    return qs.filter(m.open_q("tasks"), priority__in=["urgent", "high"])


PRESETS = {"due_today": ("Open tasks due today", due_today),
           "urgent": ("Open urgent / high-priority tasks", urgent)}


def kpis(qs, ctx):
    return [
        m.kpi("Open tasks", qs.filter(m.open_q("tasks")).count(), "bi-list-task", "primary", link={"state": "open"}),
        m.kpi("Due today", due_today(qs).count(), "bi-calendar-day", "warning", link={"preset": "due_today"}),
        m.kpi("Overdue", qs.filter(m.overdue_q(registry.get("tasks"))).count(), "bi-exclamation-triangle", "danger",
              link={"overdue": "1"}),
        m.kpi("Completed", qs.filter(m.completed_q("tasks")).count(), "bi-check2-all", "success",
              link={"state": "completed"}),
        m.kpi("Urgent / high", urgent(qs).count(), "bi-lightning", "danger", link={"preset": "urgent"}),
    ]


def charts(qs, ctx):
    return [
        m.status_breakdown_chart(qs, registry.get("tasks"), "task_status", "Task status"),
        m.choice_breakdown(qs.filter(m.open_q("tasks")), "priority", Task.Priority.choices, "task_priority",
                           "Open tasks by priority"),
    ]


registry.register(Resource(
    key="tasks",
    module="tasks",
    model_path="tasks.Task",
    label="Task",
    label_plural="Tasks & Follow-ups",
    icon="bi-check2-square",
    primary=True,
    form_fields=["product", "title", "priority", "status", "due_date", "assigned_to", "notes"],
    list_columns=["title", "product", "priority", "status", "due_date", "assigned_to"],
    search_fields=["title", "description", "notes"],
    sort_fields=["title", "priority", "due_date", "reminder_date", "created_at"],
    filter_fields=["priority"],
    default_statuses=[
        ("todo", "To Do", "open", "secondary"),
        ("in_progress", "In Progress", "open", "info"),
        ("blocked", "Blocked", "open", "warning"),
        ("done", "Done", "completed", "success"),
        ("cancelled", "Cancelled", "closed", "dark"),
    ],
    date_field="created_at",
    due_field="due_date",
    calendar_field="due_date",
    presets=PRESETS,
    kpis=kpis,
    charts=charts,
))
