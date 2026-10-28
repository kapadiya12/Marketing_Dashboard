"""
Imports that run in a separate process (``manage.py run_import_job``).

On Turso every write is a network round trip to the database, and the driver keeps the whole Python
process busy while it waits. Running a big import inside the web request froze that web worker (other
pages stopped loading) until Render restarted it, which ended the upload in a 502. Instead the upload is
kept in a job folder, a separate process replays the same import page as the uploading user, and the
browser polls the job until it can show the result.

A job is a folder in ``settings.IMPORT_JOB_DIR`` holding the uploaded file and ``job.json``. Both web
workers and the import process run on the same machine, so no database table is needed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.http import Http404

STALE_SECONDS = 15 * 60  # a running job that has not reported for this long has died (e.g. out of memory)
KEEP_SECONDS = 24 * 60 * 60
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_children = []  # import processes started by this web worker, reaped when finished


def enabled():
    return settings.IMPORT_IN_BACKGROUND


def _root():
    return Path(settings.IMPORT_JOB_DIR)


def _folder(job_id):
    if not _JOB_ID.match(job_id or ""):
        raise Http404
    return _root() / job_id


def save(job):
    job["updated"] = time.time()
    path = _folder(job["id"]) / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job), encoding="utf-8")
    os.replace(tmp, path)


def read(job_id):
    try:
        return json.loads((_folder(job_id) / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load(job_id, user):
    """The user's job, marked failed if its process stopped without finishing."""
    job = read(job_id)
    if job is None or job["user_id"] != user.pk:
        raise Http404
    if job["status"] in ("queued", "running") and time.time() - job["updated"] > STALE_SECONDS:
        job.update(status="failed", error="The import stopped unexpectedly. Please upload the file again.")
        save(job)
    return job


def start(request, upload):
    """Keep the upload and start the import process; returns the job id."""
    _cleanup()
    job_id = uuid.uuid4().hex
    folder = _folder(job_id)
    folder.mkdir(parents=True)
    name = re.sub(r"[^\w.\- ]", "_", os.path.basename(upload.name))[:120] or "upload.csv"
    with open(folder / name, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    save({
        "id": job_id, "user_id": request.user.pk, "path": request.get_full_path(), "filename": name,
        "fields": {k: v for k, v in request.POST.lists() if k != "csrfmiddlewaretoken"},
        "status": "queued", "stage": "", "done": 0, "total": 0, "started": time.time(),
    })
    _spawn(job_id)
    return job_id


def _spawn(job_id):
    for proc in list(_children):
        if proc.poll() is not None:
            _children.remove(proc)
    log = open(_folder(job_id) / "process.log", "ab")
    detach = {"start_new_session": True} if os.name == "posix" else {}
    _children.append(subprocess.Popen(
        [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "run_import_job", job_id],
        cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **detach))
    log.close()


def _cleanup():
    root = _root()
    if not root.is_dir():
        return
    for folder in root.iterdir():
        try:
            if time.time() - folder.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- the import process

def run(job_id):
    """Replay the upload against its import page as the uploading user (``manage.py run_import_job``)."""
    from django.contrib.auth import get_user_model
    from django.contrib.messages.storage.base import BaseStorage
    from django.test import RequestFactory
    from django.urls import resolve

    class CapturedMessages(BaseStorage):
        def _get(self, *args, **kwargs):
            return [], True

        def _store(self, messages, response, *args, **kwargs):
            return []

    job = read(job_id)
    if job is None or job["status"] != "queued":
        return
    job["status"] = "running"
    save(job)
    try:
        user = get_user_model().objects.get(pk=job["user_id"], is_active=True)
        host = next((h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")), "localhost")
        with open(_folder(job_id) / job["filename"], "rb") as upload:
            data = {k: v if len(v) > 1 else v[0] for k, v in job["fields"].items()}
            request = RequestFactory(HTTP_HOST=host).post(job["path"], {**data, "file": upload})
        request.user = user
        from importlib import import_module

        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        request._messages = CapturedMessages(request)
        request._import_job = job
        last = [0.0]

        def progress(stage, done, total):
            if time.time() - last[0] >= 1 or done == total:
                last[0] = time.time()
                job.update(stage=stage, done=done, total=total)
                save(job)

        request._import_progress = progress
        match = resolve(request.path_info)
        request.resolver_match = match
        response = match.func(request, *match.args, **match.kwargs)
        result = getattr(request, "_import_result", None)
        job.update(
            status="done",
            location=response["Location"] if response.status_code in (301, 302) else "",
            result=result,
            messages=[(m.level, str(m.message), m.extra_tags) for m in request._messages._queued_messages],
        )
    except Exception as exc:  # reported to the user; the traceback goes to process.log
        import traceback

        traceback.print_exc()
        job.update(status="failed", error=f"The import failed: {exc}")
    save(job)
