import glob
import os

from django.core.management.base import BaseCommand
from django.db import connections

from apps.core import import_jobs


class Command(BaseCommand):
    help = "Run one uploaded import in this process (started by the import page; see apps/core/import_jobs.py)."

    def add_arguments(self, parser):
        parser.add_argument("job_id")

    def handle(self, *args, job_id, **options):
        try:
            import_jobs.run(job_id)
        finally:
            connections.close_all()
            # This process's Turso replica files (config/turso_backend: one per process and thread).
            for conn in connections.all():
                replica_dir = conn.settings_dict.get("OPTIONS", {}).get("replica_dir")
                if replica_dir:
                    for path in glob.glob(os.path.join(replica_dir, f"{conn.alias}-{os.getpid()}-*")):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
