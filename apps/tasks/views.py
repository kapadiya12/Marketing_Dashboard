import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import accessible_products, scoped_queryset
from apps.core import metrics as m
from apps.core.registry import registry
from apps.core.exporting import export_filename, export_tables, plain, requested_format
from apps.core.statuses import get_status, get_statuses


@login_required
def overview(request):
    """Today's tasks, follow-ups, meetings, demo days and investor follow-ups (only what the user may see)."""
    today = timezone.localdate()
    week = today + datetime.timedelta(days=7)
    mine = request.GET.get("mine") == "1"
    slug = request.GET.get("product")
    product = accessible_products(request.user).filter(slug=slug).first() if slug else None

    def qs(key):
        q = scoped_queryset(request.user, registry.get(key), "read", product=product).filter(is_archived=False)
        if mine:
            q = q.filter(assigned_to=request.user)
        return q.select_related("product", "assigned_to")

    tasks = qs("tasks").filter(m.open_q("tasks"))
    followups = []
    for res in registry.activity_resources():
        if res.due_field and res.key not in ("investors",):
            for obj in qs(res.key).filter(m.open_q(res.key)).filter(
                    **{f"{res.due_field}__gte": today, f"{res.due_field}__lte": week}).order_by(res.due_field)[:20]:
                followups.append({"object": obj, "resource": res, "due": getattr(obj, res.due_field)})
    followups.sort(key=lambda x: x["due"])
    ctx = {
        "mine": mine,
        "product": product,
        "products": accessible_products(request.user).filter(is_active=True),
        "today_tasks": tasks.filter(due_date=today),
        "overdue_tasks": tasks.filter(due_date__lt=today).order_by("due_date"),
        "upcoming_tasks": tasks.filter(due_date__gt=today, due_date__lte=week).order_by("due_date"),
        "followups": followups[:30],
        "today_meetings": qs("meetings").filter(start_at__date=today).order_by("start_at"),
        "upcoming_events": qs("events").filter(event_date__gte=today).filter(m.open_q("events")).order_by(
            "event_date")[:10],
        "investor_followups": qs("investors").filter(follow_up_date__isnull=False, follow_up_date__lte=week).filter(
            m.open_q("investors")).order_by("follow_up_date")[:15],
        "today": today,
        "tasks_resource": registry.get("tasks"),
        "task_statuses": get_statuses("tasks"),
    }
    fmt = requested_format(request)
    if fmt:
        def task_rows(items):
            return [[t.title, t.product.name, t.get_priority_display(), plain(t.due_date),
                     get_status("tasks", t.status).label, plain(t.assigned_to)] for t in items]

        task_headers = ["Task", "Product", "Priority", "Due", "Status", "Assigned to"]
        tables = [
            {"title": "Overdue tasks", "headers": task_headers, "rows": task_rows(ctx["overdue_tasks"])},
            {"title": "Today's tasks", "headers": task_headers, "rows": task_rows(ctx["today_tasks"])},
            {"title": "Upcoming tasks (7 days)", "headers": task_headers, "rows": task_rows(ctx["upcoming_tasks"])},
            {"title": "Follow-ups this week", "headers": ["Due", "Module", "Record", "Product", "Assigned to"],
             "rows": [[f["due"], f["resource"].label, str(f["object"]), f["object"].product.name,
                       plain(f["object"].assigned_to)] for f in followups]},
            {"title": "Today's meetings", "headers": ["Time", "Meeting", "Company", "Product", "Link"],
             "rows": [[plain(mt.start_at), mt.title, mt.customer_company, mt.product.name, mt.meeting_link]
                      for mt in ctx["today_meetings"]]},
            {"title": "Upcoming demo days", "headers": ["Date", "Event", "Organizer", "Product", "Register by"],
             "rows": [[e.event_date, e.name, e.organizer, e.product.name, plain(e.registration_deadline)]
                      for e in ctx["upcoming_events"]]},
            {"title": "Investor follow-ups", "headers": ["Follow-up", "Investor", "Product", "Stage"],
             "rows": [[i.follow_up_date, i.name, i.product.name, get_status("investors", i.status).label]
                      for i in ctx["investor_followups"]]},
        ]
        return export_tables(tables, fmt, export_filename("my-day", product.slug if product else ""),
                             "My day & follow-ups", f"{today:%A, %d %B %Y}")
    return render(request, "tasks/overview.html", ctx)
