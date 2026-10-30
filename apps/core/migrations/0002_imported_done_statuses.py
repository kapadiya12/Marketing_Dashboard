"""Statuses created by imports were always open, so records marked "Completed" or "Done" never counted as done."""
from django.db import migrations


def fix_states(apps, schema_editor):
    from apps.core.statuses import guess_state

    StatusOption = apps.get_model("core", "StatusOption")
    for status in StatusOption.objects.filter(order=50, state="open"):
        state, color = guess_state(status.label)
        if state != "open":
            status.state, status.color = state, color
            status.save(update_fields=["state", "color"])


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(fix_states, migrations.RunPython.noop)]
